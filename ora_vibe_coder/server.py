"""Loopback-only foreground HTTP utility; no generic file-serving route."""

import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import secrets
import ssl
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import conversation
from .handoff import PLUGIN, STAGES, prepare_request, stated_code_location
from .hosts import HOSTS as TOOL_LABELS, continue_in, discover
from .launcher import Settings, documents_location
from .project import Conflict, ProjectError, ProjectStore, ROLES

# A 4 MiB packet can expand sixfold when JSON escapes control characters.
# This bounded transport ceiling accommodates a full saved packet plus input.
REQUEST_LIMIT = 32 * 1024 * 1024
STATIC = Path(__file__).parent / "static"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
          "/static/style.css": ("style.css", "text/css; charset=utf-8"),
          "/static/vendor/markdown-it.min.js": ("vendor/markdown-it.min.js", "application/javascript; charset=utf-8")}
WORKSPACES = ("specification", "plan", "build")
RELEASE_LOOKUP_URL = "https://api.github.com/repos/ora-commons/ora-vibe-coder/releases/latest"
UPDATE_STEPS = ("Download the new release, choose Stop Vibe, open the new release's setup, "
                "and choose Install or update Vibe and selected entries.")


def lookup_latest_release(url=RELEASE_LOOKUP_URL, timeout=5):
    """One standard-library HTTPS question about the newest public release.

    A short timeout and a User-Agent header are sent; nothing else is asked,
    downloaded, or installed. A freshly installed python.org Python has no
    certificates until its Install Certificates step runs, so on macOS one
    certificate failure is retried against /etc/ssl/cert.pem before giving up.
    """
    for attempt in (None, "/etc/ssl/cert.pem"):
        context = ssl.create_default_context(cafile=attempt) if attempt else None
        request = urllib.request.Request(url, headers={"User-Agent": "Ora Vibe Coder update check"})
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as error:
            if (attempt is None and sys.platform == "darwin"
                    and isinstance(getattr(error, "reason", None), ssl.SSLCertVerificationError)
                    and Path("/etc/ssl/cert.pem").is_file()):
                continue
            raise
    raise OSError(f"Update lookup did not finish: {url}")


def release_answer(release, running):
    """Compare one GitHub release record with the running version.

    Four answers: newer (names the release and links its page with the update
    steps), same, ahead, or can't tell — any failure, rate limit, or unreadable
    answer is can't tell and is never reported as up to date.
    """
    unparsable = {"answer": "cant_tell", "label": "Couldn't check for updates.", "url": None,
                  "note": "The check failed, was rate-limited, or returned an unreadable answer, "
                          "so no update conclusion is offered. Nothing was downloaded or installed."}
    tag = release.get("tag_name") if isinstance(release, dict) else None
    page = release.get("html_url") if isinstance(release, dict) else None
    numbers = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag if isinstance(tag, str) else "")
    here = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", running)
    if not numbers or not here or not isinstance(page, str) or not page.startswith("https://"):
        return unparsable
    latest = tuple(int(part) for part in numbers.groups())
    current = tuple(int(part) for part in here.groups())
    if latest > current:
        release_version = ".".join(numbers.groups())
        return {"answer": "newer", "label": f"Version {release_version} is available.",
                "url": page, "note": UPDATE_STEPS}
    if latest == current:
        return {"answer": "same", "label": "You are up to date.",
                "url": None, "note": f"This copy ({running}) is the newest public release."}
    older = ".".join(numbers.groups())
    return {"answer": "ahead", "label": f"This copy ({running}) is newer than the newest public release ({older}).",
            "url": None, "note": "No public release is newer than this copy."}


def shape(data, required, optional=()):
    if not isinstance(data, dict) or set(data) - set(required) - set(optional) or set(required) - set(data):
        raise ProjectError("Malformed request fields.")


def strings(data, keys):
    if any(not isinstance(data[key], str) for key in keys):
        raise ProjectError("Expected text fields.")


