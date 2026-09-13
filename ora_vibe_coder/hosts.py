"""Small interactive coding-tool launch operations; no agent execution engine."""

import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile

HOSTS = {
    "codex": ("Codex", "codex"),
    "claude": ("Claude Code", "claude"),
    "zcode": ("ZCode", "zcode"),
    "hermes": ("Hermes", "hermes"),
    "qwen": ("Qwen Code", "qwen"),
    "minimax": ("MiniMax Code", "mcode"),
}
NOTICE = "Implemented route; live host, account, and platform combinations are untested. Your coding tool retains its normal login and approval steps."
ROUTE_NOTICES = {
    "zcode": "Continue uses one bounded, no-change receipt turn before opening ZCode's normal interactive TUI.",
    "hermes": "Continue uses Hermes 0.18.2's interactive TUI query route.",
}
ZCODE_BOOTSTRAP = (
    "Read the complete attached UTF-8 Markdown as the user's exact assignment. "
    "Make no changes, run no implementation, and take no action requiring approval. "
    "Confirm receipt, or state the required scope approval or clarification, then stop. "
    "Work continues in the normal interactive TUI, which owns the conversation and approvals."
)
ZCODE_BOOTSTRAP_TIMEOUT = 600


def host_id(value):
    return next((key for key, (label, _) in HOSTS.items() if value.lower() in {key, label.lower()}), None)


def executable(host):
    command = shutil.which(HOSTS[host][1])
    if command:
        return [command]
    if host == "zcode" and sys.platform == "darwin":
        script = Path("/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs")
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script)]
    if host == "minimax":
        candidate = Path.home() / ".minimax-code" / "bin" / ("mcode.cmd" if os.name == "nt" else "mcode")
        if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
            return [str(candidate)]
    return None


def discover():
    return [{"id": key, "name": label, "detected": executable(key) is not None,
             "continuation": True, "notice": " ".join(filter(None, (
                 NOTICE, ROUTE_NOTICES.get(key))))} for key, (label, _) in HOSTS.items()]


def agent_arguments(host, command, packet):
    # The complete Markdown stays in an immutable operation-owned file, so a
    # long packet never becomes an oversized command line or shell program.
    prompt = ("Read the complete UTF-8 Markdown assignment at " + json.dumps(str(packet), ensure_ascii=False) +
              ". Treat it as the user's supplied assignment, preserve its exact user request, and follow your normal conversation and approval rules. "
              "Read every part before acting. Do not substitute a summary or an earlier Handoff.md. Return results in this conversation.")
    if host in {"codex", "claude", "minimax"}:
        return [*command, prompt]
    if host == "qwen":
        return [*command, "--prompt-interactive", prompt]
    if host == "hermes":
        return [*command, "chat", "--tui", "-q", prompt]
    raise ValueError(f"No inspected interactive prompt entry is available for {HOSTS[host][0]}.")


def launch_request(host, command, packet, project):
    if host == "zcode":
        return {
            "kind": "zcode",
            "cwd": str(project),
            "command": command,
            "packet": str(packet),
        }
    return {
        "kind": "direct",
        "cwd": str(project),
        "argv": agent_arguments(host, command, packet),
    }


