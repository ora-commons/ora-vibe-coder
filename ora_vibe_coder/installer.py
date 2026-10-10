"""Shared per-user source installation and desktop launchers."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile

from . import loop_integrity
from .launcher import AppLock

ROOT = Path(__file__).resolve().parent.parent
SKILL_HOMES = {"codex": ".codex", "claude": ".claude", "zcode": ".zcode", "hermes": ".hermes", "qwen": ".qwen", "minimax": ".minimax"}
IDENTITY = "ora-vibe-install.json"
LOOP_PROFILE = "programming-loop-reviewer.md"
EXECUTABLE_NAME = "Ora Vibe Coder"
BRIDGE_HOME_NAME = "agent-bridge"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install_location(home=None, platform=None):
    home, platform = Path(home or Path.home()), platform or sys.platform
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Ora Vibe Coder" / "app"
    if platform == "win32":
        return home / "AppData" / "Local" / "Ora Vibe Coder" / "app"
    return home / ".local" / "share" / "ora-vibe-coder" / "app"


def identity(folder):
    path = folder / IDENTITY
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{folder} is not an owned Vibe installation. Choose another location; nothing was replaced.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("component") != "ora-vibe-coder":
        raise ValueError(f"{folder} is not an owned Vibe installation. Choose another location; nothing was replaced.")
    if not isinstance(data.get("files"), dict) or any(
            not isinstance(name, str) or Path(name).is_absolute()
            or ".." in Path(name).parts or "\\" in name
            or not isinstance(expected, str)
            or not all(character in "0123456789abcdef" for character in expected)
            or len(expected) != 64
            for name, expected in data["files"].items()):
        raise ValueError("Installed file ownership is invalid; no files were changed.")
    return data


def file_map(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Required release directory is missing or not ordinary: {root}")
    if any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("Release resources must be ordinary files, not symbolic links.")
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def prepare_replacement(destination, files, version):
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError(f"Installation path is a symbolic link: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError(f"Installation target is a symbolic link: {destination}")
    if destination.exists() and any(path.is_symlink() for path in destination.rglob("*")):
        raise ValueError(f"Installation contains a symbolic link: {destination}. The previous installation was preserved.")
    staging = Path(tempfile.mkdtemp(prefix=".ora-vibe-install-", dir=destination.parent))
    try:
        owned = set()
        if destination.exists():
            old = identity(destination)
            owned = set(old["files"])
            edited = []
            for name, expected in old["files"].items():
                path = destination / name
                if not path.is_file() or digest(path.read_bytes()) != expected:
                    edited.append(str(path))
            if edited:
                raise ValueError("Installed product files were changed or are missing. Preserve or repair them before updating: " + ", ".join(edited))
            shutil.copytree(destination, staging, dirs_exist_ok=True, symlinks=True)
            for name in old["files"]:
                path = staging / name
                if path.is_file() or path.is_symlink():
                    path.unlink()
        for name, data in files.items():
            path = staging / name
            if path.exists() and name not in owned:
                raise ValueError(f"Unowned file would be replaced: {destination / name}. Preserve it before updating.")
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(staging)):
                raise ValueError("An installed program path is a symbolic link. The previous installation was preserved.")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        ownership = {name: digest(data) for name, data in sorted(files.items())}
        (staging / IDENTITY).write_text(json.dumps({"component": "ora-vibe-coder", "source": "ora-vibe-coder", "version": version, "files": ownership}, indent=2) + "\n", encoding="utf-8")
        for name, expected in ownership.items():
            path = staging / name
            if path.suffix in {".desktop", ".command"} or path.parent.name == "MacOS":
                path.chmod(0o755)
            if not path.is_file() or digest(path.read_bytes()) != expected:
                raise ValueError(f"Staged product file differs: {name}")
        return staging
    except BaseException:
        shutil.rmtree(staging)
        raise


def apply_replacements(replacements):
    switched = []
    try:
        for destination, staging in replacements:
            backup = None
            if destination.exists():
                backup = Path(tempfile.mkdtemp(prefix=".ora-vibe-previous-", dir=destination.parent))
                backup.rmdir()
                os.replace(destination, backup)
            try:
                os.replace(staging, destination)
            except BaseException:
                if backup:
                    os.replace(backup, destination)
                raise
            switched.append((destination, backup))
    except BaseException:
        for destination, backup in reversed(switched):
            shutil.rmtree(destination)
            if backup:
                os.replace(backup, destination)
        raise
    finally:
        for _, staging in replacements:
            if staging.exists():
                shutil.rmtree(staging)
    for _, backup in switched:
        if backup:
            shutil.rmtree(backup)


def snapshot_targets(targets):
    """Copy only selected product targets for one in-process rollback."""
    backup = Path(tempfile.mkdtemp(prefix="ora-vibe-transaction-"))
    records = []
    try:
        seen = set()
        for target in map(Path, targets):
            key = str(target)
            if key in seen:
                continue
            seen.add(key)
            saved = backup / str(len(records))
            if target.is_symlink():
                raise ValueError(f"Transaction target is a symbolic link: {target}")
            if target.is_dir():
                shutil.copytree(target, saved)
                kind = "directory"
            elif target.is_file():
                shutil.copy2(target, saved)
                kind = "file"
            elif target.exists():
                raise ValueError(f"Transaction target is not an ordinary file or directory: {target}")
            else:
                kind = "missing"
            records.append((target, saved, kind))
        return backup, records
    except BaseException:
        shutil.rmtree(backup)
        raise


def restore_targets(records):
    for target, saved, kind in reversed(records):
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if kind == "directory":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(saved, target)
        elif kind == "file":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, target)


def transaction(targets, action):
    backup, records = snapshot_targets(targets)
    preserve_backup = False
    try:
        return action()
    except BaseException:
        try:
            restore_targets(records)
        except BaseException as error:
            preserve_backup = True
            raise RuntimeError(
                f"Installation transaction stopped; prior files remain copied at {backup}: {error}"
            ) from error
        raise
    finally:
        if backup.exists() and not preserve_backup:
            shutil.rmtree(backup)


def release_version(value):
    """One dotted numeric release identity, or None when unreadable."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def refuse_to_replace_newer(home, platform, destination, hosts, skill_names, plugin, version):
    """Setup never rolls back: a newer installed copy is named, not replaced."""
    installed = release_version(version)
    newer = []
    for label, folder in (
        ("the Vibe application", destination),
        ("the bundled Agent Bridge", bridge_home(destination)),
        ("the Vibe launcher", shortcut_location(home, platform)),
        *((f"the Vibe entries for {host}", home / SKILL_HOMES[host] / "skills" / name)
          for host in hosts for name in skill_names),
    ):
        try:
            data = json.loads((folder / IDENTITY).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        recorded = data.get("version") if isinstance(data, dict) else None
        if release_version(recorded) and installed and release_version(recorded) > installed:
            newer.append(f"{label} at {folder} records version {recorded}")
    bundled_loop = release_version(
        (plugin / "resources/programming-loop/VERSION").read_text(encoding="utf-8"))
    for host in hosts:
        try:
            data = json.loads(
                (home / SKILL_HOMES[host] / "skills/programming-loop/SOURCE.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        recorded = data.get("version") if isinstance(data, dict) else None
        if bundled_loop and release_version(recorded) and release_version(recorded) > bundled_loop:
            newer.append(f"the Programming Loop for {host} records version {recorded}")
    if newer:
        raise ValueError(
            "A newer version is already installed, so setup changed nothing: "
            + "; ".join(newer)
            + ". Removing Ora Vibe Coder first allows installing an older version."
        )


def programming_loop_targets(home, hosts):
    targets = []
    for host in hosts:
        root = home / SKILL_HOMES[host]
        targets.extend((root / "skills/programming-loop", root / "agents" / LOOP_PROFILE))
    return targets


def bridge_home(destination):
    """The one Bridge runtime location: beside the application, never per skill."""
    return Path(destination).parent / BRIDGE_HOME_NAME


def bridge_files(source):
    """The bundled Agent Bridge runtime exactly as pinned, one flat file map."""
    authority = loop_integrity.bridge_authority_metadata()
    try:
        files, _modes, source_tree = loop_integrity.read_bridge_snapshot(
            Path(source) / authority["vendored_snapshot"])
    except loop_integrity.LoopIntegrityError as error:
        raise ValueError(f"{error} The previous installation was preserved.") from error
    if source_tree != authority["source_tree"]:
        raise ValueError(
            "The bundled Agent Bridge does not match its reviewed source tree. "
            "The previous installation was preserved."
        )
    return files


def run_loop_installer(installer, action, host, home):
    result = subprocess.run(
        [sys.executable, str(installer), action, "--host", host, "--home", str(home)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic was returned"
        raise ValueError(f"Programming Loop {action} did not finish for {host}: {detail}")
    return result.stdout.strip()


def applet_source(python, launch, settings, home):
    """Stay-open JXA wrapper: owns the Python child with native argument
    passing, handles reopen, exits on child termination, reports an unusable
    installation through a native dialog before exiting, and routes Dock Quit
    through the input-warning quit check. No shells, no polling."""
    paths = {"python": str(python), "launch": str(launch), "settings": str(settings), "home": str(home)}
    for value in paths.values():
        if "\n" in value or "\r" in value:
            raise ValueError("Launcher paths cannot contain newlines.")
    return (
        "ObjC.import('Foundation')\n"
        "ObjC.import('stdlib')\n"
        "const APP = " + json.dumps(paths, ensure_ascii=False) + "\n"
        "var watched = null\n"
        "var stopping = false\n"
        "ObjC.registerSubclass({\n"
        "  name: 'OraVibeChildWatcher',\n"
        "  superclass: 'NSObject',\n"
        "  methods: {\n"
        "    'childExited:': {\n"
        "      types: ['void', ['id']],\n"
        "      implementation: function (self, cmd, note) {\n"
        "        if (!watched || watched.terminationStatus === 42) { return }\n"
        "        $.exit(0)\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "})\n"
        "function runChild(extra) {\n"
        "  const task = $.NSTask.new\n"
        "  task.launchPath = APP.python\n"
        "  const args = [APP.launch, '--settings', APP.settings]\n"
        "  if (extra) { for (const item of extra) { args.push(item) } }\n"
        "  task.arguments = ObjC.wrap(args)\n"
        "  task.currentDirectoryPath = APP.home\n"
        "  let launched = false\n"
        "  try { launched = task.launchAndReturnError(null) } catch (error) { launched = false }\n"
        "  if (!launched) {\n"
        "    warnUnusableInstall()\n"
        "    $.exit(1)\n"
        "  }\n"
        "  return task\n"
        "}\n"
        "function warnUnusableInstall() {\n"
        "  const current = Application.currentApplication()\n"
        "  current.includeStandardAdditions = true\n"
        "  current.displayDialog('Ora Vibe Coder cannot start: the installed program files are missing or damaged. Application folder: ' + APP.home + ' Interpreter: ' + APP.python + ' Launcher: ' + APP.launch + ' Reinstall Ora Vibe Coder, or repair the installation, then open it again.', {withTitle: 'Ora Vibe Coder', buttons: ['OK'], defaultButton: 'OK'})\n"
        "}\n"
        "function run(argv) {\n"
        "  watched = runChild(['--wrapper'])\n"
        "  $.NSNotificationCenter.defaultCenter.addObserverSelectorNameObject($.OraVibeChildWatcher.new, 'childExited:', $.NSTaskDidTerminateNotification, watched)\n"
        "}\n"
        "function reopen() { if (!stopping) { runChild(['--reopen']) } }\n"
        "function idle() { return 60 }\n"
        "function quit(event) {\n"
        "  stopping = true\n"
        "  const helper = runChild(['--quit'])\n"
        "  for (let i = 0; i < 36000 && helper.isRunning; i++) {\n"
        "    $.NSRunLoop.currentRunLoop.runModeBeforeDate('NSDefaultRunLoopMode', $.NSDate.dateWithTimeIntervalSinceNow(0.1))\n"
        "  }\n"
        "  if (helper.isRunning || helper.terminationStatus !== 0) { return false }\n"
        "  for (let i = 0; i < 300 && watched && watched.isRunning; i++) {\n"
        "    $.NSRunLoop.currentRunLoop.runModeBeforeDate('NSDefaultRunLoopMode', $.NSDate.dateWithTimeIntervalSinceNow(0.1))\n"
        "  }\n"
        "  if (watched && watched.isRunning) { $.exit(1) }\n"
        "  return true\n"
        "}\n"
    )


def mac_icns(source_png):
    """A provisional .icns from the local Ora logo through sips and iconutil."""
    with tempfile.TemporaryDirectory(prefix="ora-vibe-icon-") as directory:
        iconset = Path(directory) / "Ora Vibe Coder.iconset"
        iconset.mkdir()
        sizes = ((16, "icon_16x16.png"), (32, "icon_16x16@2x.png"), (32, "icon_32x32.png"),
                 (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
                 (256, "icon_256x256.png"), (512, "icon_512x512.png"))
        for size, name in sizes:
            subprocess.run(["/usr/bin/sips", "-z", str(size), str(size), str(source_png), "--out", str(iconset / name)],
                           check=True, capture_output=True, timeout=120)
        icns = Path(directory) / "applet.icns"
        subprocess.run(["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
                       check=True, capture_output=True, timeout=120)
        return icns.read_bytes()


def mac_applet_files(app, python, version="0.0.0"):
    if sys.platform != "darwin":
        raise ValueError("The Mac application launcher is generated on macOS.")
    with tempfile.TemporaryDirectory(prefix="ora-vibe-applet-") as directory:
        source = Path(directory) / "applet.js"
        source.write_text(applet_source(python, app / "launch.py", app.parent / "settings.json", app), encoding="utf-8")
        bundle = Path(directory) / f"{EXECUTABLE_NAME}.app"
        subprocess.run(["/usr/bin/osacompile", "-s", "-l", "JavaScript", "-o", str(bundle), str(source)],
                       check=True, capture_output=True, timeout=300)
        executable = bundle / "Contents" / "MacOS" / EXECUTABLE_NAME
        (bundle / "Contents" / "MacOS" / "applet").rename(executable)
        logo = ROOT / "ora_vibe_coder" / "static" / "ora-logo.png"
        (bundle / "Contents" / "Resources" / "applet.icns").write_bytes(mac_icns(logo))
        # Edit the compiler's own plist: the applet runtime depends on its
        # stay-open and usage-description keys, so nothing else is replaced.
        plist_path = bundle / "Contents" / "Info.plist"
        plist = plistlib.loads(plist_path.read_bytes())
        plist.update({
            "CFBundleName": EXECUTABLE_NAME, "CFBundleDisplayName": EXECUTABLE_NAME,
            "CFBundleIdentifier": "org.ora.vibe-coder", "CFBundleExecutable": EXECUTABLE_NAME,
            "CFBundleShortVersionString": version,
        })
        plist_path.write_bytes(plistlib.dumps(plist))
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)],
                       check=False, capture_output=True, timeout=300)
        return {str(path.relative_to(bundle)): path.read_bytes()
                for path in sorted(bundle.rglob("*")) if path.is_file()}


def windows_icon_bytes(png):
    """A provisional .ico container holding the local Ora logo PNG."""
    width = height = 0  # 0 declares a 256-pixel entry; Windows scales the payload.
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(png), 6 + 16)
    return header + entry + png


def shortcut_command(lnk, target, arguments, working, icon):
    def literal(text):
        return "'" + str(text).replace("'", "''") + "'"
    return "\n".join([
        "$shell = New-Object -ComObject WScript.Shell",
        f"$shortcut = $shell.CreateShortcut({literal(lnk)})",
        f"$shortcut.TargetPath = {literal(target)}",
        f"$shortcut.Arguments = {literal(arguments)}",
        f"$shortcut.WorkingDirectory = {literal(working)}",
        f"$shortcut.IconLocation = {literal(str(icon) + ',0')}",
        "$shortcut.Save()",
    ])


def ensure_windows_shortcut(home, app, python, icon):
    """Create the desktop .lnk through built-in PowerShell/WScript.Shell.

    Only runs on an actual Windows installation; paths travel as data inside
    one encoded command, never through a shell string. Windows splits the
    shortcut's Arguments value at whitespace, so each path is double-quoted
    inside that value; default install paths contain spaces.
    """
    if os.name != "nt":
        return None
    pythonw = Path(python).with_name("pythonw.exe")
    target = pythonw if pythonw.is_file() else Path(python)
    lnk = home / "Desktop" / f"{EXECUTABLE_NAME}.lnk"
    launch_entry, settings_entry = app / "launch.py", app.parent / "settings.json"
    command = shortcut_command(lnk, target, f'"{launch_entry}" --settings "{settings_entry}"', app, icon)
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", encoded],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError(f"The desktop shortcut could not be created: {result.stderr.strip() or result.stdout.strip()}")
    return lnk


def launcher_files(app, platform=None, python=None, version="0.0.0"):
    platform, python = platform or sys.platform, python or sys.executable
    if any(character in str(python) + str(app) for character in "\r\n"):
        raise ValueError("Launcher paths cannot contain newlines.")
    if platform == "darwin":
        return mac_applet_files(app, python, version)
    if platform == "win32":
        # This launcher script has fixed product/interpreter paths, never a user prompt.
        safe_python, safe_app = str(python).replace("%", "%%"), str(app / "launch.py").replace("%", "%%")
        if any(c in safe_python + safe_app for c in '\r\n"'):
            raise ValueError("Windows launcher paths cannot contain quotes or newlines.")
        settings = str(app.parent / "settings.json").replace("%", "%%")
        return {"Ora Vibe Coder.cmd": f'@echo off\r\n"{safe_python}" "{safe_app}" --settings "{settings}"\r\n'.encode()}
    quote = lambda s: '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"'
    return {"Ora Vibe Coder.desktop": ("[Desktop Entry]\nType=Application\nName=Ora Vibe Coder\nComment=Your local software project workspace\nTerminal=true\nExec=" + quote(python) + " " + quote(app / "launch.py") + " --settings " + quote(app.parent / "settings.json") + "\nCategories=Development;\n").encode()}


def install(source=ROOT, *, home=None, destination=None, hosts=(), platform=None):
    if sys.version_info < (3, 10):
        raise ValueError(
            "Ora Vibe Coder requires Python 3.10 or later. Get Python 3.10 or later "
            "from the python.org macOS installer at https://www.python.org/downloads/, "
            "then open this setup again.")
    source, home, platform = Path(source).resolve(), Path(home or Path.home()).absolute(), platform or sys.platform
    destination = Path(destination or install_location(home, platform)).absolute()
    if source == destination or source.is_relative_to(destination):
        raise ValueError("Install into a separate application folder, not over the downloaded source.")
    unknown = set(hosts) - set(SKILL_HOMES)
    if unknown:
        raise ValueError("Select a supported coding tool.")
    plugin = source / "plugins" / "ora-vibe-coder"
    version = (plugin / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError("Vibe VERSION must identify a release, such as 1.0.0")
    files = {"launch.py": b"from ora_vibe_coder.__main__ import main\nmain()\n"}
    for directory in ("ora_vibe_coder", "plugins/ora-vibe-coder"):
        files.update({f"{directory}/{name}": data for name, data in file_map(source / directory).items()})
    for name in ("ora_vibe_coder/__main__.py", "ora_vibe_coder/server.py", "ora_vibe_coder/static/index.html", "plugins/ora-vibe-coder/references/shared-contract.md"):
        if name not in files:
            raise ValueError(f"Required source is missing: {name}. Previous installation preserved.")
    for name, data in files.items():
        if name.endswith(".py"):
            compile(data, name, "exec")
    return install_locked(source, home, platform, destination, hosts, plugin, version, files)


def install_locked(source, home, platform, destination, hosts, plugin, version, files):
    with AppLock(destination.parent / "app.lock"):
        return install_files(source, home, platform, destination, hosts, plugin, version, files)


def install_files(source, home, platform, destination, hosts, plugin, version, files):
    if platform == "win32":
        logo = ROOT / "ora_vibe_coder" / "static" / "ora-logo.png"
        files[f"{EXECUTABLE_NAME}.ico"] = windows_icon_bytes(logo.read_bytes())
    # Verified before any staging directory is created, so a divergent bundle
    # aborts with the previous installation untouched.
    bridge = bridge_files(source)
    replacements = []
    try:
        skills = [skill for skill in (plugin / "skills").iterdir() if skill.is_dir()]
        if not skills:
            raise ValueError("The Vibe release has no native entries. The previous installation was preserved.")
        loop_installer = plugin / "resources/programming-loop/scripts/install.py"
        if hosts and not loop_installer.is_file():
            raise ValueError("The bundled Programming Loop installer is missing. The previous installation was preserved.")
        for host in hosts:
            if not (plugin / "resources/programming-loop/adapters" / f"{host}.md").is_file():
                raise ValueError(f"The selected {host} host operations are missing. The previous installation was preserved.")
        # Setup never rolls back: this runs before the first staging directory
        # is created, so a newer installed app, launcher, Bridge, Vibe entry,
        # or installed Programming Loop changes nothing.
        refuse_to_replace_newer(home, platform, destination, hosts,
                                [skill.name for skill in skills], plugin, version)
        replacements.append((destination, prepare_replacement(destination, files, version)))
        replacements.append((bridge_home(destination), prepare_replacement(bridge_home(destination), bridge, version)))
        for host in hosts:
            for skill in skills:
                native = {"SKILL.md": (skill / "SKILL.md").read_text(encoding="utf-8").replace("../../", "./").encode("utf-8")}
                for directory in ("frameworks", "references", "resources"):
                    if (plugin / directory).is_dir():
                        native.update({f"{directory}/{name}": data for name, data in file_map(plugin / directory).items()})
                operations = plugin / "resources/programming-loop/adapters" / f"{host}.md"
                if skill.name in {"ora-programming", "ora-vibe-coder"} and operations.is_file():
                    native["SKILL.md"] += f"\nRead the selected host operations at [host operations](./resources/programming-loop/adapters/{host}.md). These operations do not change the common Vibe method.\n".encode()
                target = home / SKILL_HOMES[host] / "skills" / skill.name
                replacements.append((target, prepare_replacement(target, native, version)))
        shortcut = shortcut_location(home, platform)
        replacements.append((shortcut, prepare_replacement(shortcut, launcher_files(destination, platform, version=version), version)))
        for host in hosts:
            run_loop_installer(loop_installer, "install-check", host, home)
        extra_targets = list(programming_loop_targets(home, hosts))

        def apply_complete_install():
            apply_replacements(replacements)
            installed_loop = destination / "plugins" / "ora-vibe-coder" / "resources" / "programming-loop" / "scripts" / "install.py"
            for host in hosts:
                run_loop_installer(installed_loop, "install", host, home)
            if platform == "win32":
                # One owned desktop shortcut; the old launcher stays for release migration.
                ensure_windows_shortcut(home, destination, sys.executable, destination / f"{EXECUTABLE_NAME}.ico")

        if platform == "win32" and os.name == "nt":
            extra_targets.append(home / "Desktop" / f"{EXECUTABLE_NAME}.lnk")
        transaction(
            [target for target, _ in replacements] + extra_targets,
            apply_complete_install,
        )
    except BaseException:
        for _, staging in replacements:
            if staging.exists():
                shutil.rmtree(staging)
        raise
    configured = (
        "Vibe and Programming Loop entries were installed for the selected coding tools."
        if hosts else
        "The Vibe application was installed without coding-tool entries."
    )
    return {"app": str(destination), "bridge": str(bridge_home(destination)),
            "launcher": str(shortcut), "hosts": list(hosts), "version": version,
            "note": configured + " The bundled Agent Bridge runtime was installed beside the application for the in-app conversation. Ora AI Boost (Gear 3 and Gear 4) is an optional extra for Specification and Planning — Vibe works without it; its releases are at https://github.com/ora-commons/ora-adversarial-review/releases/latest. Account access is checked by your coding tool; no model has been called."}


def preflight_remove_directory(folder):
    folder = Path(folder)
    if not folder.exists():
        return
    if any(p.is_symlink() for p in (folder, *folder.parents)) or any(p.is_symlink() for p in folder.rglob("*")):
        raise ValueError("Installation contains a symbolic link; preserve it before removal.")
    data = identity(folder)
    changed = []
    for name, expected in data["files"].items():
        path = folder / name
        if not path.is_file() or digest(path.read_bytes()) != expected:
            changed.append(str(path))
    if changed:
        raise ValueError(
            "Installed product files were changed or are missing. Preserve or repair them before removal: "
            + ", ".join(changed)
        )
    return data


def remove_directory(folder):
    folder = Path(folder)
    data = preflight_remove_directory(folder)
    if data is None:
        return []
    for name in data["files"]:
        (folder / name).unlink()
    (folder / IDENTITY).unlink()
    retained = []
    for directory in sorted((p for p in folder.rglob("*") if p.is_dir() and not p.is_symlink()), key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    if not any(folder.iterdir()):
        folder.rmdir()
    else:
        retained = [str(path) for path in folder.rglob("*") if path.is_file()]
    return retained


def shortcut_location(home, platform):
    if platform == "darwin":
        return home / "Applications" / "Ora Vibe Coder.app"
    if platform == "win32":
        return home / "Desktop" / "Ora Vibe Coder"
    return home / ".local" / "share" / "applications" / "ora-vibe-coder"


def remove(source=ROOT, *, home=None, destination=None, hosts=(), platform=None):
    source, home, platform = Path(source).resolve(), Path(home or Path.home()).absolute(), platform or sys.platform
    destination = Path(destination or install_location(home, platform)).absolute()
    if source == destination or source.is_relative_to(destination):
        raise ValueError("Run removal from a separate downloaded release, not from the installed application.")
    unknown = set(hosts) - set(SKILL_HOMES)
    if unknown:
        raise ValueError("Select a supported coding tool.")
    plugin = source / "plugins/ora-vibe-coder"
    loop_installer = plugin / "resources/programming-loop/scripts/install.py"
    retained, notes = [], []
    with AppLock(destination.parent / "app.lock"):
        skills = [skill for skill in (plugin / "skills").iterdir() if skill.is_dir()]
        vibe_targets = [
            *(home / SKILL_HOMES[host] / "skills" / skill.name for host in hosts for skill in skills),
            shortcut_location(home, platform),
            bridge_home(destination),
            destination,
        ]
        loop_hosts = []
        for host in hosts:
            loop_identity = home / SKILL_HOMES[host] / "skills/programming-loop/SOURCE.json"
            if loop_identity.is_symlink():
                raise ValueError(f"Programming Loop identity is a symbolic link: {loop_identity}")
            if loop_identity.is_file():
                try:
                    marker = json.loads(loop_identity.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    marker = {}
                if marker.get("component") == "programming-loop" and marker.get("source") == "programming-loop":
                    if not loop_installer.is_file():
                        raise ValueError("The bundled Programming Loop removal tool is missing; no Vibe files were removed.")
                    run_loop_installer(loop_installer, "remove-check", host, home)
                    loop_hosts.append(host)
        for target in vibe_targets:
            preflight_remove_directory(target)
        desktop_shortcut = home / "Desktop" / f"{EXECUTABLE_NAME}.lnk"

        def apply_complete_removal():
            for host in loop_hosts:
                note = run_loop_installer(loop_installer, "remove", host, home)
                if note:
                    notes.append(note)
            for target in vibe_targets:
                retained.extend(remove_directory(target))
            if platform == "win32" and os.name == "nt" and desktop_shortcut.is_file():
                desktop_shortcut.unlink()

        removal_targets = programming_loop_targets(home, loop_hosts) + vibe_targets
        if platform == "win32" and os.name == "nt":
            removal_targets.append(desktop_shortcut)
        transaction(
            removal_targets,
            apply_complete_removal,
        )
        shortcut = shortcut_location(home, platform)
    return {
        "app": str(destination), "launcher": str(shortcut), "hosts": list(hosts),
        "retained": sorted(set(retained)), "notes": notes,
    }


def main():
    parser = argparse.ArgumentParser(description="Install Ora Vibe Coder's application and selected coding-tool entries. Python 3.10+ is required.")
    parser.add_argument("action", choices=("install", "remove"))
    parser.add_argument("--home", type=Path, default=Path.home(), help="User home; use a disposable location for inspection")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--host", choices=tuple(SKILL_HOMES), action="append", default=[])
    args = parser.parse_args()
    if args.action == "install":
        print(json.dumps(install(home=args.home, destination=args.destination, hosts=args.host), indent=2))
    else:
        result = remove(home=args.home, destination=args.destination, hosts=args.host)
        print("Vibe application, launcher, and selected Vibe entries removed. Projects, documents, other host files, and credentials were preserved.")
        if result["retained"]:
            print("Retained unowned additions:\n" + "\n".join(result["retained"]))


if __name__ == "__main__":
    main()
