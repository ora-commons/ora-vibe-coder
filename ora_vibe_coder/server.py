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
from . import run as run_module
from .handoff import PLUGIN, STAGES, prepare_request, stated_code_location
from .hosts import HOSTS as TOOL_LABELS, continue_in, discover
from .launcher import Settings, documents_location
from .project import Conflict, ProjectError, ProjectStore, ROLES, atomic_write, not_started, read_text
from .status import assessment_facts, metadata, review_basis, sections

# A 4 MiB packet can expand sixfold when JSON escapes control characters.
# This bounded transport ceiling accommodates a full saved packet plus input.
REQUEST_LIMIT = 32 * 1024 * 1024
STATIC = Path(__file__).parent / "static"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
          "/static/style.css": ("style.css", "text/css; charset=utf-8"),
          "/static/vendor/markdown-it.min.js": ("vendor/markdown-it.min.js", "application/javascript; charset=utf-8"),
          "/static/vendor/Quicksand.ttf": ("vendor/Quicksand.ttf", "font/ttf")}
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


def validated_roles(values):
    """Role defaults: each role a tool plus optional model and effort strings."""
    if not isinstance(values, dict) or set(values) - set(run_module.ROLE_NAMES):
        raise ProjectError("Role defaults name the six run roles.")
    roles = {}
    for role, choice in values.items():
        if choice is None:
            roles[role] = {}
            continue
        if not isinstance(choice, dict) or set(choice) - {"tool", "model", "effort"}:
            raise ProjectError(f"Invalid defaults for the {run_module.ROLE_NAMES[role]} role.")
        tool = choice.get("tool", "")
        if tool and tool not in conversation.PEERS:
            raise ProjectError(f"Unknown coding tool for the {run_module.ROLE_NAMES[role]} role.")
        for key in ("model", "effort"):
            if not isinstance(choice.get(key, ""), str):
                raise ProjectError(f"Invalid {key} for the {run_module.ROLE_NAMES[role]} role.")
        roles[role] = {"tool": tool, "model": choice.get("model", ""), "effort": choice.get("effort", "")}
    return roles