def terminal_arguments(operation, platform=None):
    platform = platform or sys.platform
    runner = str(Path(__file__).resolve())
    if platform == "darwin":
        wrapper = operation / "Continue.command"
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join([sys.executable, runner, str(operation)]) + "\n", encoding="utf-8")
        wrapper.chmod(0o700)
        return ["open", "-a", "Terminal", str(wrapper)], {}
    if platform == "win32":
        return [sys.executable, runner, str(operation)], {"creationflags": subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0x10}
    terminal = next((shutil.which(name) for name in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm") if shutil.which(name)), None)
    if terminal is None:
        raise OSError("No supported desktop terminal was found. Install a desktop terminal or use Copy in your coding tool.")
    separator = ["--wait", "--"] if Path(terminal).name == "gnome-terminal" else ["-e"]
    return [terminal, *separator, sys.executable, runner, str(operation)], {}


def continue_in(project, displayed, destination, *, launch=None, platform=None):
    host = host_id(destination)
    if host is None:
        raise ValueError("Select one of the six coding tools, or use Copy for another recipient.")
    text = project.copy_snapshot(displayed)
    command = executable(host)
    if command is None:
        raise ValueError(f"{HOSTS[host][0]} was not found. Install or enable that coding tool, then try Continue again. Your saved Markdown and Copy remain available.")
    # Validate the selected host before creating any operation files.
    launch_request(host, command, Path("assignment.md"), project.root)
    operation = Path(tempfile.mkdtemp(prefix="ora-vibe-continue-"))
    try:
        packet = operation / "assignment.md"
        packet.write_bytes(text.encode("utf-8"))
        packet.chmod(0o600)
        (operation / "launch.json").write_text(
            json.dumps(launch_request(host, command, packet, project.root)),
            encoding="utf-8",
        )
        args, options = terminal_arguments(operation, platform)
        if launch is not None:
            launch(args, options)
        elif (platform or sys.platform) == "darwin":
            subprocess.run(args, check=True, timeout=15, capture_output=True)
        else:
            subprocess.Popen(args, **options)
    except BaseException:
        shutil.rmtree(operation)
        raise
    return {"state": "launch_requested", "message": f"Requested an interactive {HOSTS[host][0]} session with this exact saved assignment. Receipt and execution are not confirmed by the app. Continue in that window; refresh files here when work returns.", "notice": NOTICE}


def run_operation(operation):
    """The visible terminal owns the handoff copy until its coding tool exits."""
    operation = Path(operation).resolve(strict=True)
    if not operation.name.startswith("ora-vibe-continue-") or operation.parent != Path(tempfile.gettempdir()).resolve():
        raise ValueError("Not an Ora Vibe Coder launch operation.")
    try:
        data = json.loads((operation / "launch.json").read_text(encoding="utf-8"))
        if data.get("kind") == "zcode":
            command, packet, cwd = data["command"], data["packet"], data["cwd"]
            print(
                "Ora Vibe Coder: requested ZCode receipt of the exact saved assignment. "
                "Receipt and execution are not yet confirmed.",
                flush=True,
            )
            bootstrap = subprocess.run(
                [*command, "--cwd", cwd, "--mode", "plan", "--max-turns", "1",
                 "--json", "--attach", packet, "--prompt", ZCODE_BOOTSTRAP],
                cwd=cwd, shell=False, capture_output=True, text=True,
                timeout=ZCODE_BOOTSTRAP_TIMEOUT,
            )
            if bootstrap.returncode:
                print(
                    f"ZCode's receipt request exited with status {bootstrap.returncode}; "
                    "delivery is unconfirmed and implementation did not start. "
                    "The canonical Handoff.md and Copy remain available.",
                    flush=True,
                )
                return bootstrap.returncode
            response = json.loads(bootstrap.stdout)
            session_id = response.get("sessionId") if isinstance(response, dict) else None
            if not isinstance(session_id, str) or not session_id.startswith("sess_"):
                raise ValueError("ZCode did not return a valid sessionId; delivery is unconfirmed")
            visible_id = json.dumps(session_id)
            print(
                f"ZCode confirmed assignment delivery in session {visible_id}; implementation has not started. "
                "Opening the normal interactive TUI now; its conversation and approvals control the work.",
                flush=True,
            )
            try:
                result = subprocess.call(
                    [*command, "tui", "--cwd", cwd, "--mode", "build", "--resume", session_id],
                    cwd=cwd, shell=False,
                )
            except OSError as error:
                print(
                    f"ZCode session {visible_id} received the assignment, but its normal TUI could not start: "
                    f"{error}. Reopen ZCode in this project and use /resume {visible_id}. "
                    "The canonical Handoff.md and Copy remain available.",
                    flush=True,
                )
                return 1
            if result:
                print(
                    f"ZCode session {visible_id} received the assignment, but the normal TUI exited with "
                    f"status {result}. Reopen ZCode in this project and use /resume {visible_id}. "
                    "The canonical Handoff.md and Copy remain available.",
                    flush=True,
                )
            return result
        if data.get("kind") != "direct":
            raise ValueError("Unrecognized coding-tool launch operation")
        print(
            "Ora Vibe Coder: opening your selected coding tool. Receipt is not confirmed here; "
            "its normal conversation and approvals apply.",
            flush=True,
        )
        return subprocess.call(data["argv"], cwd=data["cwd"], shell=False)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"The coding tool could not start: {error}\nYour project's Handoff.md is unchanged. Return to Vibe and use Copy.", flush=True)
        return 1
    finally:
        shutil.rmtree(operation)


if __name__ == "__main__":
    raise SystemExit(run_operation(sys.argv[1]))
