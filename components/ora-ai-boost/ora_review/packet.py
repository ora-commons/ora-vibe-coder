"""Exact Markdown packet construction and mechanical response parsing."""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .errors import MalformedResponse, OraReviewError
from .models import AnswerBoundary, RevisionOutcome, StageMaterial, UserMaterial


TokenFactory = Callable[[], str]

#: Environment variable that names the global instruction master explicitly.
ORA_INSTRUCTION_MASTER_ENV = "ORA_INSTRUCTION_MASTER"
#: The default master location, relative to the user's home directory.
DEFAULT_MASTER_PATH = Path(".config") / "ora" / "global-instructions.md"
#: The notice a run emits when no global instruction master is configured.
NO_MASTER_NOTICE = (
    "No global instruction master configured (set ORA_INSTRUCTION_MASTER or "
    "provision ~/.config/ora/global-instructions.md); packets carry role "
    "instructions only."
)
CORE_BEGIN_MARKER = "<!-- ORA-CORE-BEGIN -->"
CORE_END_MARKER = "<!-- ORA-CORE-END -->"
CORE_RULES_HEADING = "## CORE RULES — UNIVERSAL"
CURRENT_TURN_HEADING = "## CURRENT USER INSTRUCTIONS — THIS TURN (VERBATIM)"
CURRENT_TURN_END_HEADING = "## END CURRENT USER INSTRUCTIONS"
REPOSITORY_HEADING = "## REPOSITORY INSTRUCTIONS"


@dataclass(frozen=True)
class GlobalMasterResolution:
    """One launch's global instruction master resolution.

    ``path`` and ``core_text`` are ``None`` when no core was loaded;
    ``notice`` carries the disclosure or loud warning for that case and
    is ``None`` otherwise.
    """

    path: Path | None
    core_text: str | None
    notice: str | None


def resolve_global_instruction_master() -> GlobalMasterResolution:
    """Resolve the global instruction master for this launch.

    One short read, failing open with a loud warning: a configured master
    that is missing, unreadable, or malformed never stops the run — the
    run proceeds without the core and every notice surface names the file
    and the problem. Only a machine with no master configured at all gets
    the plain unconfigured disclosure.
    """
    selected = os.environ.get(ORA_INSTRUCTION_MASTER_ENV, "").strip()
    master = (
        Path(selected).expanduser()
        if selected
        else Path.home() / DEFAULT_MASTER_PATH
    )
    text = ""
    problem: str | None = None
    try:
        text = master.read_text(encoding="utf-8")
    except FileNotFoundError:
        if not selected:
            return GlobalMasterResolution(None, None, NO_MASTER_NOTICE)
        problem = "the file is missing"
    except (OSError, UnicodeDecodeError) as exc:
        problem = f"it cannot be read as UTF-8 ({exc})"
    if problem is None:
        begins, ends = text.count(CORE_BEGIN_MARKER), text.count(CORE_END_MARKER)
        if begins == 1 and ends == 1:
            start = text.index(CORE_BEGIN_MARKER) + len(CORE_BEGIN_MARKER)
            core = text[start : text.index(CORE_END_MARKER)].strip("\n")
            if core.strip():
                return GlobalMasterResolution(master, core, None)
        problem = (
            f"it has no exactly-once nonempty core marker pair "
            f"({begins} begin / {ends} end)"
        )
    notice = (
        f"WARNING: the global instruction master at `{master}` could not be "
        f"used: {problem}. This run proceeds WITHOUT the core rules; repair "
        "or remove that file to restore them."
    )
    return GlobalMasterResolution(None, None, notice)


def load_repository_instructions(
    repository: str | Path,
) -> tuple[str | None, Path]:
    """Read the target repository's complete root ``AGENTS.md``.

    Returns ``(instructions_or_None, root)``. A missing target or an
    unreadable ``AGENTS.md`` refuses the launch before any model call; a
    repository with no ``AGENTS.md`` contributes no repository block.
    """
    given = Path(repository).expanduser()
    if not given.is_dir():
        raise OraReviewError(
            f"The repository target `{given}` is missing or unreadable."
        )
    root = given.resolve()
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return None, root
    try:
        text = agents.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise OraReviewError(
            f"Cannot read the repository instructions at `{agents}`: {exc}"
        ) from exc
    return (text.strip("\n") or None), root


