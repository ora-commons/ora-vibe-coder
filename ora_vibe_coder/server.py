"""Loopback-only foreground HTTP utility; no generic file-serving route."""

import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import threading

from .handoff import prepare_request
from .hosts import continue_in, discover
from .launcher import Settings
from .project import Conflict, ProjectError, ProjectStore, ROLES

# A 4 MiB packet can expand sixfold when JSON escapes control characters.
# This bounded transport ceiling accommodates a full saved packet plus input.
REQUEST_LIMIT = 32 * 1024 * 1024
STATIC = Path(__file__).parent / "static"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
          "/static/style.css": ("style.css", "text/css; charset=utf-8"),
          "/static/vendor/markdown-it.min.js": ("vendor/markdown-it.min.js", "application/javascript; charset=utf-8")}


def shape(data, required, optional=()):
    if not isinstance(data, dict) or set(data) - set(required) - set(optional) or set(required) - set(data):
        raise ProjectError("Malformed request fields.")


def strings(data, keys):
    if any(not isinstance(data[key], str) for key in keys):
        raise ProjectError("Expected text fields.")


class LocalServer(HTTPServer):
    def __init__(self, home=None, port=0, settings=None, install_home=None):
        self.settings = settings
        self.install_home = Path(install_home) if install_home else None
        self.store = ProjectStore(home) if home else None
        self.token = secrets.token_urlsafe(32)
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
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'none'; frame-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
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
            if self.path not in ASSETS:
                self.reply(404, {"error": "No such page."})
                return
            name, kind = ASSETS[self.path]
            self.reply(200, (STATIC / name).read_bytes(), kind)
        except PermissionError as error:
            self.reply(403, {"error": str(error)})
        except OSError:
            self.reply(500, {"error": "A packaged interface file is missing."})

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
            return {"home": str(self.server.store.home) if self.server.store else None,
                    "browse_home": str(Path.home()), "hosts": discover(), "installation": self.server.install_home is not None}
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
            shape(data, ["path"])
            strings(data, ["path"])
            folder = Path(data["path"]).expanduser().resolve(strict=True)
            if not folder.is_dir():
                raise ProjectError("Select an existing folder.")
            children = sorted((p for p in folder.iterdir() if p.is_dir() and not p.name.startswith('.')), key=lambda p: p.name.casefold())
            return {"path": str(folder), "parent": str(folder.parent),
                    "folders": [{"name": p.name, "path": str(p)} for p in children[:500]], "limited": len(children) > 500}
        if path == "/api/select-home":
            shape(data, ["path"])
            strings(data, ["path"])
            store = ProjectStore(data["path"])
            if self.server.settings:
                self.server.settings.update(projects_home=str(store.home))
            self.server.store = store
            return {"home": str(store.home)}
        if path == "/api/stop":
            shape(data, [])
            # HTTPServer.shutdown must run outside the serving thread; this bounded
            # thread completes as soon as this request returns, and starts no worker.
            threading.Thread(target=self.server.shutdown, daemon=False).start()
            return {"stopped": True}
        if self.server.store is None:
            raise ProjectError("Choose your projects folder first. No project work has started.")
        if path == "/api/projects":
            shape(data, [])
            return {"home": str(self.server.store.home), "projects": self.server.store.list(), "roles": ROLES}
        if path == "/api/open":
            shape(data, ["path"])
            strings(data, ["path"])
            return {"id": self.server.store.open(data["path"])}
        if path == "/api/create":
            shape(data, ["directory", "name", "description", "goals"])
            strings(data, data)
            return {"id": self.server.store.create(**data)}
        allowed = {"/api/project", "/api/save", "/api/read", "/api/documents", "/api/approve-reference", "/api/prepare", "/api/handoff", "/api/copy", "/api/continue"}
        if path not in allowed:
            raise ProjectError("No such operation; arbitrary file access is not supported.")
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise ProjectError("Select a project first.")
        project = self.server.store.projects[data["id"]]
        if path == "/api/project":
            shape(data, ["id"])
            return project.snapshot()
        if path == "/api/documents":
            shape(data, ["id", "directory"])
            strings(data, ["directory"])
            folder = (project.root / data["directory"]).resolve(strict=True)
            if not folder.is_relative_to(project.root) or not folder.is_dir():
                raise ProjectError("Choose a folder inside this project. Outside references can be associated explicitly in Edit Project.")
            entries = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
            return {"directory": str(folder.relative_to(project.root)), "entries": [
                {"name": p.name, "path": str(p.relative_to(project.root)), "directory": p.is_dir()}
                for p in entries if not p.name.startswith('.') and p.resolve().is_relative_to(project.root)
                and (p.is_dir() or (p.suffix.lower() in {".md", ".markdown", ".txt"} and p.name not in {"Project.md", "Handoff.md"}))][:500]}
        if path == "/api/save":
            shape(data, ["id", "expected", "name", "description", "goals", "paths"])
            strings(data, ["name", "description", "goals"])
            if data["expected"] is not None and not isinstance(data["expected"], str):
                raise ProjectError("Invalid loaded overview.")
            if not isinstance(data["paths"], dict) or any(not isinstance(v, str) for v in data["paths"].values()):
                raise ProjectError("Invalid artifact paths.")
            return project.save_brief(**{key: value for key, value in data.items() if key != "id"})
        if path == "/api/read":
            shape(data, ["id", "role"])
            strings(data, ["role"])
            return project.material(data["role"])
        if path == "/api/approve-reference":
            shape(data, ["id", "role", "path"])
            strings(data, ["role", "path"])
            project.approve_reference(data["role"], data["path"])
            return {"selected": True}
        if path == "/api/handoff":
            shape(data, ["id"])
            return {"text": project.handoff_text()}
        if path == "/api/copy":
            shape(data, ["id", "displayed"])
            strings(data, ["displayed"])
            return {"text": project.copy_snapshot(data["displayed"])}
        if path == "/api/continue":
            shape(data, ["id", "displayed", "destination"])
            strings(data, ["displayed", "destination"])
            return continue_in(project, data["displayed"], data["destination"])
        shape(data, ["id", "stage", "input", "destination", "context", "expected", "selected_existing"])
        strings(data, ["stage", "input", "destination"])
        if len(data["input"].encode("utf-8")) > 64 * 1024:
            raise ProjectError("Stage input exceeds 64 KiB. Your input is retained; nothing was saved.")
        if not isinstance(data["selected_existing"], bool) or (data["expected"] is not None and not isinstance(data["expected"], str)):
            raise ProjectError("Invalid outgoing destination selection.")
        shape(data["context"], ["authority", "protected", "references", "sensitive"])
        strings(data["context"], ["authority", "protected", "references"])
        sensitive = data["context"]["sensitive"]
        if not isinstance(sensitive, list) or any(not isinstance(role, str) or role not in ROLES for role in sensitive):
            raise ProjectError("Invalid reference-only selections.")
        payload = prepare_request(project, data["stage"], data["input"], data["destination"], data["context"])
        return {"text": project.save_packet(payload, data["expected"], data["selected_existing"])}
