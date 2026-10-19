"""Fresh native calls and the frozen Agent Bridge Format 2 boundary."""

from __future__ import annotations

import hashlib
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
class BridgeProvenance:
    """Transport facts verified from one canonical Format 2 response."""

    peer: str
    initiator: str
    session_dir: Path
    response_path: Path
    message_sequence: int
    from_label: str
    to_label: str
    response_sha256: str
    body_sha256: str
    bridge_format: int = 2
    session_verified: bool = False


@dataclass(frozen=True)
class BridgeResponse:
    body: str
    provenance: BridgeProvenance


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
    or its own terminal error, and the grace constant above bounds only the
    cleanup of the group this call started.
    """

    cancelled: int | None = None
    waiting = False

    def cancel(signum: int, _frame: object) -> None:
        nonlocal cancelled
        cancelled = signum
        if waiting:
            raise SystemExit(128 + signum)

    handlers = {
        signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGHUP)
    }
    try:
        for signum in handlers:
            signal.signal(signum, cancel)
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
            # Defer cancellation during child creation and cleanup; never abandon it.
            waiting = True
            try:
                if cancelled is not None:
                    raise SystemExit(128 + cancelled)
                stdout, stderr = process.communicate(input=body, timeout=timeout)
            finally:
                waiting = False
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


class CodexAdapter:
    """Start one isolated, ephemeral, read-only Codex process per role."""

    engine = "codex"

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("codex") or "codex"

    def call(self, packet: str, *, role: str) -> str:
        with tempfile.TemporaryDirectory(prefix="ora-review-codex-") as directory:
            root = Path(directory)
            response_path = root / "final-response.md"
            argv = (
                self.executable,
                "exec",
                "--ephemeral",
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

        model_usage = payload.get("modelUsage")
        if not isinstance(model_usage, dict):
            reported: list[str] = []
        else:
            reported = sorted(
                key for key in model_usage if isinstance(key, str) and key.strip()
            )
        if len(reported) != 1:
            detail = ", ".join(f"`{key}`" for key in reported) or "none"
            raise CallFailure(
                f"Fresh Claude Code role `{role}` did not report one unambiguous "
                f"effective model; returned modelUsage keys: {detail}."
            )

        effective_model = reported[0]
        if self.model is not None:
            normalized_selector = self.model.casefold()
            normalized_effective = effective_model.casefold()
            if normalized_selector == "fable":
                matches = normalized_effective.startswith("claude-fable-")
            else:
                matches = normalized_effective == normalized_selector or (
                    normalized_effective.startswith(normalized_selector + "-")
                )
            if not matches:
                raise CallFailure(
                    f"Fresh Claude Code role `{role}` requested model selector "
                    f"`{self.model}` but reported effective model `{effective_model}`."
                )
        self.effective_model = effective_model
        return payload["result"]

    def call(self, packet: str, *, role: str) -> str:
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
            (root / "bridge" / "__main__.py").is_file()
            and (root / "bridge" / "cli.py").is_file()
        ):
            return None
        version = None
        try:
            found = re.search(
                r'^VERSION\s*=\s*"([^"\n]+)"',
                (root / "bridge" / "__init__.py").read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        except OSError:
            found = None
        if found is not None:
            version = found.group(1)
        return cls(root, (sys.executable, "-m", "bridge"), version)

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
                    "usable Bridge checkout: it has no `bridge/__main__.py` and "
                    "`bridge/cli.py`. No fallback to another installation was "
                    "attempted."
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
        initiator: str,
        session_dir: Path,
        session_verified: bool = False,
    ) -> None:
        self.command = command
        self.peer = peer
        self.engine = peer
        self.initiator = initiator
        self.session_dir = session_dir
        self.session_verified = session_verified
        self.last_call_notice = ""
        self.last_call_provenance: BridgeProvenance | None = None

    @classmethod
    def prepare(cls, *, peer: str, initiator: str) -> tuple["BridgeAdapter", str]:
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
        cls._verify_session_record(
            session_dir,
            peer=peer,
            initiator=initiator,
        )
        return cls(
            command,
            peer=peer,
            initiator=initiator,
            session_dir=session_dir,
            session_verified=True,
        ), readiness

    def call(self, packet: str, *, role: str) -> str:
        """One fresh analytical call, with no elapsed-time cutoff.

        No deadline is passed to Bridge and none is imposed here: the call
        ends when the peer answers, the caller cancels, or transport fails.
        """
        self.last_call_notice = ""
        self.last_call_provenance = None
        before = self._response_paths()
        try:
            result = self.command.run(
                (
                    "run",
                    "--session",
                    str(self.session_dir),
                ),
                body=packet,
                timeout=None,
            )
        except CallFailure as failure:
            detail = published_detail = failure.display()
        else:
            if result.returncode == 0:
                self.last_call_notice = result.stderr.decode("utf-8", errors="replace")
                lines = [line for line in _display_bytes(result.stdout).splitlines() if line]
                if len(lines) != 1:
                    raise CallFailure(
                        f"Agent Bridge returned an ambiguous response path for role `{role}`."
                    )
                reported = Path(lines[0]).expanduser().resolve()
                newly_published = self._response_paths() - before
                if len(newly_published) != 1 or reported not in newly_published:
                    raise CallFailure(
                        f"Agent Bridge did not publish exactly one new response for role `{role}`."
                    )
                return self._read_response(reported)
            detail = _display_bytes(result.stderr) or (
                f"Agent Bridge role `{role}` exited {result.returncode}."
            )
            published_detail = _display_bytes(result.stderr) or (
                f"Agent Bridge role `{role}` exited {result.returncode} after "
                "publishing a readable response."
            )

        newly_published = self._response_paths() - before
        if len(newly_published) == 1:
            body = self._read_response(next(iter(newly_published)))
            raise CallFailure(published_detail, usable_response=body)
        if len(newly_published) > 1:
            detail = (
                f"{detail} More than one new peer response appeared in the session; "
                "none was guessed."
            )
        raise CallFailure(detail)

    def call_with_provenance(self, packet: str, *, role: str) -> BridgeResponse:
        """Return one successful response together with verified transport facts."""

        body = self.call(packet, role=role)
        if self.last_call_provenance is None:
            raise CallFailure(
                f"Agent Bridge returned role `{role}` without verified response provenance."
            )
        return BridgeResponse(body, self.last_call_provenance)

    def _response_paths(self) -> set[Path]:
        messages = self.session_dir / "messages"
        if not messages.is_dir():
            return set()
        return {
            path.resolve()
            for path in messages.iterdir()
            if path.is_file() and self._RESPONSE_NAME.fullmatch(path.name)
        }

    def _read_response(self, path: Path) -> str:
        messages = (self.session_dir / "messages").resolve()
        resolved = path.expanduser().resolve()
        if resolved.parent != messages or not self._RESPONSE_NAME.fullmatch(resolved.name):
            raise CallFailure(
                f"Agent Bridge returned a response path outside its session: {path}"
            )
        try:
            raw = resolved.read_bytes()
            text = raw.decode("utf-8")
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
        name_match = self._RESPONSE_NAME.fullmatch(resolved.name)
        if name_match is None:
            raise MalformedResponse(
                f"Agent Bridge response `{resolved}` has an invalid response identity."
            )
        sequence_text = name_match.group("sequence")
        expected_header = [
            f"# Message {sequence_text}",
            f"From: {self.peer}",
            f"To: {self.initiator}",
        ]
        if header.splitlines() != expected_header:
            raise MalformedResponse(
                f"Agent Bridge response `{resolved}` has an ambiguous or incorrect "
                "Format 2 identity and direction."
            )
        self.last_call_provenance = BridgeProvenance(
            peer=self.peer,
            initiator=self.initiator,
            session_dir=self.session_dir.expanduser().resolve(),
            response_path=resolved,
            message_sequence=int(sequence_text),
            from_label=self.peer,
            to_label=self.initiator,
            response_sha256=hashlib.sha256(raw).hexdigest(),
            body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            session_verified=self.session_verified,
        )
        return body

    @staticmethod
    def _verify_session_record(
        session_dir: Path,
        *,
        peer: str,
        initiator: str,
    ) -> None:
        path = session_dir.expanduser().resolve() / "SESSION.md"
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as failure:
            raise CallFailure(
                f"Agent Bridge session `{path}` could not be verified as Format 2: {failure}"
            ) from failure
        marker = "\n\n## Body\n\n"
        if marker not in text:
            raise CallFailure(
                f"Agent Bridge session `{path}` has no Format 2 body boundary."
            )
        header, body = text.split(marker, 1)
        expected_header = [
            "# Session",
            "",
            "Bridge-Format: 2",
            f"Initiator: {initiator}",
            f"Peer: {peer}",
        ]
        if header.splitlines() != expected_header or not body.strip():
            raise CallFailure(
                f"Agent Bridge session `{path}` has an ambiguous or incorrect "
                "Format 2 identity."
            )