def compose_instruction_prefix(
    core_text: str | None = None,
    *,
    current_turn_instructions: str | None = None,
    repository_instructions: str | None = None,
    repository_root: str | None = None,
) -> str:
    """Compose the per-run packet prefix: the core first when a global
    instruction master resolved one, then this turn's current user
    instructions (verbatim), then the repository's rules. With no master and
    neither option supplied the result is empty and binds as ``None``."""
    blocks = []
    if core_text and core_text.strip():
        blocks.append(CORE_RULES_HEADING + "\n\n" + core_text.rstrip("\n"))
    if current_turn_instructions and current_turn_instructions.strip():
        # The turn body is forwarded verbatim — no stripping or
        # normalization of the value.
        blocks.append("\n\n".join((
            CURRENT_TURN_HEADING, current_turn_instructions,
            CURRENT_TURN_END_HEADING)))
    if repository_instructions and repository_instructions.strip():
        root_label = f" — {repository_root}" if repository_root else ""
        blocks.append(f"{REPOSITORY_HEADING}{root_label}\n\n"
                      + repository_instructions.strip("\n"))
    return "\n\n".join(blocks)


@dataclass(frozen=True)
class ProtectedBlock:
    label: str
    body: str
    boundary: str

    def render(self, *, heading_level: int = 2) -> str:
        hashes = "#" * heading_level
        begin = f"<<<ORA-PROTECTED-BEGIN:{self.boundary}>>>"
        end = f"<<<ORA-PROTECTED-END:{self.boundary}>>>"
        return f"{hashes} {self.label}\n\n{begin}\n{self.body}\n{end}"


class InstructionStore:
    """Read the editable Markdown instructions shipped with this package."""

    def read(self, name: str) -> str:
        if "/" in name or "\\" in name or not name.endswith(".md"):
            raise OraReviewError(f"Invalid instruction name: {name}")
        resource = files("ora_review").joinpath("instructions", name)
        return resource.read_text(encoding="utf-8")


