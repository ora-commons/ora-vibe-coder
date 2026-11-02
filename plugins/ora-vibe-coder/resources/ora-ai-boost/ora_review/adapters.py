"""Fresh native calls and the Agent Bridge Format 2 boundary."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .errors import CallFailure, MalformedResponse


#: The six engines Gear can name for its analytical native and peer roles.
#: Codex and Claude keep their own native adapters; the other four travel as
#: text-only analytical calls through the Agent Bridge review transport, which
#: never grants them a project-editing work mode.
ANALYTICAL_ENGINES = ("codex", "claude", "zcode", "hermes", "qwen", "minimax")

#: Grace given to a process group this run owns when it is being cleaned up
#: after cancellation or failure. It bounds cleanup, not AI work: an
#: analytical model call itself has no elapsed-time cutoff at all.
PROCESS_GRACE_SECONDS = 10


@dataclass(frozen=True)
class _ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class BridgeChoices:
    """The model and effort one Bridge reply says the tool used.

    Each half is the exact single-line string the reply's header carries:
    ``Model:`` and ``Effort:`` hold the values the tool recorded, and
    ``Requested-Model:`` / ``Requested-Effort:`` appear only when the caller
    named a choice. A half the reply does not carry stays ``None``; nothing
    is inferred.
    """

    model: str | None = None
    effort: str | None = None
    requested_model: str | None = None
    requested_effort: str | None = None


def _display_bytes(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").strip()


def _run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path,
    body: bytes,
    timeout: float | None,
    env: dict[str, str] | None = None,
) -> _ProcessResult:
    """Start one process group and wait for it.

    ``timeout`` bounds only calls that are not AI work: a readiness or record
    question may be cut short. A model call passes ``None`` and is never
    killed for elapsed time — it ends on completion, explicit cancellation,
    or its own terminal error. Cancellation (SIGTERM/SIGHUP) and any other
    failure always stop and reap the process group this call started; a
    signal that lands while the child is being created is deferred until the
    child exists and its cleanup is protected.
    """
    cancelled: int | None = None

    def record(signum: int, _frame: object) -> None:
        nonlocal cancelled
        cancelled = signum

    def cancel(signum: int, frame: object) -> None:
        record(signum, frame)
        raise SystemExit(128 + signum)

    handlers = {
        signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGHUP)
    }
    try:
        for signum in handlers:
            signal.signal(signum, record)
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=env,
            )
        except OSError as failure:
            if cancelled is not None:
                raise SystemExit(128 + cancelled) from failure
            raise CallFailure(f"Could not start `{argv[0]}`: {failure}") from failure

        try:
            for signum in handlers:
                signal.signal(signum, cancel)
            if cancelled is not None:
                raise SystemExit(128 + cancelled)
            stdout, stderr = process.communicate(input=body, timeout=timeout)
        except subprocess.TimeoutExpired as failure:
            stdout, stderr = _stop_process(process)
            if cancelled is not None:
                raise SystemExit(128 + cancelled) from failure
            detail = _display_bytes(stderr)
            if detail:
                detail = f" Last error output: {detail}"
            raise CallFailure(
                f"`{argv[0]}` did not finish within {timeout:g} seconds.{detail}"
            ) from failure
        except BaseException:
            _stop_process(process)
            raise

        if cancelled is not None:
            raise SystemExit(128 + cancelled)
        return _ProcessResult(process.returncode, stdout, stderr)
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def _stop_process(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    """Terminate and reap only the process group this call started."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return process.communicate(timeout=PROCESS_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return process.communicate()


#: The start-up lines `codex exec` prints about itself before any work. The
#: Gear call is ephemeral, so there is no session file: these lines are the
#: only place Codex itself states the model and reasoning effort it is using.
_CODEX_REPORTED_MODEL = re.compile(r"(?m)^model:(.*)$")
_CODEX_REPORTED_EFFORT = re.compile(r"(?m)^reasoning effort:(.*)$")


