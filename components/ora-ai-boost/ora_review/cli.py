"""Public command entries and their separate result/status surfaces."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .adapters import ANALYTICAL_ENGINES, BridgeAdapter, ClaudeAdapter, CodexAdapter
from .errors import CallFailure, OraReviewError
from .models import UserMaterial
from .runner import ReviewRunner, RunRequest
from .validator import ValidationRequest, ValidationRunner


def _parser(tool: str) -> argparse.ArgumentParser:
    title = "Ora Gear 3" if tool == "gear3" else "Ora Gear 4"
    parser = argparse.ArgumentParser(
        prog="ora-gear-3" if tool == "gear3" else "ora-gear-4",
        description=f"Run {title} adversarial review on one exact request.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--request",
        metavar="FILE",
        help="read the exact original request from FILE instead of standard input",
    )
    parser.add_argument(
        "--later-user",
        action="append",
        default=[],
        metavar="FILE",
        help="append one exact later user message; repeat in chronological order",
    )
    parser.add_argument(
        "--assistant-context",
        action="append",
        default=[],
        metavar="FILE",
        help="append one exact prior assistant turn supplied by the caller",
    )
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        metavar="FILE",
        help="append one exact governing-context block supplied by the caller",
    )
    parser.add_argument(
        "--peer",
        metavar="TARGET",
        help="use this exact Agent Bridge target for peer-owned roles",
    )
    parser.add_argument(
        "--native",
        choices=ANALYTICAL_ENGINES,
        default="codex",
        help=(
            "native Gear role engine (default: codex); codex and claude run "
            "their own native adapters, every other engine runs fresh "
            "text-only analytical calls through Agent Bridge"
        ),
    )
    parser.add_argument(
        "--model",
        choices=("fable", "claude-fable-5"),
        metavar="FABLE",
        help=(
            "pin the Claude Fable native model; requires --native claude "
            "(choices: fable, claude-fable-5)"
        ),
    )
    parser.add_argument("--consensus", action="store_true")
    if tool == "gear3":
        parser.add_argument(
            "--current-answer",
            metavar="FILE",
            help="review this exact complete current answer instead of generating one",
        )
    else:
        parser.add_argument(
            "--breadth",
            choices=("analytical", "committed"),
            default="analytical",
        )
        parser.add_argument(
            "--commitment",
            metavar="FILE",
            help="exact user-written commitment required by committed Breadth",
        )
    return parser


def _validator_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ora-validator",
        description=(
            "Send one exact validation request to one explicit external peer and "
            "require a complete decision for every explicit root."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--request",
        required=True,
        metavar="FILE",
        help="read the exact UTF-8 validation request from FILE; stdin is not accepted",
    )
    parser.add_argument(
        "--root",
        required=True,
        action="append",
        metavar="ID",
        help="require a decision for this exact root ID; repeat for each root",
    )
    parser.add_argument(
        "--peer",
        required=True,
        metavar="TARGET",
        help="use this exact Agent Bridge target; no fallback is permitted",
    )
    return parser


def _read_file(path: str, label: str) -> str:
    try:
        raw = Path(path).expanduser().read_bytes()
    except OSError as failure:
        raise OraReviewError(f"Could not read {label} `{path}`: {failure}") from failure
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as failure:
        raise OraReviewError(f"{label} `{path}` is not valid UTF-8.") from failure


def _read_request(path: str | None) -> str:
    if path is not None:
        return _read_file(path, "request file")
    if sys.stdin.isatty():
        raise OraReviewError(
            "No request was supplied. Pipe the exact UTF-8 request on standard input "
            "or name it with --request FILE."
        )
    raw = sys.stdin.buffer.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as failure:
        raise OraReviewError("The request on standard input is not valid UTF-8.") from failure


def _files(paths: Sequence[str], label: str) -> tuple[str, ...]:
    return tuple(_read_file(path, label) for path in paths)


def _configuration_line(tool: str, args: argparse.Namespace) -> str:
    name = "Ora Gear 3" if tool == "gear3" else "Ora Gear 4"
    ending = "consensus" if args.consensus else "one-pass"
    if tool == "gear4":
        line = (
            f"{name}; {ending}; {args.breadth} Breadth; "
            f"native engine `{args.native}`."
        )
    else:
        line = f"{name}; {ending}; native engine `{args.native}`."
    if args.model:
        line += f" Requested native model selector `{args.model}`."
    return line


def _run(tool: str, argv: Sequence[str] | None = None) -> int:
    parser = _parser(tool)
    args = parser.parse_args(list(argv) if argv is not None else None)
    runner: ReviewRunner | None = None
    native: CodexAdapter | ClaudeAdapter | BridgeAdapter | None = None
    try:
        if args.model and args.native != "claude":
            raise OraReviewError("--model requires --native claude.")
        commitment = None
        if tool == "gear4":
            if args.breadth == "committed" and not args.commitment:
                raise OraReviewError(
                    "Committed Breadth requires --commitment FILE containing the "
                    "user's exact non-empty commitment."
                )
            if args.breadth != "committed" and args.commitment:
                raise OraReviewError(
                    "--commitment is used only with --breadth committed."
                )
            if args.commitment:
                commitment = _read_file(args.commitment, "commitment file")
                if not commitment.strip():
                    raise OraReviewError("The commitment file contains no user words.")

        material = UserMaterial(
            original=_read_request(args.request),
            later_user_messages=_files(args.later_user, "later-user file"),
            prior_assistant_turns=_files(
                args.assistant_context, "assistant-context file"
            ),
            governing_context=_files(args.context, "context file"),
            commitment=commitment,
        )
        if material.original == "":
            raise OraReviewError("The original user request is empty.")
        existing_answer = None
        if tool == "gear3" and args.current_answer:
            existing_answer = _read_file(args.current_answer, "current-answer file")
            if not existing_answer:
                raise OraReviewError("The current-answer file is empty.")

        print(_configuration_line(tool, args), file=sys.stderr)
        initiator = "ora-gear-3" if tool == "gear3" else "ora-gear-4"
        if args.native == "codex":
            native = CodexAdapter()
        elif args.native == "claude":
            native = ClaudeAdapter(model=args.model) if args.model else ClaudeAdapter()
        else:
            try:
                native, native_readiness = BridgeAdapter.prepare(
                    peer=args.native, initiator=initiator
                )
            except CallFailure as failure:
                raise OraReviewError(
                    f"Selected native engine `{args.native}` is unavailable: "
                    f"{failure.display()} No other engine was substituted. "
                    f"Selectable engines: {', '.join(ANALYTICAL_ENGINES)}."
                ) from failure
            print(native_readiness, file=sys.stderr)
        native_label = {
            "codex": "Codex",
            "claude": "Claude Code",
        }.get(args.native, f"`{args.native}`")
        native_route = (
            f"fresh {native_label} contexts"
            if args.native in ("codex", "claude")
            else f"fresh Agent Bridge calls to `{args.native}`"
        )
        peer_adapter = None
        notices: tuple[str, ...] = ()
        if args.peer:
            try:
                peer_adapter, readiness = BridgeAdapter.prepare(
                    peer=args.peer, initiator=initiator
                )
                print(readiness, file=sys.stderr)
                print(
                    "Peer-owned roles use fresh Agent Bridge calls; native roles use "
                    f"{native_route} selected by `--native {args.native}`. "
                    "Fresh context is guaranteed; provider or model "
                    "diversity is promised only when separately established. "
                    + (
                        (
                            f"The requested native model selector is `{args.model}`; every "
                            "successful native call must return one matching exact model "
                            "attribution, which is recorded. "
                            if args.model
                            else "No native model selector was supplied; every successful "
                            "native call must return one unambiguous exact model "
                            "attribution, which is recorded. "
                        )
                        if args.native == "claude"
                        else "Effective model and effort are not selected or reported. "
                    )
                    + "The vendor CLI runs "
                    "as your operating-system account, and local or vendor tooling may "
                    "retain plaintext transcripts.",
                    file=sys.stderr,
                )
            except CallFailure as failure:
                exact = failure.display()
                notice = (
                    f"Selected peer `{args.peer}` is unavailable: {exact} "
                    f"This run will use fresh internal {native_label} calls instead; "
                    "no other peer was substituted. Other Bridge targets can be "
                    f"selected explicitly with `--peer`: {', '.join(ANALYTICAL_ENGINES)}."
                )
                print(notice, file=sys.stderr)
                notices = (notice,)
        else:
            print(
                f"Entirely internal route: every role uses {native_route} "
                f"selected by `--native {args.native}`. "
                "This promises context separation, not different evidence, training, "
                "models, or blind spots. "
                + (
                    (
                        f"The requested native model selector is `{args.model}`; every "
                        "successful native call must return one matching exact model "
                        "attribution, which is recorded."
                        if args.model
                        else "No native model selector was supplied; every successful "
                        "native call must return one unambiguous exact model attribution, "
                        "which is recorded."
                    )
                    if args.native == "claude"
                    else "Effective model and effort are not selected or reported."
                ),
                file=sys.stderr,
            )

        runner = ReviewRunner(native=native, peer=peer_adapter)
        request = RunRequest(
            material=material,
            existing_answer=existing_answer,
            consensus=args.consensus,
            breadth=args.breadth if tool == "gear4" else "analytical",
            initial_notices=notices,
        )
        result = runner.run_gear3(request) if tool == "gear3" else runner.run_gear4(request)
    except (CallFailure, OraReviewError, OSError) as failure:
        if isinstance(failure, CallFailure):
            detail = failure.display()
        elif isinstance(failure, OSError):
            detail = (
                f"The Markdown run record could not be updated: {failure}. "
                "Next action: restore writable storage and run the command again."
            )
        else:
            detail = str(failure)
        if (
            runner is not None
            and runner.latest_user_deliverable_answer is not None
        ):
            sys.stdout.buffer.write(
                runner.latest_user_deliverable_answer.encode("utf-8")
            )
            sys.stdout.buffer.flush()
            print("\nStatus: TECHNICAL INCOMPLETE", file=sys.stderr)
        print(detail, file=sys.stderr)
        if runner is not None and runner.run_path is not None:
            print(f"Run record: {runner.run_path}", file=sys.stderr)
        return 1

    sys.stdout.buffer.write(result.answer.encode("utf-8"))
    sys.stdout.buffer.flush()
    print(f"\nStatus: {result.status}", file=sys.stderr)
    for notice in result.notices:
        print(f"Notice: {notice}", file=sys.stderr)
    effective_model = getattr(native, "effective_model", None)
    if effective_model is not None:
        print(
            f"Verified effective native model: `{effective_model}`.",
            file=sys.stderr,
        )
    print(f"Run record: {result.run_path}", file=sys.stderr)
    return result.exit_code


def _write_status(message: str) -> None:
    sys.stderr.write(message)
    if not message.endswith("\n"):
        sys.stderr.write("\n")
    sys.stderr.flush()


def _run_validator(argv: Sequence[str] | None = None) -> int:
    parser = _validator_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    runner = ValidationRunner(status_sink=_write_status)
    try:
        request = _read_file(args.request, "validator request file")
        _write_status(
            f"Ora Validator; external only; selected peer `{args.peer}`; "
            "no native adapter or fallback."
        )
        result = runner.run(
            ValidationRequest(
                request=request,
                roots=tuple(args.root),
                peer=args.peer,
            )
        )
    except (CallFailure, OraReviewError, OSError) as failure:
        if isinstance(failure, CallFailure):
            detail = failure.display()
        elif isinstance(failure, OSError):
            detail = f"The validator run record could not be updated: {failure}."
        else:
            detail = str(failure)
        _write_status(f"Technical failure — no certification: {detail}")
        if runner.run_path is not None:
            _write_status(f"Run record: {runner.run_path}")
        return 1

    sys.stdout.buffer.write(result.output.encode("utf-8"))
    sys.stdout.buffer.flush()
    _write_status("Status: VALIDATION COMPLETE")
    _write_status(f"Run record: {result.run_path}")
    return 0


def main_gear3() -> int:
    return _run("gear3")


def main_gear4() -> int:
    return _run("gear4")


def main_validator() -> int:
    return _run_validator()