class PacketBuilder:
    """Build the one fixed packet shape without interpreting its contents."""

    def __init__(
        self,
        instructions: InstructionStore | None = None,
        token_factory: TokenFactory | None = None,
    ) -> None:
        self.instructions = instructions or InstructionStore()
        self._token_factory = token_factory or (lambda: uuid.uuid4().hex)
        self._instruction_snapshot: dict[str, str] | None = None
        self.instruction_prefix: str | None = None

    def bind_instruction_prefix(self, prefix: str | None) -> None:
        """Bind the resolved instruction prefix for one run.

        The run context resolves the prefix once — core first, this turn's
        current user instructions second, repository rules next — and every
        packet this run builds prepends it; ``None`` clears it.
        """
        self.instruction_prefix = prefix.strip() if prefix and prefix.strip() else None

    def snapshot_instructions(self, names: Iterable[str]) -> tuple[StageMaterial, ...]:
        """Refresh once per run; packets and RUN.md use the same exact text."""
        self._instruction_snapshot = {
            name: self.instructions.read(name) for name in dict.fromkeys(names)
        }
        return tuple(
            StageMaterial(f"INSTRUCTION — {name}", body)
            for name, body in self._instruction_snapshot.items()
        )

    def protect(self, label: str, body: str) -> ProtectedBlock:
        token = f"block-{self._token_factory()}"
        return ProtectedBlock(label, body, token)

    def answer_boundary(self) -> AnswerBoundary:
        token = f"answer-{self._token_factory()}"
        return AnswerBoundary(
            begin=f"<<<ORA-ANSWER-BEGIN:{token}>>>",
            end=f"<<<ORA-ANSWER-END:{token}>>>",
        )

    def build(
        self,
        *,
        material: UserMaterial,
        role_files: Sequence[str],
        output_file: str,
        stage_material: Sequence[StageMaterial] = (),
        answer_boundary: AnswerBoundary | None = None,
    ) -> str:
        if not role_files:
            raise OraReviewError("A role packet requires at least one role instruction.")

        instructions = self._instruction_snapshot
        if instructions is None:
            instructions = {
                name: self.instructions.read(name)
                for name in ("universal.md", *role_files, output_file)
            }
        universal = instructions["universal.md"].rstrip("\n")
        role = "\n\n".join(
            instructions[name].rstrip("\n") for name in role_files
        )
        output = instructions[output_file].rstrip("\n")
        if answer_boundary is not None:
            output = output.replace("{{ANSWER_BEGIN}}", answer_boundary.begin)
            output = output.replace("{{ANSWER_END}}", answer_boundary.end)
        elif "{{ANSWER_" in output:
            raise OraReviewError("A bounded-output packet has no supplied boundary.")

        user_blocks: list[str] = []
        user_blocks.append(
            self.protect(
                "ORIGINAL USER REQUEST — VERBATIM",
                material.original,
            ).render()
        )
        user_blocks.append(
            self._render_group(
                "LATER USER MESSAGES — VERBATIM, CHRONOLOGICAL",
                "LATER USER MESSAGE",
                material.later_user_messages,
            )
        )
        user_blocks.append(
            self._render_group(
                "PRIOR ASSISTANT CONTEXT — VERBATIM",
                "PRIOR ASSISTANT TURN",
                material.prior_assistant_turns,
            )
        )
        user_blocks.append(
            self._render_group(
                "OTHER GOVERNING CONTEXT — VERBATIM",
                "GOVERNING CONTEXT",
                material.governing_context,
            )
        )
        if material.commitment is not None:
            user_blocks.append(
                self.protect(
                    "USER COMMITMENT — VERBATIM",
                    material.commitment,
                ).render()
            )

        if stage_material:
            stage_blocks = "\n\n".join(
                self.protect(item.label, item.body).render()
                for item in stage_material
            )
        else:
            stage_blocks = "No stage material is supplied for this call."

        rendered_user_blocks = "\n\n".join(user_blocks)
        # The bound per-run prefix leads the controlling instructions when
        # one is bound; packets built outside a run context keep today's
        # shape exactly.
        prefix = f"{self.instruction_prefix}\n\n" if self.instruction_prefix else ""
        return (
            "# CONTROLLING ORA INSTRUCTIONS\n\n"
            f"{prefix}"
            "## UNIVERSAL LAWS\n\n"
            f"{universal}\n\n"
            "## ROLE FOR THIS CALL\n\n"
            f"{role}\n\n"
            "## REQUIRED INTERNAL OUTPUT\n\n"
            f"{output}\n\n"
            "---\n\n"
            "# SUPPLIED MATERIAL — VERBATIM WITH LABELLED PROVENANCE\n\n"
            f"{rendered_user_blocks}\n\n"
            "---\n\n"
            "# STAGE MATERIAL — VERBATIM\n\n"
            f"{stage_blocks}\n\n"
            "---\n\n"
            "# TASK REMINDER — CONTROLLING\n\n"
            f"{role}\n\n"
            "## OUTPUT ORDER — REQUIRED\n\n"
            f"{output}\n"
        )

    def _render_group(
        self,
        heading: str,
        item_label: str,
        values: Sequence[str],
    ) -> str:
        if not values:
            return f"## {heading}\n\nNone supplied."
        blocks = "\n\n".join(
            self.protect(f"{item_label} {index}", value).render(heading_level=3)
            for index, value in enumerate(values, start=1)
        )
        return f"## {heading}\n\n{blocks}"


def extract_answer(response: str, boundary: AnswerBoundary) -> str:
    """Return only a single nonempty answer delimited by the exact markers."""

    if response.count(boundary.begin) != 1 or response.count(boundary.end) != 1:
        raise MalformedResponse(
            "The model response did not contain exactly one supplied answer boundary pair."
        )
    start = response.index(boundary.begin) + len(boundary.begin)
    finish = response.index(boundary.end)
    if finish <= start:
        raise MalformedResponse("The answer boundary order was invalid.")
    body = response[start:finish]
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    if body.endswith("\r\n"):
        body = body[:-2]
    elif body.endswith("\n"):
        body = body[:-1]
    if not body:
        raise MalformedResponse("The supplied answer boundaries contained an empty answer.")
    return body


#: The one allowed completion line on review reports and correction results.
DISPOSITION_VALUES = ("SETTLED", "CORRECTION", "SEVERE", "INCOMPLETE", "ASK USER")
#: Any line shaped like a declaration counts as one, whatever its value: a
#: valid declaration plus an unknown one is two declarations, not one.
_DISPOSITION_DECLARATION = re.compile(r"^Review disposition:[ \t]*(.*?)[ \t]*\r?$")