class CodexAdapter:
    """Start one isolated, ephemeral, read-only Codex process per role."""

    engine = "codex"

    def __init__(
        self,
        executable: str | None = None,
        *,
        model: str | None = None,
        effort: str | None = None,
    ) -> None:
        self.executable = executable or shutil.which("codex") or "codex"
        self.model = model
        self.effort = effort
        self.reported_model: str | None = None
        self.reported_effort: str | None = None

    def call(self, packet: str, *, role: str) -> str:
        self.reported_model = None
        self.reported_effort = None
        with tempfile.TemporaryDirectory(prefix="ora-review-codex-") as directory:
            root = Path(directory)
            response_path = root / "final-response.md"
            argv = (
                self.executable,
                "exec",
                "--ephemeral",
                *(("-m", self.model) if self.model is not None else ()),
                *(
                    ("-c", f"model_reasoning_effort={self.effort}")
                    if self.effort is not None
                    else ()
                ),
                "--ignore-user-config",
                "--ignore-rules",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--cd",
                str(root),
                "--output-last-message",
                str(response_path),
                "-",
            )
            result = _run_bounded(
                argv,
                cwd=root,
                body=packet.encode("utf-8"),
                timeout=None,
            )
            if result.returncode != 0:
                detail = _display_bytes(result.stderr) or f"exit {result.returncode}"
                raise CallFailure(f"Fresh Codex role `{role}` failed: {detail}")
            self._read_reported_choices(result.stderr)
            try:
                response = response_path.read_bytes()
            except OSError as failure:
                raise CallFailure(
                    f"Fresh Codex role `{role}` returned no readable final response: {failure}"
                ) from failure
            try:
                return response.decode("utf-8")
            except UnicodeDecodeError as failure:
                raise CallFailure(
                    f"Fresh Codex role `{role}` returned text that was not valid UTF-8."
                ) from failure

    def _read_reported_choices(self, stderr: bytes) -> None:
        """Read the model and effort Codex says it is using for this call.

        Codex prints both at the start of its error output. A half Codex did
        not state stays unset; nothing is inferred from the request.
        """

        text = stderr.decode("utf-8", errors="replace")
        model = _CODEX_REPORTED_MODEL.search(text)
        effort = _CODEX_REPORTED_EFFORT.search(text)
        self.reported_model = model.group(1).strip() if model else None
        self.reported_effort = effort.group(1).strip() if effort else None
        if self.reported_model == "":
            self.reported_model = None
        if self.reported_effort == "":
            self.reported_effort = None


