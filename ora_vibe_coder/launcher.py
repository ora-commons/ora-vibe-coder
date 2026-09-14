"""Shared foreground launcher and ordinary local application preferences."""

import json
import os
from pathlib import Path
import sys
import threading
import webbrowser

from .project import atomic_write


def settings_path(home=None, platform=None):
    home, platform = Path(home or Path.home()), platform or sys.platform
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Ora Vibe Coder" / "settings.json"
    if platform == "win32":
        return home / "AppData" / "Local" / "Ora Vibe Coder" / "settings.json"
    return home / ".config" / "ora-vibe-coder" / "settings.json"


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


def serve(server, *, no_browser=False, opener=None):
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
                    print("The browser did not open. Open the local URL printed above.", flush=True)
            except (webbrowser.Error, OSError):
                print("The browser could not be opened. Open the local URL printed above.", flush=True)
        while thread.is_alive():
            thread.join(.2)
    except KeyboardInterrupt:
        server.shutdown()
    finally:
        if thread.is_alive():
            server.shutdown()
        thread.join()
        server.server_close()
    print("Ora Vibe Coder stopped. Project files were left in place.", flush=True)