def parse_disposition(response: str) -> str:
    """Parse exactly one ``Review disposition:`` line, counting every line
    shaped like a declaration — whatever its value — outside fenced code
    blocks and quotations. Missing, duplicate, unknown, or in-example
    declarations are malformed."""

    found: list[str] = []
    fence: str | None = None
    for line in response.splitlines():
        stripped = line.strip()
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        for marker in ("```", "~~~"):
            if stripped.startswith(marker):
                fence = marker
                break
        if fence is not None:
            continue
        if stripped.startswith(">"):
            continue
        match = _DISPOSITION_DECLARATION.match(line)
        if match is not None:
            found.append(match.group(1))
    if len(found) != 1:
        raise MalformedResponse(
            "The response did not contain exactly one current "
            "`Review disposition:` line outside quotations and examples."
        )
    if found[0] not in DISPOSITION_VALUES:
        raise MalformedResponse(
            f"The response declared an unknown review disposition "
            f"{found[0]!r}; allowed values are {', '.join(DISPOSITION_VALUES)}."
        )
    return found[0]


def parse_review_outcome(response: str) -> str:
    """Parse the review's single disposition line; it alone routes the
    cycle. An unfinished review is malformed so the existing recovery route
    keeps the run incomplete."""

    disposition = parse_disposition(response)
    if disposition == "INCOMPLETE":
        raise MalformedResponse("The review declared itself unfinished.")
    return disposition


#: The review section that enumerates severe findings a reviser must settle.
_SEVERE_SECTION = re.compile(r"^#{1,6} +SEVERE FINDINGS\s*$")
_SEVERE_ENTRY = re.compile(r"^[-*] +(S\d+)\b")
#: The correction section that records the reviser's per-finding decisions.
_DISPOSITION_SECTION = re.compile(r"^#{1,6} +REVIEW DISPOSITION\s*$")
#: One recorded builder decision in a correction result's REVIEW DISPOSITION
#: section; a severe finding's line is its own recorded fix and evidence.
_DISPOSITION_ITEM = re.compile(r"^[-*] +(S\d+) — .+")


def _severe_labels(review: str) -> list[str]:
    """The distinct S-labels the review's SEVERE FINDINGS section enumerated."""

    labels: list[str] = []
    in_section = False
    for line in review.splitlines():
        if _SEVERE_SECTION.match(line):
            in_section = True
            continue
        if line.startswith("#"):
            in_section = False
            continue
        if not in_section:
            continue
        entry = _SEVERE_ENTRY.match(line)
        if entry is not None and entry.group(1) not in labels:
            labels.append(entry.group(1))
    return labels


def _recorded_severe_fixes(response: str) -> set[str]:
    """The S-labels carrying a decision line inside the correction's
    REVIEW DISPOSITION section — the one place a severe finding's own
    recorded fix can live. Answer content never counts."""

    labels: set[str] = set()
    in_section = False
    for line in response.splitlines():
        if _DISPOSITION_SECTION.match(line):
            in_section = True
            continue
        if line.startswith("#"):
            in_section = False
            continue
        if not in_section:
            continue
        entry = _DISPOSITION_ITEM.match(line)
        if entry is not None:
            labels.add(entry.group(1))
    return labels


def _revision_disposition_issue(response: str, review: str) -> str | None:
    """Why a correction result does not settle the review's severe findings,
    or None when it does. A severe finding settles solely through its own
    recorded fix line in the correction's REVIEW DISPOSITION section."""

    recorded = _recorded_severe_fixes(response)
    for label in _severe_labels(review):
        if label not in recorded:
            return f"The severe finding {label} recorded no fix and evidence."
    return None


def parse_revision_outcome(
    response: str, boundary: AnswerBoundary, review: str
) -> "RevisionOutcome":
    """Parse a correction result: one complete answer and one disposition;
    a settled result must carry its severe findings' own recorded fix."""

    answer = extract_answer(response, boundary)
    disposition = parse_disposition(response)
    if disposition not in ("SETTLED", "SEVERE", "ASK USER"):
        raise MalformedResponse(
            "The correction result did not carry a settled, severe, or "
            "ask-user disposition; an unfinished correction is not a result."
        )
    if disposition == "SETTLED":
        issue = _revision_disposition_issue(response, review)
        if issue is not None:
            raise MalformedResponse(
                "The correction declared SETTLED without settling the review's "
                f"severe findings: {issue[0].lower()}{issue[1:]}"
            )
    return RevisionOutcome(answer=answer, disposition=disposition)