class LocalServer(HTTPServer):
    def __init__(self, home=None, port=0, settings=None, install_home=None, update_lookup=None):
        self.settings = settings
        self.install_home = Path(install_home) if install_home else None
        self.store = ProjectStore(home) if home else None
        self.token = secrets.token_urlsafe(32)
        # The one network-capable operation, reached only when the user presses
        # Check for updates. A stand-in lookup can be supplied for tests.
        self.update_lookup = update_lookup or lookup_latest_release
        # Work-turn operation handles: in memory only, bound to their
        # originating project; the .vibe/ records on disk are the truth.
        self.conversation = conversation.TurnRegistry()
        # One boolean in memory: does the displayed main instruction input hold
        # text right now? Never the text itself, and never stored on disk.
        self.visible_input = False
        # After Stop: no new work is admitted while the in-flight turns drain.
        self.stopping = False
        self.shutdown_thread = None
        # Background Bridge readiness facts, refreshed on request; a check
        # makes no model call and stores only what `bridge check` reports.
        self.readiness_lock = threading.Lock()
        self.readiness = None
        self.readiness_thread = None
        # One retained explicit recheck: a Recheck arriving while a sweep runs
        # is honored after that sweep instead of being silently dropped.
        self.readiness_pending = False
        super().__init__(("127.0.0.1", port), Handler)
        self.host = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.host}"
        self.timeout = 1

    @property
    def url(self):
        return f"{self.origin}/#{self.token}"

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def preferences(self):
        try:
            return self.settings.read() if self.settings else {}
        except (OSError, ValueError):
            return {}

    def remember_project(self, path):
        if not self.settings:
            return
        path = str(path)
        recent = [item for item in self.preferences().get("recent_projects", [])
                  if isinstance(item, str) and item != path]
        self.settings.update(recent_projects=[path, *recent[:7]], last_project=path)

    def remember_workspace(self, workspace):
        if self.settings and workspace in WORKSPACES:
            self.settings.update(last_workspace=workspace)

    def readiness_refresh(self):
        """Start one background readiness sweep unless one is already running.

        An explicit recheck arriving while a sweep runs is retained — once,
        never queued in depth — and runs as soon as that sweep completes, so a
        sign-in repaired mid-sweep is reflected rather than the sweep's
        already-stale result standing. Ordinary polls never call this: they
        only read the report.
        """
        with self.readiness_lock:
            if self.stopping:
                return
            if self.readiness_thread is not None and self.readiness_thread.is_alive():
                self.readiness_pending = True
                return
            self.readiness_pending = False
            self.readiness_thread = threading.Thread(target=self._readiness_worker, daemon=True,
                                                     name="Ora Vibe Coder readiness check")
            self.readiness_thread.start()

    def _readiness_worker(self):
        results = []
        for peer in conversation.PEERS:
            if self.stopping:
                break
            facts = conversation.bridge_check(peer, stop_requested=lambda: self.stopping)
            facts["label"] = TOOL_LABELS[peer][0]
            results.append(facts)
        with self.readiness_lock:
            self.readiness = results
            if self.readiness_pending and not self.stopping:
                # The one retained explicit recheck: its sweep starts inside
                # this same locked step that stores these results, so a reader
                # never observes a moment where no sweep runs and none waits.
                self.readiness_pending = False
                self.readiness_thread = threading.Thread(target=self._readiness_worker, daemon=True,
                                                         name="Ora Vibe Coder readiness check")
                self.readiness_thread.start()
            else:
                self.readiness_thread = None

    def readiness_report(self):
        with self.readiness_lock:
            checking = self.readiness_thread is not None and self.readiness_thread.is_alive()
            peers = self.readiness
        # Harness facts only: Bridge's own check reports capability and sign-in
        # truth. No model/provider identity is claimed from a harness name.
        return {"checking": checking, "peers": peers}

    def begin_shutdown(self):
        """Stop work the user chose to interrupt, then close owned processes."""
        if self.shutdown_thread is not None:
            return
        self.stopping = True
        def finish():
            conversation.end_checks()
            self.conversation.drain()
            with self.readiness_lock:
                readiness = self.readiness_thread
            if readiness is not None:
                readiness.join(10)
            self.shutdown()

        self.shutdown_thread = threading.Thread(target=finish, daemon=False,
                                               name="Ora Vibe Coder shutdown")
        self.shutdown_thread.start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log tokens, input, or file paths.

    def reply(self, code, data, kind="application/json; charset=utf-8"):
        payload = json.dumps(data).encode("utf-8") if isinstance(data, (dict, list)) else data
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # The one inline script in index.html's head applies a stored light/dark
        # choice before first paint; its exact hash is allowlisted below.
        # img-src adds blob: only for the fresh paste/upload previews held in
        # memory; retained originals still load through the same-origin route.
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self' 'sha256-F67S4cyeDKHZWHZkYuZA9hhcE79TgOLNss519TC/CRQ='; style-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def boundary(self, authenticated):
        if self.headers.get_all("Host") != [self.server.host]:
            raise PermissionError("Unrecognized local host.")
        origins = self.headers.get_all("Origin")
        if origins and origins != [self.server.origin]:
            raise PermissionError("Cross-origin requests are not permitted.")
        if authenticated and not hmac.compare_digest(self.headers.get("X-Ora-Token", ""), self.server.token):
            raise PermissionError("Open the launch URL from the local terminal to authorize this tab.")

    def do_GET(self):
        try:
            self.boundary(False)
            if urllib.parse.urlsplit(self.path).path == "/api/attachment":
                self.attachment()
                return
            if self.path not in ASSETS:
                self.reply(404, {"error": "No such page."})
                return
            name, kind = ASSETS[self.path]
            self.reply(200, (STATIC / name).read_bytes(), kind)
        except PermissionError as error:
            self.reply(403, {"error": str(error)})
        except OSError:
            self.reply(500, {"error": "A packaged interface file is missing."})

    def attachment(self):
        """One retained original attachment, same-origin, behind the full boundary.

        An image element cannot carry the tab's token header, so this one GET
        route accepts the identical token from its query string; the host and
        origin checks are unchanged, and everything else about the boundary is
        the same as every other route. Only an original retained with an
        opened project's turn is served, exactly the bytes saved with it.
        """
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if (set(query) != {"token", "id", "turn", "name"}
                or any(len(values) != 1 for values in query.values())):
            self.reply(400, {"error": "Malformed attachment request."})
            return
        if not hmac.compare_digest(query["token"][0], self.server.token):
            raise PermissionError("Open the launch URL from the local terminal to authorize this tab.")
        identifier, turn, name = query["id"][0], query["turn"][0], query["name"][0]
        kinds = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
        project = self.server.store.projects.get(identifier) if self.server.store else None
        folder = project.root / conversation.VIBE / turn / "attachments" if project is not None else None
        target = folder / name if folder is not None else None
        # Confinement covers every path component below the project's reserved
        # .vibe root: a symbolic link on the retained-attachment folder, on its
        # turn folder, or on .vibe itself would serve bytes from outside the
        # project through an otherwise valid name, because resolving both
        # sides of a containment comparison follows the same link. Hard links
        # cannot be distinguished on this route; containment is judged on path
        # resolution, links included.
        linked = project is not None and any(
            path.is_symlink() for path in (
                project.root / conversation.VIBE,
                project.root / conversation.VIBE / turn,
                folder, target))
        if (project is None or not re.fullmatch(r"\d{4}-\d{8}-\d{6}", turn)
                or not re.fullmatch(r"\d{4}-[A-Za-z0-9._-]+", name)
                or Path(name).suffix.lower() not in kinds
                or linked or not target.is_file()
                or target.resolve().parent != folder.resolve()):
            self.reply(404, {"error": "No retained attachment matches this request."})
            return
        try:
            data = target.read_bytes()
        except OSError:
            self.reply(404, {"error": "No retained attachment matches this request."})
            return
        self.reply(200, data, kinds[Path(name).suffix.lower()])

    def do_POST(self):
        try:
            self.boundary(True)
            if self.headers.get("Transfer-Encoding") or self.headers.get_all("Content-Length") is None or len(self.headers.get_all("Content-Length")) != 1:
                raise ProjectError("A single bounded Content-Length is required.")
            length = int(self.headers.get("Content-Length"))
            if length < 0 or length > REQUEST_LIMIT:
                raise ProjectError("Request exceeds the 32 MiB transport limit. Input has not been saved.")
            if self.headers.get("Content-Type") != "application/json":
                raise ProjectError("Expected JSON content.")
            data = json.loads(self.rfile.read(length))
            result = self.action(data)
            self.reply(200, result)
        except Conflict as error:
            self.reply(409, {"error": str(error), "current": error.current})
        except PermissionError as error:
            self.reply(403, {"error": str(error)})
        except (ProjectError, ValueError, TypeError, KeyError, OSError) as error:
            self.reply(400, {"error": str(error)})

    def action(self, data):
        path = self.path
        if path == "/api/setup":
            shape(data, [])
            documents = documents_location()
            preferences = self.server.preferences()
            recent = [item for item in preferences.get("recent_projects", []) if isinstance(item, str)][:8]
            return {"home": str(self.server.store.home) if self.server.store else None,
                    "browse_home": str(documents or Path.home()),
                    "browse_note": "" if documents else "Your Documents folder was not found, so browsing starts at your home folder. No project was created or selected.",
                    "recent_projects": recent,
                    "last_project": preferences.get("last_project", ""),
                    "last_workspace": preferences.get("last_workspace", ""),
                    "split_orientation": preferences.get("split_orientation", "split"),
                    "split_fraction": preferences.get("split_fraction", 0.42),
                    "version": (PLUGIN / "VERSION").read_text(encoding="utf-8").strip(),
                    "hosts": discover(), "installation": self.server.install_home is not None}
        if path == "/api/install":
            shape(data, ["hosts"])
            from .installer import install, SKILL_HOMES
            if self.server.install_home is None:
                raise ProjectError("Open the supplied installer to install or update Vibe. Stop the installed application before updating.")
            if not isinstance(data["hosts"], list) or not data["hosts"] or any(not isinstance(host, str) or host not in SKILL_HOMES for host in data["hosts"]):
                raise ProjectError("Select the coding tools to configure.")
            return install(home=self.server.install_home, hosts=list(dict.fromkeys(data["hosts"])))
        if path == "/api/remove":
            shape(data, ["hosts"])
            from .installer import remove, SKILL_HOMES
            if self.server.install_home is None:
                raise ProjectError("Open the supplied installer to remove Vibe. Stop the installed application first.")
            if not isinstance(data["hosts"], list) or any(not isinstance(host, str) or host not in SKILL_HOMES for host in data["hosts"]):
                raise ProjectError("Select the coding tools whose Vibe entries should be removed.")
            return remove(home=self.server.install_home, hosts=list(dict.fromkeys(data["hosts"])))
        if path == "/api/folders":
            shape(data, ["path"], ["limit"])
            strings(data, ["path"])
            if "limit" in data and not isinstance(data["limit"], str):
                raise ProjectError("Expected the browsing boundary.")
            folder = Path(data["path"]).expanduser().resolve(strict=True)
            limit = Path(data["limit"]).expanduser().resolve(strict=True) if "limit" in data else None
            if not folder.is_dir():
                raise ProjectError("Select an existing folder.")
            if limit is not None and folder != limit and not folder.is_relative_to(limit):
                raise ProjectError("Choose a folder inside your Documents folder.")
            children = sorted((p for p in folder.iterdir() if p.is_dir() and not p.name.startswith('.')), key=lambda p: p.name.casefold())
            parent = folder.parent
            if limit is not None and parent != limit and not parent.is_relative_to(limit):
                parent = limit  # Browsing upward stops at the Documents boundary.
            return {"path": str(folder), "parent": str(parent),
                    "folders": [{"name": p.name, "path": str(p)} for p in children[:500]], "limited": len(children) > 500}
        if path == "/api/browse-files":
            shape(data, ["path"])
            strings(data, ["path"])
            folder = Path(data["path"]).expanduser().resolve(strict=True)
            if not folder.is_dir():
                raise ProjectError("Select an existing folder.")
            children = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
            parent = folder.parent
            entries = [{"name": p.name, "path": str(p), "directory": p.is_dir()}
                       for p in children[:500]
                       if not p.name.startswith(".") and not p.is_symlink()
                       and (p.is_dir() or (p.is_file() and p.suffix.lower() in {".md", ".markdown", ".txt"}))]
            return {"path": str(folder), "parent": str(parent), "entries": entries, "limited": len(children) > 500}
        if path == "/api/create-folder":
            shape(data, ["parent", "name"])
            strings(data, ["parent", "name"])
            name = data["name"]
            if (not name or name in {".", ".."} or "/" in name or "\\" in name
                    or Path(name).name != name):
                raise ProjectError("Use one new child folder name, with no slashes or parent traversal.")
            parent = Path(data["parent"]).expanduser().resolve(strict=True)
            if not parent.is_dir():
                raise ProjectError("Select an existing folder to create inside.")
            target = parent / name
            target.mkdir()  # An existing folder is never overwritten.
            return {"path": str(target)}
        if path == "/api/workspace":
            shape(data, ["workspace"])
            strings(data, ["workspace"])
            if data["workspace"] not in WORKSPACES:
                raise ProjectError("Unknown workspace.")
            self.server.remember_workspace(data["workspace"])
            return {"workspace": data["workspace"]}
        if path == "/api/input-state":
            shape(data, ["visible"])
            if not isinstance(data["visible"], bool):
                raise ProjectError("Expected the visible-input state.")
            self.server.visible_input = data["visible"]
            return {"recorded": True}
        if path == "/api/quit-state":
            shape(data, [])
            return {"visible_input": self.server.visible_input,
                    "active_turns": len(self.server.conversation.in_flight())}
        if path == "/api/check-updates":
            shape(data, [])
            # One deliberate HTTPS question to the public release record,
            # asked only because the user pressed the button: nothing is
            # downloaded, installed, or replaced, and no background moment
            # ever contacts the network.
            version = (PLUGIN / "VERSION").read_text(encoding="utf-8").strip()
            try:
                return release_answer(self.server.update_lookup(), version)
            except (OSError, ValueError):
                return release_answer(None, version)
        if path == "/api/readiness":
            shape(data, [], ["recheck"])
            if "recheck" in data and not isinstance(data["recheck"], bool):
                raise ProjectError("Expected the recheck selection.")
            # An ordinary poll only reads the current report; it never starts
            # the worker, so the client's poll chain ends naturally once a
            # check finishes instead of every poll restarting it. Only an
            # explicit recheck — startup's first check or the Recheck button —
            # starts one background probe (no model call), still behind the
            # single-worker guard; a recheck that arrives while a sweep runs
            # is retained once and runs when that sweep completes. A recheck
            # after resolving sign-in or permissions is never a retry of
            # consequential work.
            if data.get("recheck"):
                self.server.readiness_refresh()
            return self.server.readiness_report()
        if path == "/api/preferences":
            shape(data, [], ["split_orientation", "split_fraction"])
            updates = {}
            if "split_orientation" in data:
                if data["split_orientation"] not in {"split", "stacked"}:
                    raise ProjectError("Unknown split orientation.")
                updates["split_orientation"] = data["split_orientation"]
            if "split_fraction" in data:
                value = data["split_fraction"]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.05 <= value <= 0.95:
                    raise ProjectError("Invalid split fraction.")
                updates["split_fraction"] = round(float(value), 4)
            if self.server.settings and updates:
                self.server.settings.update(**updates)
            preferences = self.server.preferences()
            return {"split_orientation": preferences.get("split_orientation", "split"),
                    "split_fraction": preferences.get("split_fraction", 0.42)}
        if path == "/api/stop":
            shape(data, [])
            # A deliberate Stop interrupts owned AI work. Files already changed
            # remain; the retained turn records show what was attempted.
            finishing = self.server.conversation.in_flight()
            if not self.server.stopping:
                self.server.stopping = True
                self.server.begin_shutdown()
            note = (f"Stopping {len(finishing)} active AI turn{'s' if len(finishing) != 1 else ''}. "
                    "Files already changed remain; check the recorded turn before retrying."
                    if finishing else "")
            return {"stopped": True, "interrupted": len(finishing), "note": note}
        if self.server.store is None:
            raise ProjectError("This is the installation interface; no project work has started. Open the installed launcher to work with your projects.")
        if path == "/api/projects":
            shape(data, [])
            return {"home": str(self.server.store.home), "projects": self.server.store.list(include_archived=True),
                    "notices": self.server.store.scan_notices, "roles": ROLES}
        if path == "/api/rescan":
            shape(data, [])
            return {"home": str(self.server.store.home), "projects": self.server.store.rescan(),
                    "notices": self.server.store.scan_notices, "roles": ROLES}
        if path == "/api/open":
            shape(data, ["path"])
            strings(data, ["path"])
            key = self.server.store.open(data["path"])
            self.server.remember_project(self.server.store.projects[key].root)
            return {"id": key}
        if path == "/api/create":
            shape(data, ["directory", "name", "description", "goals"], ["parent", "under", "code"])
            strings(data, data)
            key = self.server.store.create(directory=data["directory"], name=data["name"], description=data["description"],
                                           goals=data["goals"], parent=data.get("parent", ""),
                                           under=data.get("under") or None, code=data.get("code", ""))
            self.server.remember_project(self.server.store.projects[key].root)
            return {"id": key}
        allowed = {"/api/project", "/api/save", "/api/read", "/api/read-file", "/api/approve-reference", "/api/prepare", "/api/preview", "/api/handoff", "/api/copy", "/api/continue",
                   "/api/converse", "/api/turn-state", "/api/conversation", "/api/review"}
        if path not in allowed:
            raise ProjectError("No such operation; arbitrary file access is not supported.")
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise ProjectError("Select a project first.")
        project = self.server.store.projects[data["id"]]
        if path == "/api/project":
            shape(data, ["id"])
            return project.snapshot()
        if path == "/api/save":
            shape(data, ["id", "expected", "name", "description", "goals", "paths"], ["parent", "state"])
            strings(data, ["name", "description", "goals"])
            if "parent" in data and not isinstance(data["parent"], str):
                raise ProjectError("Invalid parent field.")
            if "state" in data and not isinstance(data["state"], str):
                raise ProjectError("Invalid project state.")
            if data["expected"] is not None and not isinstance(data["expected"], str):
                raise ProjectError("Invalid loaded overview.")
            if not isinstance(data["paths"], dict) or any(not isinstance(v, str) for v in data["paths"].values()):
                raise ProjectError("Invalid artifact paths.")
            result = project.save_brief(expected=data["expected"], name=data["name"], description=data["description"],
                                        goals=data["goals"], paths=data["paths"], parent=data.get("parent"), state=data.get("state"))
            # One entry updates from the saved definition; no rescan, no switch.
            self.server.store.refresh_entry(project.root)
            return result
        if path == "/api/read":
            shape(data, ["id", "role"])
            strings(data, ["role"])
            return project.material(data["role"])
        if path == "/api/read-file":
            shape(data, ["id", "path"])
            strings(data, ["path"])
            return project.read_reader_document(data["path"])
        if path == "/api/approve-reference":
            shape(data, ["id", "role", "path"])
            strings(data, ["role", "path"])
            project.approve_reference(data["role"], data["path"])
            return {"selected": True}
        if path == "/api/handoff":
            shape(data, ["id"])
            return {"text": project.handoff_text()}
        if path == "/api/copy":
            shape(data, ["id", "displayed"], ["purpose"])
            strings(data, ["displayed"])
            if data.get("purpose") not in (None, "implement-plan"):
                raise ProjectError("Invalid saved request purpose.")
            return {"text": project.copy_snapshot(data["displayed"], data.get("purpose"))}
        if path == "/api/continue":
            shape(data, ["id", "displayed", "destination"], ["purpose", "route"])
            strings(data, ["displayed", "destination"])
            if data.get("purpose") not in (None, "implement-plan"):
                raise ProjectError("Invalid saved request purpose.")
            # A changed repository / code folder must not silently launch a
            # stale saved assignment against the wrong folder.
            current = str(project.code_folder()) if project.code_folder() else None
            if stated_code_location(data["displayed"]) != current:
                raise ProjectError("The repository / code folder changed after this assignment was prepared, so the saved assignment names a different location. Prepare Again; nothing was launched.")
            return continue_in(project, data["displayed"], data["destination"],
                               purpose=data.get("purpose"), route=data.get("route", "terminal"))
        if path == "/api/converse":
            shape(data, ["id", "tool", "stage", "text", "images"], ["files"])
            strings(data, ["tool", "stage", "text"])
            if not isinstance(data["images"], list):
                raise ProjectError("Invalid image attachments.")
            if not isinstance(data.get("files", []), list):
                raise ProjectError("Invalid selected files.")
            if self.server.stopping:
                raise ProjectError("Vibe is closing after Stop; no new turn was started. Your message is retained in this page.")
            # The submission is validated and saved durably before the bounded
            # worker starts; this handler returns as soon as dispatch begins.
            handle = conversation.start_turn(self.server.conversation, project, data["tool"], data["stage"],
                                             data["text"], data["images"], data.get("files", []))
            # The acknowledgement identifies the originating turn and the
            # retained attachment names, so the browser keys the restorable
            # draft to this project and can redeliver originals same-origin.
            return {"turn": handle.turn, "operation": handle.snapshot(),
                    "images": list(handle.retained_images)}
        if path == "/api/turn-state":
            shape(data, ["id"])
            return self.server.conversation.report(project)
        if path == "/api/conversation":
            shape(data, ["id"])
            return {"turns": conversation.read_conversation(project),
                    "runs": conversation.read_reliability_runs(project)}
        if path == "/api/review":
            shape(data, ["id", "tool", "reviewer", "stage", "iterate"])
            strings(data, ["tool", "reviewer", "stage"])
            if not isinstance(data["iterate"], bool):
                raise ProjectError("Expected the iterate selection.")
            if self.server.stopping:
                raise ProjectError("Vibe is closing after Stop; no new review run was started.")
            # The author's note is recorded durably before the bounded pipeline
            # starts; this handler returns as soon as dispatch begins.
            handle = conversation.start_assessment(self.server.conversation, project, data["tool"],
                                                   data["stage"], data["reviewer"], data["iterate"])
            return {"turn": handle.turn, "operation": handle.snapshot()}
        fields = ["id", "stage", "input", "destination", "context"]
        shape(data, fields, ["expected"])
        strings(data, ["stage", "input", "destination"])
        if data["stage"] not in STAGES:
            raise ProjectError("Select one of the supported stages.")
        if len(data["input"].encode("utf-8")) > 64 * 1024:
            raise ProjectError("Stage input exceeds 64 KiB. Your input is retained; nothing was saved.")
        if data.get("expected") is not None and not isinstance(data["expected"], str):
            raise ProjectError("Invalid loaded request.")
        shape(data["context"], ["material"])
        material = data["context"]["material"]
        if (not isinstance(material, list) or len(material) > 50
                or any(not isinstance(item, str) or not item for item in material)):
            raise ProjectError("Invalid selected material.")
        payload = prepare_request(project, data["stage"], data["input"], data["destination"], material)
        if path == "/api/prepare":
            project.save_packet(payload, data["stage"], expected=data.get("expected"))
            return {"text": payload, "path": str(project.packet_path(data["stage"]))}
        return {"text": payload}
