"""Launch the app, using an explicit projects folder when configured."""

import argparse
import os
from pathlib import Path
import sys
from .launcher import AppLock, Settings, documents_location, native_alert, open_existing, request_quit, serve
from .project import atomic_write
from .server import LocalServer

# The wrapper's watched child exits with this code when it only reopened an
# already running instance, so the Dock icon stays without a second server.
REOPENED_EXISTING = 42


def include_mac_tool_directories():
    """Give an icon-launched app the usual user CLI locations Finder omits."""
    home = Path.home()
    current = os.environ.get("PATH", "")
    path = current.split(os.pathsep) if current else []
    for directory in (home / ".local/bin", home / ".minimax-code/bin", home / "bin",
                      Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
        if directory.is_dir() and str(directory) not in path:
            path.append(str(directory))
    os.environ["PATH"] = os.pathsep.join(path)


def main():
    parser = argparse.ArgumentParser(description="Ora Vibe Coder — your local software project workspace")
    parser.add_argument("--projects-dir", help="An explicitly chosen discovery root for disposable runs; normal startup searches the user's Documents folder")
    parser.add_argument("--settings", help="Application settings path (for a disposable installation)")
    parser.add_argument("--install", action="store_true", help="Open the shared installation interface")
    parser.add_argument("--install-home", help="Disposable user home for installation inspection")
    parser.add_argument("--no-browser", action="store_true", help="Print the local launch URL without opening a browser")
    parser.add_argument("--wrapper", action="store_true", help="Launched by the desktop wrapper: report failures natively, without a console")
    parser.add_argument("--reopen", action="store_true", help="Reopen the running instance's browser tab, or start one when none runs")
    parser.add_argument("--quit", action="store_true", help="Native Quit path: warn about visible input, then stop the running server")
    args = parser.parse_args()
    if args.wrapper and sys.platform == "darwin":
        include_mac_tool_directories()
    settings = Settings(args.settings)
    if args.quit:
        raise SystemExit(0 if request_quit(settings) else 130)
    if args.install:
        serve(LocalServer(install_home=args.install_home or Path.home()), no_browser=args.no_browser, wrapped=args.wrapper)
        return
    # A deliberate projects boundary takes precedence over broad Documents
    # discovery. The CLI option remains available for disposable test runs.
    home = args.projects_dir
    if home is None:
        try:
            home = settings.projects_dir()
        except ValueError as error:
            message = f"Ora Vibe Coder could not start: {error} Your projects have not changed."
            print(message, flush=True)
            if args.wrapper:
                native_alert(message)
            return
    if home is None:
        documents = documents_location()
        if documents is None or not os.access(documents, os.R_OK):
            message = ("Ora Vibe Coder could not start because your Documents folder is not available; "
                       "open it again once Documents exists and can be read, and know that no files were changed.")
            print(message, flush=True)
            if args.wrapper:
                native_alert(message)
            return
        home = documents
    lock = AppLock(settings.path.with_name("app.lock"))
    try:
        lock.__enter__()
    except ValueError as error:
        if args.reopen or args.wrapper:
            # Another instance owns the server: show its workspace again.
            open_existing(settings)
            raise SystemExit(REOPENED_EXISTING)
        if args.no_browser or not open_existing(settings):
            print(str(error), flush=True)
        return
    running = settings.path.with_name("running.json")
    if running.is_symlink():
        message = "The local launch record is a symbolic link. Nothing was changed."
        print(message, flush=True)
        if args.wrapper:
            native_alert(message)
        lock.__exit__()
        return
    try:
        server = LocalServer(home, settings=settings)
        import json
        atomic_write(running, json.dumps({"url": server.url}))
        running.chmod(0o600)
        serve(server, no_browser=args.no_browser, wrapped=args.wrapper)
    except OSError as error:
        message = f"Ora Vibe Coder could not start: {error}"
        print(message, flush=True)
        if args.wrapper:
            native_alert(message)
    finally:
        running.unlink(missing_ok=True)
        lock.__exit__()


if __name__ == "__main__":
    main()
