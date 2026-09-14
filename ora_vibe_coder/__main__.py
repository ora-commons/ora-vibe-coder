"""Launch from the source directory: python3 -m ora_vibe_coder --projects-dir PATH."""

import argparse
from .launcher import AppLock, Settings, open_existing, serve
from .project import atomic_write
from .server import LocalServer


def main():
    parser = argparse.ArgumentParser(description="Ora Vibe Coder — your local software project workspace")
    parser.add_argument("--projects-dir", help="An explicitly chosen existing projects home; otherwise choose in the browser")
    parser.add_argument("--settings", help="Application settings path (for a disposable installation)")
    parser.add_argument("--install", action="store_true", help="Open the shared installation interface")
    parser.add_argument("--install-home", help="Disposable user home for installation inspection")
    parser.add_argument("--no-browser", action="store_true", help="Print the local launch URL without opening a browser")
    args = parser.parse_args()
    settings = Settings(args.settings)
    if args.install:
        from pathlib import Path
        serve(LocalServer(install_home=args.install_home or Path.home()), no_browser=args.no_browser)
        return
    home = args.projects_dir or settings.read().get("projects_home")
    if home:
        from pathlib import Path
        if not Path(home).is_dir():
            print("The saved projects folder is unavailable. Choose its current location in the browser.", flush=True)
            home = None
    lock = AppLock(settings.path.with_name("app.lock"))
    try:
        lock.__enter__()
    except ValueError as error:
        if args.no_browser or not open_existing(settings):
            print(str(error), flush=True)
        return
    running = settings.path.with_name("running.json")
    if running.is_symlink():
        print("The local launch record is a symbolic link. Nothing was changed.", flush=True)
        lock.__exit__()
        return
    try:
        server = LocalServer(home, settings=settings)
        import json
        atomic_write(running, json.dumps({"url": server.url}))
        running.chmod(0o600)
        serve(server, no_browser=args.no_browser)
    finally:
        running.unlink(missing_ok=True)
        lock.__exit__()


if __name__ == "__main__":
    main()
