"""Shared foreground launcher and ordinary local application preferences."""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser

from .project import atomic_write

# The desktop wrapper passes this flag so startup and browser failures reach
# the user without a console window. Nothing else changes.
WRAPPER_FLAG = "--wrapper"


def settings_path(home=None, platform=None):
    home, platform = Path(home or Path.home()), platform or sys.platform
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Ora Vibe Coder" / "settings.json"
    if platform == "win32":
        return home / "AppData" / "Local" / "Ora Vibe Coder" / "settings.json"
    return home / ".config" / "ora-vibe-coder" / "settings.json"


def documents_location(home=None):
    """The user's actual Documents folder, or None when it does not exist."""
    candidate = Path(home or Path.home()) / "Documents"
    try:
        if candidate.is_dir():
            return candidate
    except OSError:
        pass
    return None


class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else settings_path()

    def read(self):
        if self.path.is_symlink() or any(parent.is_symlink() for parent in self.path.parents):
            raise ValueError("Application settings path cannot be a symbolic link. Your projects have not changed.")
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Application settings must contain an object. Your projects have not changed.")
        return data

    def projects_dir(self):
        """Optional explicit discovery boundary; older projects_home is ignored."""
        configured = self.read().get("projects_dir")
        if configured is None:
            return None
        if not isinstance(configured, str) or not Path(configured).is_absolute():
            raise ValueError("The configured projects folder must be an absolute path.")
        root = Path(configured)
        if not root.is_dir():
            raise ValueError(f"The configured projects folder is unavailable: {root}")
        return root

    def update(self, **values):
        data = self.read()
        data.update(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


class AppLock:
    """One OS-held lock prevents replacement of a running local application."""
    def __init__(self, path):
        self.path = Path(path)
        self.stream = None

    def __enter__(self):
        if self.path.is_symlink() or any(parent.is_symlink() for parent in self.path.parents):
            raise ValueError("Application lock path cannot be a symbolic link. Nothing was changed.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.stream.write(b" "); self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            self.stream = None
            raise ValueError("Ora Vibe Coder is already running. Use Stop app before updating or removing it.") from error
        return self

    def __exit__(self, *args):
        # Keep the empty lock inode stable so simultaneous launch/update requests
        # cannot obtain different locks. It contains no account or project data.
        if self.stream:
            self.stream.close()


def open_existing(settings, opener=None):
    path = settings.path.with_name("running.json")
    try:
        if path.is_symlink():
            raise ValueError("Invalid local launch record.")
        data = json.loads(path.read_text(encoding="utf-8"))
        from urllib.parse import urlsplit
        url = data["url"]
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
            raise ValueError("Invalid local launch address.")
        print("Ora Vibe Coder is already running: " + url, flush=True)
        return (opener or webbrowser.open)(url)
    except (OSError, ValueError, KeyError, webbrowser.Error):
        return False


def native_alert(message, url=None, platform=None):
    """Console-free error reporting through native facilities or the stdlib."""
    platform = platform or sys.platform
    text = message.replace('"', "'")
    if url:
        text = f'{text}\n\nLocal address: {str(url).replace(chr(34), "")}'
    try:
        if platform == "darwin":
            subprocess.run(["/usr/bin/osascript", "-e",
                            f'display dialog "{text}" with title "Ora Vibe Coder" buttons {{"OK"}} default button "OK"'],
                           check=False, timeout=60, capture_output=True)
            return
        if platform == "win32":
            encoded = text.replace("'", "''")
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(New-Object -ComObject WScript.Shell).Popup('{encoded}', 0, 'Ora Vibe Coder', 48)"],
                           check=False, timeout=60, capture_output=True)
            return
    except (OSError, subprocess.SubprocessError):
        pass
    print(text, flush=True)


def _post(url, token, path):
    # The launch URL carries the token as its fragment (http://127.0.0.1:PORT/#TOKEN);
    # drop it — the token travels in the header — and any trailing slash so the
    # appended API path reaches the server as /api/..., not a fragment or //api/...
    request = urllib.request.Request(url.partition("#")[0].rstrip("/") + path, data=b"{}",
                                     headers={"Content-Type": "application/json", "X-Ora-Token": token}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def confirm_quit_dialog(platform=None):
    """Foreground Cancel / Quit anyway warning for the native Quit path."""
    platform = platform or sys.platform
    message = ("Quitting now interrupts any active AI turn; files already changed remain.\\n\\n"
               "Unsent text remains available only in the open browser tab.").replace('"', "'")
    if platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/osascript", "-e",
             f'display dialog "{message}" with title "Ora Vibe Coder" buttons {{"Cancel", "Quit anyway"}} default button "Cancel"'],
            check=False, timeout=120, capture_output=True, text=True)
        return "Quit anyway" in (result.stdout or "")
    if platform == "win32" and os.name == "nt":
        script = (f"$b = (New-Object -ComObject WScript.Shell).Popup('{message.replace(chr(39), chr(39)*2)}', 0, "
                  "'Quit Ora Vibe Coder?', 33); exit $b")
        result = subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False, timeout=120)
        return result.returncode == 1
    try:
        return input("Quit anyway? [y/N] ").strip().lower() == "y"
    except (EOFError, OSError):
        return True


def request_quit(settings, *, dialog=None, platform=None):
    """Ask the running local server to stop, warning first about visible input.

    Returns True when the app should quit (nothing left running locally, or the
    user chose Quit anyway); False when the user cancelled. Never touches the
    input text itself.
    """
    dialog = dialog or confirm_quit_dialog
    path = settings.path.with_name("running.json")
    try:
        if path.is_symlink():
            raise ValueError("Invalid local launch record.")
        data = json.loads(path.read_text(encoding="utf-8"))
        url = data["url"]
        token = url.partition("#")[2]
        if not token:
            raise ValueError("Invalid local launch record.")
        state = _post(url, token, "/api/quit-state")
        if (state.get("visible_input") or state.get("active_turns")) and not dialog(platform):
            return False
        _post(url, token, "/api/stop")
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        pass  # Nothing is running locally; there is no admitted work to finish.
    return True


def serve(server, *, no_browser=False, opener=None, wrapped=False):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .2}, name="Ora Vibe Coder local interface")
    thread.start()
    print("Ora Vibe Coder is running locally.", flush=True)
    print(server.url, flush=True)
    print("Use Stop in the page or Control-C here. Closing a browser tab does not stop the app.", flush=True)
    try:
        if not no_browser:
            try:
                opened = (opener or webbrowser.open)(server.url)
                if not opened:
                    message = "The browser did not open. Open the local address shown here."
                    if wrapped:
                        native_alert("Vibe is running, but the browser did not open.", url=server.url)
                    print(message, flush=True)
            except (webbrowser.Error, OSError):
                if wrapped:
                    native_alert("Vibe is running, but the browser could not be opened.", url=server.url)
                print("The browser could not be opened. Open the local URL printed above.", flush=True)
        while thread.is_alive():
            thread.join(.2)
    except KeyboardInterrupt:
        server.stopping = True
        server.begin_shutdown()
        thread.join()
    finally:
        if thread.is_alive():
            server.shutdown()
        thread.join()
        server.server_close()
    print("Ora Vibe Coder stopped. Project files were left in place.", flush=True)
