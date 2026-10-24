"""Small interactive coding-tool launch operations; no agent execution engine."""

import json
import os
import selectors
import re
import time
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlencode, quote

HOSTS = {
    "codex": ("Codex", "codex"),
    "claude": ("Claude Code", "claude"),
    "zcode": ("ZCode", "zcode"),
    "hermes": ("Hermes", "hermes"),
    "qwen": ("Qwen Code", "qwen"),
    "minimax": ("MiniMax Code", "mcode"),
}
# Makers' own install instructions, shown when a tool's command is not found.
# Only established maker pages are named; no substitute page is invented for
# a tool whose maker has no public instructions to link.
INSTALL_URLS = {
    "codex": "https://github.com/openai/codex",
    "claude": "https://github.com/anthropics/claude-code",
    "qwen": "https://github.com/QwenLM/qwen-code",
}
DESKTOP_APPS = {
    "codex": "ChatGPT.app", "claude": "Claude.app", "zcode": "ZCode.app",
    "hermes": "Hermes.app", "qwen": "Qwen Code.app", "minimax": "MiniMax Code.app",
}
NOTICE = "Live host, account, and platform combinations are untested. Your coding tool retains its normal login and approval steps."
ROUTE_NOTICES = {
    "zcode": "Terminal uses one bounded, no-change receipt turn before opening ZCode's normal interactive TUI.",
    "hermes": "Terminal uses Hermes 0.18.2's interactive TUI query route.",
}
ZCODE_BOOTSTRAP = (
    "Read the complete attached UTF-8 Markdown as the user's exact assignment. "
    "Make no changes, run no implementation, and take no action requiring approval. "
    "Confirm receipt, or state the required scope approval or clarification, then stop. "
    "Work continues in the normal interactive TUI, which owns the conversation and approvals."
)
# The peers with an Agent Bridge work mode, so an in-app conversation — and an
# unattended Run to Completion — can actually exchange turns with them. Hermes
# and Qwen Code stay courier/terminal-only; nothing is silently substituted.
CONVERSATION_HOSTS = frozenset({"codex", "claude", "zcode", "minimax"})


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