class LocalServer(HTTPServer):
    def __init__(self, home=None, port=0, settings=None, install_home=None, update_lookup=None,
                 install_applications=None):
        self.settings = settings
        self.install_home = Path(install_home) if install_home else None
        # None keeps the real shared Applications folder; the disposable
        # inspection route supplies a test-only root for setup effects.
        self.install_applications = Path(install_applications) if install_applications else None
        self.store = ProjectStore(home) if home else None
        self.token = secrets.token_urlsafe(32)
        # The one network-capable operation, reached only when the user presses
        # Check for updates. A stand-in lookup can be supplied for tests.
        self.update_lookup = update_lookup or lookup_latest_release
        # Work-turn operation handles: in memory only, bound to their
        # originating project; the .vibe/ records on disk are the truth.
        self.conversation = conversation.TurnRegistry()
        # Live Run to Completion drivers, in memory only; each run's durable
        # record is the ordinary .vibe/ turn folders it writes.
        self.runs = run_module.RunRegistry()
        # One live read-only auxiliary call (unclear-record judgment or
        # findings sorting) per project and purpose, for honest polling.
        self.aux_lock = threading.Lock()
        self.aux_handles = {}
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
        self.readiness_components = None
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
            if peer == "zcode" and not self.stopping:
                # Keep ordinary Edit readiness separate from the explicit
                # Full access contract used only for programming turns.
                facts["programming"] = conversation.bridge_check(
                    peer, stop_requested=lambda: self.stopping, work_permission="full-access")
            facts["label"] = TOOL_LABELS[peer][0]
            results.append(facts)
        # The bundled components' own facts — read once per sweep from the
        # copies actually selected, never persisted — carry the Gear
        # primary/peer availability shown beside each tool's readiness.
        components = conversation.component_facts()
        for facts in results:
            facts["gear"] = conversation.gear_availability(
                facts["peer"], boost=components["boost"], bridge=components["bridge"])
        with self.readiness_lock:
            self.readiness = results
            self.readiness_components = components
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
            components = self.readiness_components
        # Discovery rides along once a sweep has reported, so a Recheck after
        # installation, removal, update or sign-in refreshes both readiness
        # and discovery in one response. Harness facts only: Bridge's own
        # check reports capability and sign-in truth. No model/provider
        # identity is claimed from a harness name.
        hosts_report = None
        if peers is not None:
            hosts_report = discover({facts.get("peer"): facts.get("work") for facts in peers})
        return {"checking": checking, "peers": peers, "components": components, "hosts": hosts_report}

    def run_report(self, project):
        """The live run driver's status, or the last retained run's outcome."""
        driver = self.runs.find(project)
        if driver is not None:
            return {"active": driver.status()}
        records = run_module.read_runs(project)
        return {"active": None, "last": records[-1] if records else None}

    def aux_report(self, project, purpose, stage, tool, body, remember):
        """A remembered auxiliary answer, a live call, or one fresh call.

        The answer is remembered in the retained records by its content key, so
        it is never repeated on refresh; a failed call is reported as a failure
        and may be retried, never remembered as a verdict or a repair list.
        """
        key = f"{stage}:{remember.get('Key', '')}"
        remembered = conversation.read_aux_answers(project).get(key)
        if remembered and remembered["purpose"] == purpose:
            return {"state": "answered", "answer": remembered["answer"], "tool": remembered["tool"]}
        holder = (str(project.root), purpose, stage)
        with self.aux_lock:
            handle = self.aux_handles.get(holder)
        if handle is not None:
            if handle.state in {"starting", "running"}:
                return {"state": "working"}
            if handle.state == "finished":
                with self.aux_lock:
                    self.aux_handles.pop(holder, None)
                remembered = conversation.read_aux_answers(project).get(key)
                if remembered and remembered["purpose"] == purpose:
                    return {"state": "answered", "answer": remembered["answer"], "tool": remembered["tool"]}
            else:
                reason = handle.reason or "The call failed."
                with self.aux_lock:
                    self.aux_handles.pop(holder, None)
                return {"state": "failed", "reason": reason}
        handle = conversation.start_aux(self.conversation, project, tool, purpose, stage, body, remember)
        with self.aux_lock:
            self.aux_handles[holder] = handle
        return {"state": "working"}

    def begin_shutdown(self):
        """Stop work the user chose to interrupt, then close owned processes."""
        if self.shutdown_thread is not None:
            return
        self.stopping = True
        def finish():
            conversation.end_checks()
            self.runs.drain()
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
        # font-src allows only the vendored local font files; the app never
        # fetches fonts from the internet.
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self' 'sha256-F67S4cyeDKHZWHZkYuZA9hhcE79TgOLNss519TC/CRQ='; style-src 'self'; font-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
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

    def host_discovery(self):
        """Discovery with conversation routes from the last completed sweep.

        Before any sweep has reported, the reviewed fixed set of the pinned
        bundle stands; the sweep and every Recheck then true it to the actual
        copy in use.
        """
        with self.server.readiness_lock:
            peers = self.server.readiness
        work = {facts.get("peer"): facts.get("work") for facts in peers} if peers is not None else None
        return discover(work)

    def action(self, data):
        path = self.path
        if path == "/api/setup":
            shape(data, [])
            documents = documents_location()
            preferences = self.server.preferences()
            recent = [item for item in preferences.get("recent_projects", []) if isinstance(item, str)][:8]
            roles = preferences.get("role_defaults") if isinstance(preferences.get("role_defaults"), dict) else {}
            return {"home": str(self.server.store.home) if self.server.store else None,
                    "browse_home": str(documents or Path.home()),
                    "browse_note": "" if documents else "Your Documents folder was not found, so browsing starts at your home folder. No project was created or selected.",
                    "recent_projects": recent,
                    "last_project": preferences.get("last_project", ""),
                    "last_workspace": preferences.get("last_workspace", ""),
                    "split_orientation": preferences.get("split_orientation", "split"),
                    "split_fraction": preferences.get("split_fraction", 0.42),
                    "app_settings": {"warn_skip_review": preferences.get("warn_skip_review", True),
                                     "spending": preferences.get("spending", ""),
                                     "role_defaults": {role: roles.get(role, {}) for role in run_module.ROLE_NAMES}},
                    "version": (PLUGIN / "VERSION").read_text(encoding="utf-8").strip(),
                    "hosts": self.host_discovery(), "installation": self.server.install_home is not None}
        if path == "/api/install":
            shape(data, ["hosts"])
            from .installer import install, SKILL_HOMES
            if self.server.install_home is None:
                raise ProjectError("Open the supplied installer to install or update Vibe. Stop the installed application before updating.")
            if not isinstance(data["hosts"], list) or not data["hosts"] or any(not isinstance(host, str) or host not in SKILL_HOMES for host in data["hosts"]):
                raise ProjectError("Select the coding tools to configure.")
            return install(home=self.server.install_home, hosts=list(dict.fromkeys(data["hosts"])),
                           applications=self.server.install_applications)
        if path == "/api/remove":
            shape(data, ["hosts"])
            from .installer import remove, SKILL_HOMES
            if self.server.install_home is None:
                raise ProjectError("Open the supplied installer to remove Vibe. Stop the installed application first.")
            if not isinstance(data["hosts"], list) or any(not isinstance(host, str) or host not in SKILL_HOMES for host in data["hosts"]):
                raise ProjectError("Select the coding tools whose Vibe entries should be removed.")
            return remove(home=self.server.install_home, hosts=list(dict.fromkeys(data["hosts"])),
                          applications=self.server.install_applications)
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
        if path == "/api/settings":
            # Settings holds the skip-review warning switch, the role defaults
            # and the spending preference, persisted in the existing
            # settings.json through Settings; nothing else is stored.
            shape(data, [], ["warn_skip_review", "spending", "role_defaults"])
            updates = {}
            if "warn_skip_review" in data:
                if not isinstance(data["warn_skip_review"], bool):
                    raise ProjectError("Expected the warning switch state.")
                updates["warn_skip_review"] = data["warn_skip_review"]
            if "spending" in data:
                if not isinstance(data["spending"], str):
                    raise ProjectError("Expected the spending preference.")
                updates["spending"] = data["spending"]
            if "role_defaults" in data:
                updates["role_defaults"] = validated_roles(data["role_defaults"])
            if self.server.settings is None:
                raise ProjectError("Settings are stored by the installed application; this installer does not save them.")
            if updates:
                self.server.settings.update(**updates)
            preferences = self.server.preferences()
            roles = preferences.get("role_defaults") if isinstance(preferences.get("role_defaults"), dict) else {}
            return {"warn_skip_review": preferences.get("warn_skip_review", True),
                    "spending": preferences.get("spending", ""),
                    "role_defaults": {role: roles.get(role, {}) for role in run_module.ROLE_NAMES}}
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
                   "/api/converse", "/api/turn-state", "/api/conversation", "/api/review",
                   "/api/judgment", "/api/sort-findings", "/api/approve-plan", "/api/repair", "/api/deliver",
                   "/api/run-start", "/api/run-stop", "/api/run-answer", "/api/run-resume", "/api/run-configure", "/api/run-copy"}
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
            if self.server.runs.find(project) is not None:
                raise ProjectError("A Run to Completion is active in this project, so the composer cannot start a separate turn. Answer the run's pause, or stop the run first.")
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
            report = self.server.conversation.report(project)
            report["run"] = self.server.run_report(project)
            return report
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
        if path == "/api/judgment":
            # One remembered read-only judgment when a current record's wording
            # leaves the binary verdict genuinely unclear. The answer is keyed
            # by the content basis status.py computes, so it is not repeated on
            # refresh; a failed call is a reading error, never RECORD UNCLEAR.
            shape(data, ["id", "stage", "tool"])
            strings(data, ["stage", "tool"])
            if data["stage"] not in conversation.REVIEW_STAGES:
                raise ProjectError("Judgments read the Specification and Plan review records.")
            if data["tool"] not in conversation.PEERS:
                raise ProjectError("Select one of the six supported coding tools as the Reviewer.")
            role = conversation.REVIEW_STAGES[data["stage"]]
            item = project.material(role)
            if item["text"] is None:
                return {"state": "error", "reason": item["reason"] or f"The current {role} could not be read."}
            facts = assessment_facts(data["stage"], item["text"])
            if not facts["present"]:
                return {"state": "error", "reason": "No assessment is recorded, so there is nothing to judge."}
            if facts["verdict"] and not facts["issues"]:
                return {"state": "answered", "answer": {"verdict": "PASSED" if facts["verdict"] == "COMPLETE" else "NOT PASSED"},
                        "tool": "the saved record"}
            basis = review_basis(item["text"])
            assessment = conversation.section_body(item["text"], "Current review") or item["text"]
            return self.server.aux_report(project, conversation.PURPOSE_JUDGMENT, data["stage"], data["tool"],
                                          conversation.judgment_request(data["stage"], item["text"], assessment),
                                          {"Key": basis})
        if path == "/api/sort-findings":
            # One remembered read-only sorting of an INCOMPLETE review's or a
            # NOT PASSED report's findings into AI-can-fix and needs-input.
            shape(data, ["id", "stage"])
            strings(data, ["stage"])
            if data["stage"] not in {"specification", "planning", "verification"}:
                raise ProjectError("Findings are sorted for a Specification or Plan review, or a NOT PASSED Verification Report.")
            if data["stage"] == "verification":
                report = project.material("Verification Report")
                if report["text"] is None:
                    return {"state": "error", "reason": report["reason"] or "No Verification Report is resolved to sort."}
                if run_module.verification_verdict(report["text"]) != "NOT PASSED":
                    return {"state": "error", "reason": "Sorting runs for a NOT PASSED Verification Report."}
                basis, findings = review_basis(report["text"]), report["text"]
                tool = next((turn["tool"] for turn in reversed(conversation.read_conversation(project))
                             if turn["stage"] == "verification" and turn["state"] == "complete"), "")
            else:
                role = conversation.REVIEW_STAGES[data["stage"]]
                item = project.material(role)
                if item["text"] is None:
                    return {"state": "error", "reason": item["reason"] or f"No {role} document is resolved to sort."}
                facts = assessment_facts(data["stage"], item["text"])
                if facts["verdict"] != "INCOMPLETE" or facts["issues"]:
                    return {"state": "error", "reason": "Sorting runs for a current INCOMPLETE review."}
                basis = review_basis(item["text"])
                findings = conversation.section_body(item["text"], "Current review") or item["text"]
                tool = next((run_record["tool"] for run_record in reversed(conversation.read_reliability_runs(project))
                             if run_record["stage"] == conversation.REVIEW_KEYS[data["stage"]]), "")
            if not tool:
                return {"state": "error",
                        "reason": "The tool that ran this assessment is not recorded in this project, so the sorting call has nowhere to go."}
            return self.server.aux_report(project, conversation.PURPOSE_SORTING, data["stage"], tool,
                                          conversation.sorting_request(data["stage"],
                                                                       report["text"] if data["stage"] == "verification" else item["text"],
                                                                       findings),
                                          {"Key": basis})
        if path == "/api/approve-plan":
            # Approve the Plan: the app records the approval itself, server-side,
            # reusing the document-saving protections. No AI call, no register.
            shape(data, ["id"])
            reference = project.reference("Plan")
            if not isinstance(reference, Path) or not reference.is_file():
                raise ProjectError("No Plan document is resolved to approve.")
            if reference.is_symlink() or not reference.resolve().is_relative_to(project.root.resolve()):
                raise ProjectError("The resolved Plan is a link or outside the project folder, so it was not changed.")
            try:
                current = read_text(reference)
            except (OSError, ProjectError) as error:
                raise ProjectError(f"The Plan could not be read: {error}") from error
            facts = assessment_facts("planning", current)
            if facts["verdict"] != "COMPLETE" or facts["issues"] or facts.get("unreadable"):
                raise ProjectError("Approve the Plan is available once the current Plan review verdict is COMPLETE.")
            lines = current.split("\n")
            body_at = 0
            if lines and lines[0].rstrip() == "---":
                close = next((i for i in range(1, len(lines)) if lines[i].rstrip() in {"---", "..."}), None)
                body_at = (close + 1) if close is not None else 0
            # The opening metadata region runs until the first heading, fence,
            # indented block, or ordinary prose line, mirroring status.metadata.
            opening_end = body_at
            seen_title = False
            for index in range(body_at, len(lines)):
                line = lines[index]
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(("```", "~~~")) or re.match(r"(?: {4}| {0,3}\t)", line):
                    break
                if stripped.startswith("# ") and not seen_title:
                    seen_title = True
                    continue
                if not re.fullmatch(r"[*`_]*[A-Za-z][A-Za-z0-9_ -]*?[*`_]*\s*:\s*.*", stripped):
                    break
                opening_end = index + 1
            status_line = next((index for index in range(body_at, opening_end)
                                if re.fullmatch(r"[*`_]*Status[*`_]*\s*:\s*.*", lines[index].strip())), None)
            replacement = current
            if status_line is None:
                insertion = body_at
                while insertion < len(lines) and (not lines[insertion].strip() or lines[insertion].startswith("# ")):
                    insertion += 1
                replacement = "\n".join([*lines[:insertion], "Status: APPROVED", *lines[insertion:]]) + ("\n" if current.endswith("\n") else "")
            else:
                key = lines[status_line].split(":", 1)[0]
                lines[status_line] = f"{key}: APPROVED"
                replacement = "\n".join(lines) + ("\n" if current.endswith("\n") else "")
            if read_text(reference) != current:
                raise ProjectError("The Plan changed before the approval was saved; no assessment or approval was written.")
            atomic_write(reference, replacement)
            saved = read_text(reference)
            if saved != replacement or not re.search(r"[*`_]*Status[*`_]*\s*:\s*[*`_]*APPROVED", saved):
                raise ProjectError("The approval write could not be confirmed by reading the Plan back; the prior file was kept.")
            self.server.store.refresh_entry(project.root)
            return {"approved": True, "plan": str(reference)}
        if path == "/api/repair":
            # Request repairs: the remembered AI-can-fix findings go to the
            # step-3 tool as one ordinary work turn on the same stage.
            shape(data, ["id", "stage", "tool"])
            strings(data, ["stage", "tool"])
            if data["stage"] not in conversation.REVIEW_STAGES:
                raise ProjectError("Repairs run in the Specification and Plan workspaces.")
            if data["tool"] not in conversation.PEERS:
                raise ProjectError("Select one of the six supported coding tools.")
            if self.server.stopping:
                raise ProjectError("Vibe is closing after Stop; no new turn was started.")
            if self.server.runs.find(project) is not None:
                raise ProjectError("A Run to Completion is active in this project, so the composer cannot start a separate turn.")
            role = conversation.REVIEW_STAGES[data["stage"]]
            item = project.material(role)
            if item["text"] is None:
                raise ProjectError(f"No {role} document is resolved to repair.")
            remembered = conversation.read_aux_answers(project).get(
                f"{data['stage']}:{review_basis(item['text'])}")
            findings = ((remembered or {}).get("answer") or {}).get("ai") or []
            if not findings:
                raise ProjectError("No remembered AI-can-fix findings for the current review. Run the sorting first.")
            instruction = ("Repair the review findings the AI can fix, listed below, in the current "
                           f"{role}. Fix them now in this turn, revise the document in place, and keep "
                           "everything else unchanged. Findings that need the user's input are shown "
                           "separately and are not yours to decide.\n\n" +
                           "\n".join(f"- {finding}" for finding in findings))
            handle = conversation.start_turn(self.server.conversation, project, data["tool"], data["stage"],
                                             instruction, [], [])
            return {"turn": handle.turn, "operation": handle.snapshot(), "images": []}
        if path == "/api/deliver":
            # One-click stage handoff: Send prepares and saves the complete
            # request through the existing builders, then starts the next
            # stage's in-app turn; Copy prepares, saves and returns the text;
            # Terminal opens the saved request in the tool's own window.
            shape(data, ["id", "step", "action", "tool", "text"], ["files", "images", "verifier"])
            strings(data, ["step", "action", "tool", "text"])
            if data["step"] not in {"create-plan", "implement-plan", "result", "verification", "correction"}:
                raise ProjectError("Unknown handoff step.")
            if data["action"] not in {"send", "copy", "terminal"}:
                raise ProjectError("Unknown delivery action.")
            if data["action"] == "send" and data["tool"] not in run_module.CONVERSATION_PEERS:
                raise ProjectError(f"{TOOL_LABELS.get(data['tool'], (data['tool'],))[0]} cannot exchange turns in-app; use Open in Terminal or Copy request.")
            if data["action"] == "send":
                # Revalidated against the actual current components before any
                # packet is saved, so a stale screen or direct submission can-
                # not start an unsupported route; Build-family steps also need
                # the applicable bundled Loop adapter.
                if data["step"] in {"implement-plan", "correction"}:
                    conversation.require_build_route(data["tool"], f"the {data['step']} step")
                else:
                    conversation.require_work_route(data["tool"], "this in-app step")
            if len(data["text"].encode("utf-8")) > 64 * 1024:
                raise ProjectError("Stage input exceeds 64 KiB. Your input is retained; nothing was saved.")
            files = data.get("files", [])
            if not isinstance(files, list) or len(files) > 10 or any(not isinstance(path, str) or not path for path in files):
                raise ProjectError("Choose at most 10 Markdown or text files for this message.")
            images = data.get("images", [])
            if not isinstance(images, list):
                raise ProjectError("Invalid image attachments.")
            purpose = "implement-plan" if data["step"] == "implement-plan" else None
            destination = TOOL_LABELS[data["tool"]][0] if data["tool"] in TOOL_LABELS else data["tool"] or "External AI chat"
            extra = []
            if data["step"] == "correction":
                report = project.material("Verification Report")
                if report["text"] is not None:
                    remembered = conversation.read_aux_answers(project).get(f"verification:{review_basis(report['text'])}")
                    findings = ((remembered or {}).get("answer") or {}).get("ai") or []
                    if findings:
                        extra.append("The findings the AI can fix, from the sorted review:\n\n"
                                     + "\n".join(f"- {finding}" for finding in findings))
            # A request delivered by copy or terminal cannot carry pictures, so
            # the saved packet itself names each omitted one with its access
            # limitation — the recipient sees what is missing, not only this
            # app's status bar. A send carries them as the turn's attachments.
            picture_names = [item.get("name", "") for item in images]
            if data["action"] != "send" and picture_names:
                extra.append(f"Pictures not carried by this request: {', '.join(picture_names)}. "
                             "This request cannot include images; supply them through a route that can, "
                             "if the work needs them.")
            packet = run_module.step_request(project, data["step"], data["text"], destination, files,
                                             data.get("verifier", ""), extra)
            # A new one-click delivery deliberately replaces the prior saved
            # request of the same kind; a change between reading and writing
            # still preserves the prior file and reports the conflict.
            project.save_packet(packet, purpose, expected=project.handoff_text(purpose))
            if data["action"] == "copy":
                return {"text": packet, "path": str(project.packet_path(purpose)),
                        "pictures": [item.get("name", "") for item in images]}
            if data["action"] == "terminal":
                return continue_in(project, packet, destination, purpose=purpose, route="terminal")
            handle = conversation.start_turn(self.server.conversation, project, data["tool"],
                                             run_module.STEP_STAGE[data["step"]],
                                             run_module.build_input(data["step"], project, data["text"],
                                                                    data.get("verifier", ""), extra),
                                             images, files)
            return {"turn": handle.turn, "operation": handle.snapshot(),
                    "images": list(handle.retained_images)}
        if path == "/api/run-start":
            shape(data, ["id", "entry", "text", "images", "files"], ["config", "tool"])
            strings(data, ["entry", "text"])
            # The whitelist names exactly the ROUTE entries: every layer uses
            # "planning" as the canonical Plan-workspace entry, and an entry
            # outside ROUTE would silently fall back to the build step.
            if data["entry"] not in {"specification", "planning", "build"}:
                raise ProjectError("A run starts from the Specification, Plan, or Build & Verify workspace.")
            if not isinstance(data["images"], list) or not isinstance(data.get("files", []), list):
                raise ProjectError("Invalid brief attachments.")
            config = data.get("config") or {}
            if not isinstance(config, dict):
                raise ProjectError("Invalid run configuration.")
            if self.server.stopping:
                raise ProjectError("Vibe is closing after Stop; the run did not start. Your brief is retained in this page.")
            preferences = self.server.preferences()
            defaults = preferences.get("role_defaults") if isinstance(preferences.get("role_defaults"), dict) else {}
            step3_tool = data.get("tool") if isinstance(data.get("tool"), str) else ""
            if not step3_tool or step3_tool not in conversation.PEERS:
                raise ProjectError("Choose the step-3 coding tool for the active stage before starting a run.")
            run_config = {"roles": config.get("roles", {}) if isinstance(config.get("roles"), dict) else {},
                          "best_guess": bool(config.get("best_guess")),
                          "hide_advisory": bool(config.get("hide_advisory"))}
            # Refuse for content reasons only when there is literally nothing
            # to build: no brief, no filled-in documents, no conversation.
            brief = data["text"].strip()

            def filled(role):
                item = project.material(role)
                return item["text"] is not None and (role not in {"Specification", "Plan"} or not not_started(item["text"]))

            documents = any(filled(role) for role in ("Specification", "Plan", "Programming Result", "Verification Report"))
            conversation_exists = bool(conversation.read_conversation(project))
            if not brief and not data["images"] and not data.get("files", []) and not documents and not conversation_exists:
                raise ProjectError("There is literally nothing to build: no brief, no filled-in documents, and no conversation. Write what you want first.")
            driver = self.server.runs.start(self.server.conversation, project, data["entry"], data["text"],
                                            run_config, defaults, step3_tool,
                                            data["images"], data.get("files", []))
            return {"run": driver.status()}
        if path == "/api/run-stop":
            shape(data, ["id"])
            driver = self.server.runs.stop(project)
            driver.done.wait(20)
            return {"run": self.server.run_report(project)}
        if path == "/api/run-answer":
            shape(data, ["id", "text"])
            strings(data, ["text"])
            driver = self.server.runs.find(project)
            if driver is None:
                raise ProjectError("No run is active in this project.")
            if driver.status()["state"] != "paused-question":
                raise ProjectError("The run is not paused for a question.")
            driver.receive_answer(data["text"])
            return {"run": driver.status()}
        if path == "/api/run-resume":
            shape(data, ["id"])
            driver = self.server.runs.find(project)
            if driver is None:
                raise ProjectError("No run is active in this project.")
            if not driver.resume():
                raise ProjectError("The run is not paused for an operational failure.")
            return {"run": driver.status()}
        if path == "/api/run-configure":
            shape(data, ["id", "config"])
            config = data["config"]
            if not isinstance(config, dict):
                raise ProjectError("Invalid run configuration.")
            driver = self.server.runs.find(project)
            if driver is None:
                raise ProjectError("No run is active in this project to configure.")
            roles = config.get("roles", {}) if isinstance(config.get("roles"), dict) else {}
            driver.configure({"roles": roles, "best_guess": bool(config.get("best_guess")),
                              "hide_advisory": bool(config.get("hide_advisory"))})
            return {"run": driver.status()}
        if path == "/api/run-copy":
            # The Copy request fallback for a paused step: prepare and save the
            # step's complete request for manual delivery elsewhere.
            shape(data, ["id"])
            driver = self.server.runs.find(project)
            if driver is None:
                raise ProjectError("No run is active in this project.")
            if not driver.status()["state"].startswith("paused"):
                raise ProjectError("The run is not paused; its step is running.")
            tool, _model, _effort, _origin = driver.assignment()
            destination = TOOL_LABELS.get(tool, (tool,))[0]
            # A paused entry step whose turn never dispatched still owes its
            # AI the brief, so the manual packet carries it; a dispatched
            # step's packet keeps only the step instruction.
            # The packet cannot carry the brief's pictures, so — like every
            # copy — it names each one as not included instead of silently
            # dropping it, and the response carries the names for the banner.
            pictures = driver.pending_pictures()
            extra = ([f"Brief pictures not included: {', '.join(pictures)}. A copy cannot carry pictures; "
                      "supply them through a route that can, if the work needs them."] if pictures else [])
            packet = run_module.step_request(project, driver.step, driver.pending_brief(), destination, extra=extra)
            purpose = "implement-plan" if driver.step == "build" else None
            project.save_packet(packet, purpose, expected=project.handoff_text(purpose))
            return {"text": packet, "path": str(project.packet_path("implement-plan" if driver.step == "build" else None)),
                    "pictures": pictures}
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