class ClaudeAdapter:
    """Start one fresh, restricted Claude Code subscription call per role."""

    engine = "claude"
    _NON_SUBSCRIPTION_ENVIRONMENT = (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_CUSTOM_HEADERS",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    )

    def __init__(
        self,
        executable: str | None = None,
        *,
        model: str | None = None,
    ) -> None:
        self.executable = executable or shutil.which("claude") or "claude"
        self.model = model
        self.effective_model: str | None = None

    def _parse_response(self, raw: bytes, *, role: str) -> str:
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as failure:
            raise CallFailure(
                f"Fresh Claude Code role `{role}` returned JSON that was not valid UTF-8."
            ) from failure
        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError as failure:
            raise CallFailure(
                f"Fresh Claude Code role `{role}` returned malformed JSON output."
            ) from failure
        if not isinstance(payload, dict):
            raise CallFailure(
                f"Fresh Claude Code role `{role}` returned a non-object JSON result."
            )
        if (
            payload.get("type") != "result"
            or payload.get("subtype") != "success"
            or payload.get("is_error") is not False
            or not isinstance(payload.get("result"), str)
        ):
            raise CallFailure(
                f"Fresh Claude Code role `{role}` returned no successful result text."
            )

        # Record the model Claude actually reports, where it reports one
        # unambiguously; nothing is verified against the request.
        model_usage = payload.get("modelUsage")
        reported = (
            sorted(
                key for key in model_usage
                if isinstance(key, str) and key.strip()
            )
            if isinstance(model_usage, dict)
            else []
        )
        self.effective_model = reported[0] if len(reported) == 1 else None
        return payload["result"]

    def call(self, packet: str, *, role: str) -> str:
        self.effective_model = None
        environment = os.environ.copy()
        for name in self._NON_SUBSCRIPTION_ENVIRONMENT:
            environment.pop(name, None)

        with tempfile.TemporaryDirectory(prefix="ora-review-claude-") as directory:
            root = Path(directory)
            argv = (
                self.executable,
                "--print",
                "--input-format",
                "text",
                "--output-format",
                "json",
                *(("--model", self.model) if self.model is not None else ()),
                "--no-session-persistence",
                "--safe-mode",
                "--restricted",
                "--permission-mode",
                "dontAsk",
                "--tools",
                "",
                "--strict-mcp-config",
                "--mcp-config",
                "{}",
                "--no-chrome",
                "--disable-slash-commands",
                "--prompt-suggestions",
                "false",
            )
            result = _run_bounded(
                argv,
                cwd=root,
                body=packet.encode("utf-8"),
                timeout=None,
                env=environment,
            )
            if result.returncode != 0:
                detail = _display_bytes(result.stderr) or f"exit {result.returncode}"
                raise CallFailure(f"Fresh Claude Code role `{role}` failed: {detail}")
            return self._parse_response(result.stdout, role=role)


@dataclass(frozen=True)
class _BridgeCommand:
    root: Path
    argv: tuple[str, ...]
    version: str | None = None

    @classmethod
    def _at(cls, candidate: Path) -> Optional["_BridgeCommand"]:
        root = candidate.expanduser().resolve()
        if not (
            (root / "ora_agent_bridge" / "__main__.py").is_file()
            and (root / "ora_agent_bridge" / "cli.py").is_file()
        ):
            return None
        version = None
        try:
            found = re.search(
                r'^VERSION\s*=\s*"([^"\n]+)"',
                (root / "ora_agent_bridge" / "__init__.py").read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        except OSError:
            found = None
        if found is not None:
            version = found.group(1)
        return cls(root, (sys.executable, "-m", "ora_agent_bridge"), version)

    @classmethod
    def locate(cls) -> "_BridgeCommand":
        """Resolve the selected Bridge copy and never fall back from it.

        ``AGENT_BRIDGE_HOME`` names the exact selected copy: if that path is
        not a usable Bridge checkout, the failure names it and no other
        installation is consulted. With no selection, the documented
        standalone default ``~/agent-bridge`` is used.
        """
        configured = os.environ.get("AGENT_BRIDGE_HOME")
        if configured:
            selected = cls._at(Path(configured))
            if selected is None:
                raise CallFailure(
                    f"The selected Agent Bridge path `{configured}` is not a "
                    "usable Bridge checkout: it has no "
                    "`ora_agent_bridge/__main__.py` and `ora_agent_bridge/cli.py`. "
                    "No fallback to another installation was attempted."
                )
            return selected
        default = cls._at(Path.home() / "agent-bridge")
        if default is None:
            raise CallFailure(
                "No Agent Bridge checkout was found.",
                "Set AGENT_BRIDGE_HOME to its absolute directory or install it at "
                f"{Path.home() / 'agent-bridge'}.",
            )
        return default

    def describe(self) -> str:
        version = self.version or "version not readable"
        return f"Agent Bridge copy used: {self.root} ({version})"

    def run(
        self,
        arguments: Sequence[str],
        *,
        body: str = "",
        timeout: float | None = 60,
    ) -> _ProcessResult:
        return _run_bounded(
            (*self.argv, *arguments),
            cwd=self.root,
            body=body.encode("utf-8"),
            timeout=timeout,
        )


class BridgeAdapter:
    """Carry analytical packets through one Format 2 Bridge session.

    The class attribute names the transport; each instance answers with the
    engine actually selected — the Bridge target whose session it carries —
    so records and disclosures preserve the chosen participant, and no other
    engine is ever substituted for it.
    """

    engine = "agent-bridge"

    _RESPONSE_NAME = re.compile(
        r"^(?P<sequence>\d{4,})-peer-to-initiator\.md$"
    )

    def __init__(
        self,
        command: _BridgeCommand,
        *,
        peer: str,
        session_dir: Path,
        model: str | None = None,
        effort: str | None = None,
    ) -> None:
        self.command = command
        self.engine = peer
        self.session_dir = session_dir
        self.model = model
        self.effort = effort
        self.last_call_notice = ""
        self.last_call_choices: BridgeChoices | None = None

    @classmethod
    def prepare(
        cls,
        *,
        peer: str,
        initiator: str,
        model: str | None = None,
        effort: str | None = None,
    ) -> tuple["BridgeAdapter", str]:
        command = _BridgeCommand.locate()
        checked = command.run(("check", "--peer", peer))
        if checked.returncode != 0:
            raise CallFailure(
                _display_bytes(checked.stderr)
                or f"Agent Bridge readiness for `{peer}` exited {checked.returncode}."
            )
        readiness = _display_bytes(checked.stdout)
        if not readiness:
            raise CallFailure(
                f"Agent Bridge readiness for `{peer}` succeeded without a status sentence."
            )
        readiness = f"{readiness}\n{command.describe()}"
        session_root = Path.home() / ".agent-bridge" / "sessions"
        session_dir = session_root / f"{initiator}-{uuid.uuid4().hex}"
        description = (
            f"# {initiator} transport session\n\n"
            "Carries one complete protected role packet per fresh peer call."
        )
        created = command.run(
            (
                "record",
                "--session",
                str(session_dir),
                "--kind",
                "session-create",
                "--initiator",
                initiator,
                "--peer",
                peer,
            ),
            body=description,
        )
        if created.returncode != 0:
            raise CallFailure(
                _display_bytes(created.stderr)
                or f"Agent Bridge could not create the `{peer}` session."
            )
        return cls(
            command,
            peer=peer,
            session_dir=session_dir,
            model=model,
            effort=effort,
        ), readiness

    def call(self, packet: str, *, role: str) -> str:
        """One fresh analytical call, with no elapsed-time cutoff.

        No deadline is passed to Bridge and none is imposed here: the call
        ends when the peer answers, the caller cancels, or transport fails.
        """
        self.last_call_notice = ""
        self.last_call_choices = None
        arguments = ("run", "--session", str(self.session_dir))
        if self.model is not None:
            arguments += ("--model", self.model)
        if self.effort is not None:
            arguments += ("--effort", self.effort)
        result = self.command.run(arguments, body=packet, timeout=None)
        if result.returncode != 0:
            detail = _display_bytes(result.stderr) or (
                f"Agent Bridge role `{role}` exited {result.returncode}."
            )
            raise CallFailure(detail)
        self.last_call_notice = result.stderr.decode("utf-8", errors="replace")
        lines = [line for line in _display_bytes(result.stdout).splitlines() if line]
        if len(lines) != 1:
            raise CallFailure(
                f"Agent Bridge returned an ambiguous response path for role `{role}`."
            )
        return self._read_response(Path(lines[0]).expanduser().resolve())

    def _read_response(self, path: Path) -> str:
        messages = (self.session_dir / "messages").resolve()
        resolved = path.expanduser().resolve()
        if resolved.parent != messages or not self._RESPONSE_NAME.fullmatch(resolved.name):
            raise CallFailure(
                f"Agent Bridge returned a response path outside its session: {path}"
            )
        try:
            text = resolved.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as failure:
            raise CallFailure(
                f"Agent Bridge response `{resolved}` could not be read as UTF-8: {failure}"
            ) from failure
        marker = "\n\n## Body\n\n"
        if marker not in text:
            raise MalformedResponse(
                f"Agent Bridge response `{resolved}` has no Format 2 body boundary."
            )
        header, body = text.split(marker, 1)
        self.last_call_choices = self._read_choices(header.splitlines())
        return body

    _CHOICE_KEYS = (
        ("Model", "model"),
        ("Effort", "effort"),
        ("Requested-Model", "requested_model"),
        ("Requested-Effort", "requested_effort"),
    )

    @classmethod
    def _read_choices(cls, lines: Sequence[str]) -> BridgeChoices | None:
        """Collect the model-and-effort lines a reply header may carry.

        Each recognized label contributes its value; unrecognized header
        lines are ignored rather than refused.
        """
        values: dict[str, str] = {}
        for line in lines:
            for label, field in cls._CHOICE_KEYS:
                prefix = f"{label}: "
                if field not in values and line.startswith(prefix):
                    value = line[len(prefix):].strip()
                    if value:
                        values[field] = value
        if not values:
            return None
        return BridgeChoices(
            model=values.get("model"),
            effort=values.get("effort"),
            requested_model=values.get("requested_model"),
            requested_effort=values.get("requested_effort"),
        )