def model_inventory(host):
    """Read native metadata only. Never start a model turn or change settings."""
    fallback = {"models": [], "configured_model": "", "configured_effort": "",
                "reason": "This harness does not expose a model and effort inventory to Vibe. Use harness default keeps its own configured choices."}
    command = executable(host)
    if not command:
        return {**fallback, "reason": "This harness is unavailable. Saved choices are preserved; use harness default when it is available again."}
    if host == "claude":
        try:
            # Initialization control traffic only: no user prompt, hooks, MCP startup or session persistence.
            arguments = [*command, "--print", "--input-format", "stream-json", "--output-format", "stream-json",
                         "--verbose", "--no-session-persistence", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                         "--settings", '{"disableAllHooks":true}']
            request = {"type": "control_request", "request_id": "vibe-model-metadata", "request": {"subtype": "initialize"}}
            result = subprocess.run(arguments, input=json.dumps(request) + "\n", stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8", timeout=15, shell=False)
            for line in result.stdout.splitlines():
                response = json.loads(line)
                envelope = response.get("response", {})
                if response.get("type") != "control_response" or envelope.get("request_id") != request["request_id"]:
                    continue
                data = envelope.get("response") or {}
                models = [{"id": item["value"], "label": item.get("displayName") or item["value"],
                           "efforts": item.get("supportedEffortLevels") or [], "default_effort": ""}
                          for item in data.get("models", []) if isinstance(item, dict) and isinstance(item.get("value"), str)]
                return {**fallback, "models": models,
                        "reason": "Models and effort levels come from Claude Code native initialization, without a model call. It does not report the effective configured model or effort; Use harness default follows those settings."}
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            pass
        return {**fallback, "reason": "Claude Code native metadata is inaccessible or unsupported. Use harness default follows its configured choices; saved choices are preserved."}
    if host == "minimax":
        # provider list can refresh OAuth. Read only the declared models in its native config instead.
        try:
            path = Path(os.environ.get("MINIMAX_DATA_DIR") or Path.home() / ".minimax") / "config.yaml"
            content = path.read_text(encoding="utf-8")
            provider, in_providers, in_models, models = "", False, False, []
            configured = ""
            for line in content.splitlines():
                if line and not line.startswith((" ", "#")):
                    in_providers = line.strip() == "provider:"
                    in_models = False
                    match = re.fullmatch(r"defaultModel:\s*[\"']?([\w./:+-]+)[\"']?\s*", line)
                    if match:
                        configured = match[1]
                if not in_providers:
                    continue
                match = re.fullmatch(r"  ([\w.-]+):\s*", line)
                if match:
                    provider, in_models = match[1], False
                elif re.fullmatch(r"    models:\s*", line):
                    in_models = True
                elif re.match(r"    \S", line):
                    in_models = False
                elif in_models:
                    match = re.fullmatch(r"      [\"']?([\w./:+-]+)[\"']?:\s*", line)
                    if match and provider:
                        model = provider + "/" + match[1]
                        models.append({"id": model, "label": model, "efforts": [], "default_effort": ""})
            return {**fallback, "models": models, "configured_model": configured,
                    "reason": "Models are declared in MiniMax Code’s local config.yaml, read without running provider refresh or changing sign-in. Its headless route has no effort switch; Use harness default keeps its own effort. Unrecognized config formats keep the native-default fallback."}
        except (OSError, ValueError, TypeError):
            return {**fallback, "reason": "MiniMax Code’s declared model configuration could not be read. Provider refresh is not run because it can change sign-in state. Use harness default follows its own choices."}
    if host != "codex":
        return {**fallback, "reason": "This harness’s headless route cannot accept named model or effort choices through Bridge. Use harness default keeps its own configured choices; saved named choices are preserved."}
    process = None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen([*command, "app-server"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, encoding="utf-8", shell=False)
        selector.register(process.stdout, selectors.EVENT_READ)
        sequence = 0

        def request(method, params):
            nonlocal sequence
            sequence += 1
            process.stdin.write(json.dumps({"id": sequence, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            # Bound only an inaccessible metadata query, never AI work.
            deadline = time.monotonic() + 15
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise OSError("Native metadata did not respond.")
                line = process.stdout.readline()
                if not line:
                    raise OSError("Native metadata closed before responding.")
                result = json.loads(line)
                if result.get("id") == sequence:
                    if "error" in result:
                        raise OSError("Native metadata is unsupported or inaccessible.")
                    return result.get("result") or {}

        request("initialize", {"clientInfo": {"name": "ora_vibe_coder", "version": "1"}})
        process.stdin.write(json.dumps({"method": "initialized"}) + "\n")
        process.stdin.flush()
        config = request("config/read", {"includeLayers": False}).get("config") or {}
        models, cursor = [], None
        while True:
            result = request("model/list", {"cursor": cursor})
            for item in result.get("data", []):
                model = item.get("model") or item.get("id")
                if not isinstance(model, str) or not model:
                    continue
                models.append({"id": model, "label": item.get("displayName") or model,
                               "efforts": [entry["reasoningEffort"] for entry in item.get("supportedReasoningEfforts", [])
                                           if isinstance(entry, dict) and isinstance(entry.get("reasoningEffort"), str)],
                               "default_effort": item.get("defaultReasoningEffort") or ""})
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return {"models": models, "configured_model": config.get("model") or "",
                "configured_effort": config.get("model_reasoning_effort") or "",
                "reason": "Choices come from Codex native metadata. Use harness default follows its effective configuration; a recommended model is not treated as your configured model."}
    except (OSError, ValueError, TypeError, KeyError):
        return {**fallback, "reason": "Codex native model metadata is inaccessible or unsupported. Use harness default keeps Codex's configured model and effort. Saved named choices are preserved."}
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdin.close()
            process.stdout.close()


def discover(work=None):
    """The six-tool discovery list; conversation routes follow actual facts.

    `work` maps a host id to the bundled Bridge's own work-capability label
    ("supported", "unsupported", "unknown") from the latest readiness sweep;
    when a sweep has not reported, the reviewed fixed set of the pinned
    bundle stands until Recheck refreshes both readiness and discovery.
    """
    return [{"id": key, "name": label, "detected": executable(key) is not None,
             "desktop": desktop_application(key) is not None,
             "desktop_request": "prefilled" if key in {"codex", "claude"} else "copy",
             "continuation": True,
             "conversation": work.get(key) == "supported" if work is not None
             else key in CONVERSATION_HOSTS,
             "instructions": INSTALL_URLS.get(key),
             "notice": " ".join(filter(None, (
                 NOTICE, ROUTE_NOTICES.get(key))))} for key, (label, _) in HOSTS.items()]


def desktop_application(host, platform=None):
    if (platform or sys.platform) != "darwin":
        return None
    name = DESKTOP_APPS[host]
    return next((path for path in (Path("/Applications") / name, Path.home() / "Applications" / name)
                 if path.is_dir()), None)


def desktop_arguments(host, packet, folder, app):
    if host not in {"codex", "claude"}:
        return ["open", "-a", str(app)]
    prompt = (f"Read the complete saved Markdown request at {packet}. "
              "Treat it as my full assignment, then work in this visible chat. "
              "Read the file before acting; keep your normal approval steps.")
    if host == "codex":
        url = "codex://threads/new?" + urlencode({"prompt": prompt, "path": str(folder)}, quote_via=quote)
    else:
        url = "claude://code/new?" + urlencode({"q": prompt, "folder": str(folder)}, quote_via=quote)
    return ["open", "-a", str(app), url]


def agent_arguments(host, command, packet, *, model="", effort=""):
    # The complete Markdown stays in an immutable operation-owned file, so a
    # long packet never becomes an oversized command line or shell program.
    prompt = ("Read the complete UTF-8 Markdown assignment at " + json.dumps(str(packet), ensure_ascii=False) +
              ". Treat it as the user's supplied assignment, preserve its exact user request, and follow your normal conversation and approval rules. "
              "Read every part before acting. Do not substitute a summary or an earlier Handoff.md. Return results in this conversation.")
    if host == "codex":
        choices = (["-m", model] if model else []) + (["-c", "model_reasoning_effort=" + effort] if effort else [])
        return [*command, *choices, prompt]
    if host == "claude":
        choices = (["--model", model] if model else []) + (["--effort", effort] if effort else [])
        return [*command, *choices, prompt]
    if model or effort:
        raise ValueError(f"{HOSTS[host][0]}'s interactive Terminal route cannot accept named model or effort choices. "
                         "Choose Use harness default, or use Copy and select the requested choices in the tool itself.")
    if host == "minimax":
        return [*command, prompt]
    if host == "qwen":
        return [*command, "--prompt-interactive", prompt]
    if host == "hermes":
        return [*command, "chat", "--tui", "-q", prompt]
    raise ValueError(f"No inspected interactive prompt entry is available for {HOSTS[host][0]}.")


def launch_request(host, command, packet, folder, *, model="", effort=""):
    if host == "zcode":
        if model or effort:
            raise ValueError("ZCode's interactive Terminal route cannot accept named model or effort choices. "
                             "Choose Use harness default, or use Copy and select the requested choices in ZCode itself.")
        return {
            "kind": "zcode",
            "cwd": str(folder),
            "command": command,
            "packet": str(packet),
        }
    return {
        "kind": "direct",
        "cwd": str(folder),
        "argv": agent_arguments(host, command, packet, model=model, effort=effort),
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


def continue_in(project, displayed, destination, *, purpose=None, route="terminal", launch=None, platform=None,
                model=None, effort=None):
    host = host_id(destination)
    if host is None:
        raise ValueError("Select one of the six coding tools, or use Copy for another recipient.")
    text = project.copy_snapshot(displayed, purpose)
    if route not in {"terminal", "desktop"}:
        raise ValueError("Choose Desktop or Terminal for this request.")
    if route == "desktop":
        app = desktop_application(host, platform)
        if app is None:
            raise ValueError(f"{HOSTS[host][0]} desktop app was not found. Copy the request or use Terminal if its tool is ready.")
        packet = project.root / (project.implementation_request_name() if purpose == "implement-plan" else "Handoff.md")
        folder = project.code_folder() or project.root
        args = desktop_arguments(host, packet, folder, app)
        if launch is not None:
            launch(args, {})
        else:
            subprocess.run(args, check=True, timeout=15, capture_output=True)
        detail = ("A new desktop chat was requested with the saved file location; the request is prefilled but not sent."
                  if host in {"codex", "claude"} else
                  "The desktop app was opened. Paste the request copied to your clipboard into a new chat; the request was not sent.")
        return {"state": "launch_requested", "message": f"{detail} Model and effort choices are requested in the saved assignment; select them in the desktop app. Confirm the result in {HOSTS[host][0]} itself."}
    if model is None or effort is None:
        from .handoff import requested_choices
        saved_model, saved_effort = requested_choices(text, destination)
        model = saved_model if model is None else model
        effort = saved_effort if effort is None else effort
    command = executable(host)
    if command is None:
        raise ValueError(f"{HOSTS[host][0]} terminal tool was not found. Install or enable it, then try Terminal again. Your saved Markdown and Copy remain available.")
    # Launch in the selected code folder; the documents folder is only a
    # starting point when no code folder is known.
    folder = project.code_folder() or project.root
    # Validate the selected host before creating any operation files.
    launch_request(host, command, Path("assignment.md"), folder, model=model, effort=effort)
    operation = Path(tempfile.mkdtemp(prefix="ora-vibe-continue-"))
    try:
        packet = operation / "assignment.md"
        packet.write_bytes(text.encode("utf-8"))
        packet.chmod(0o600)
        (operation / "launch.json").write_text(
            json.dumps(launch_request(host, command, packet, folder, model=model, effort=effort)),
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
