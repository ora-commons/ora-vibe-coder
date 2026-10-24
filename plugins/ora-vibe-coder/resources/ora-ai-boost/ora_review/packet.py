"""Exact Markdown packet construction and mechanical response parsing."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .errors import MalformedResponse, OraReviewError
from .models import AnswerBoundary, StageMaterial, UserMaterial


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


def read_core_from_global_master(path: Path | str) -> str:
    """Return the marked core from a global instruction master, read per
    launch.

    Raises ``OraReviewError`` when it is missing, unreadable, invalid
    UTF-8, or has no exactly-once complete marker pair, so a launch meant
    to carry the core refuses to run without it.
    """
    master = Path(path).expanduser()
    try:
        text = master.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise OraReviewError(
            f"Cannot read the global instructions master at `{master}`: {exc}. "
            "See the README's `Global instruction master (optional)` section "
            "for the accepted file shape and how to select one."
        ) from exc
    begins, ends = text.count(CORE_BEGIN_MARKER), text.count(CORE_END_MARKER)
    core = (
        text[text.index(CORE_BEGIN_MARKER) + len(CORE_BEGIN_MARKER):
             text.index(CORE_END_MARKER)]
        if begins == 1 and ends == 1 else ""
    ).strip("\n")
    if not core.strip():
        raise OraReviewError(
            f"The global instructions master at `{master}` has no exactly-once "
            f"nonempty core marker pair ({begins} begin / {ends} end). See the "
            "README's `Global instruction master (optional)` section for the "
            "accepted file shape."
        )
    return core


@dataclass(frozen=True)
class GlobalMasterResolution:
    """One launch's global instruction master resolution.

    ``path`` and ``core_text`` are ``None`` when no master is configured;
    ``notice`` is the disclosure for that case and ``None`` otherwise.
    """

    path: Path | None
    core_text: str | None
    notice: str | None


def resolve_global_instruction_master() -> GlobalMasterResolution:
    """Resolve the global instruction master for this launch.

    The chain: (1) ``ORA_INSTRUCTION_MASTER`` names the master file
    explicitly (``expanduser`` applied) — a selected master that is missing,
    unreadable, invalid UTF-8, or lacks the exactly-once nonempty core
    marker pair is a hard ``OraReviewError`` naming the path; (2) otherwise
    any directory entry at ``~/.config/ora/global-instructions.md`` counts
    as provisioned — a regular file there gets the same validation and the
    same hard error, while a non-regular entry (a directory or a dangling
    symlink) is a hard ``OraReviewError`` naming the path, and so is a
    lookup that cannot be performed (a parent directory that cannot be
    searched), because a failed probe must not masquerade as absence; (3)
    only a genuinely absent path — including a parent that is a regular
    file, so nothing can be provisioned there — means no master is
    configured: the launch proceeds without the core and discloses that
    through ``notice``. Fail-open applies only to the unconfigured case; a
    selected or provisioned master that is broken fails closed.
    """
    selected = os.environ.get(ORA_INSTRUCTION_MASTER_ENV, "").strip()
    if selected:
        master = Path(selected).expanduser()
        return GlobalMasterResolution(
            master, read_core_from_global_master(master), None
        )
    default = Path.home() / DEFAULT_MASTER_PATH
    try:
        default.lstat()
    except (FileNotFoundError, NotADirectoryError):
        # Genuine absence: no entry — or no possible entry, when a parent
        # is a regular file — means the unconfigured fail-open case.
        return GlobalMasterResolution(None, None, NO_MASTER_NOTICE)
    except OSError as exc:
        # The lookup itself failed (a parent directory cannot be searched,
        # for example). That is inaccessibility, not absence: an explicit
        # probe keeps it from being mistaken for no configuration.
        raise OraReviewError(
            f"Cannot determine whether the global instructions master at "
            f"`{default}` is provisioned: {exc}. See the README's "
            "`Global instruction master (optional)` section for the "
            "accepted file shape and how to select one."
        ) from exc
    if not default.is_file():
        raise OraReviewError(
            f"The global instructions master at `{default}` exists but "
            "is not a regular file, so it cannot provide the core. See "
            "the README's `Global instruction master (optional)` "
            "section for the accepted file shape and how to select one."
        )
    return GlobalMasterResolution(
        default, read_core_from_global_master(default), None
    )


def _expand_instruction_imports(
    text: str, base: Path, seen: frozenset[Path] = frozenset()
) -> str:
    """Expand ``@path`` import lines (relative to the file's directory);
    an import chain that revisits a file on its own chain refuses."""

    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("@") and len(stripped) > 1):
            lines.append(line)
            continue
        target = (base / stripped[1:]).resolve()
        if target in seen:
            raise OraReviewError(
                f"Instruction imports under `{base}` form a cycle at "
                f"`{stripped[1:]}`."
            )
        try:
            imported = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise OraReviewError(
                f"Cannot read instruction import `{stripped[1:]}` under "
                f"`{base}`: {exc}"
            ) from exc
        lines.append(f"[IMPORTED INSTRUCTIONS — {stripped[1:]}]")
        lines.append(
            _expand_instruction_imports(imported, target.parent, seen | {target})
        )
    return "\n".join(lines)


def resolve_assigned_paths(
    given: Sequence[Path | str], repository_root: Path
) -> tuple[Path, ...]:
    """The single pre-launch validation, reached from the loader: relative
    values resolve against the repository root, absolute values are kept,
    and a blank, missing, unreadable, or outside-the-repository path
    refuses the launch before any model call."""
    resolved: list[Path] = []
    for value in given:
        if not str(value).strip():
            raise OraReviewError("An assigned-path value is empty.")
        supplied = Path(value).expanduser()
        target = supplied if supplied.is_absolute() else repository_root / supplied
        target = target.resolve()
        if not target.exists() or not os.access(target, os.R_OK):
            raise OraReviewError(
                f"The assigned path `{value}` at `{target}` is missing or "
                "not readable."
            )
        if target == repository_root or repository_root not in target.parents:
            raise OraReviewError(
                f"The assigned path `{value}` at `{target}` does not lie "
                f"inside the repository target `{repository_root}`."
            )
        resolved.append(target)
    return tuple(resolved)


def _read_instructions_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OraReviewError(
            f"Cannot read the repository instructions at `{path}`: {exc}"
        ) from exc


def load_repository_instructions(
    repository: str | Path,
    assigned_paths: Sequence[Path | str] = (),
) -> tuple[str | None, Path]:
    """Resolve the target repository/worktree (Git worktree-aware) and read
    its complete ``AGENTS.md`` with imports expanded; assigned paths add
    their narrower rule files. A missing, unreadable, or untraversable root
    refuses. Returns ``(instructions_or_None, root)``."""
    given = Path(repository).expanduser()
    if not given.is_dir():
        raise OraReviewError(
            f"The repository target `{given}` is missing or unreadable."
        )
    root = given.resolve()
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        top = ""
    if top:
        root = Path(top).resolve()
    if not (os.access(root, os.R_OK) and os.access(root, os.X_OK)):
        raise OraReviewError(
            f"The repository target `{root}` is not readable or traversable."
        )
    assigned = resolve_assigned_paths(assigned_paths, root)
    parts: list[str] = []
    agents = root / "AGENTS.md"
    if agents.is_file():
        parts.append(_expand_instruction_imports(
            _read_instructions_file(agents), root).strip("\n"))
    for nested in sorted(_assigned_path_rule_files(root, assigned)):
        scope = nested.parent.relative_to(root).as_posix()
        parts.append(
            f"### NARROWER RULES — {nested.relative_to(root).as_posix()}\n\n"
            f"Applies to work beneath `{scope}`.\n\n"
            + _expand_instruction_imports(
                _read_instructions_file(nested), nested.parent).strip("\n")
        )
    if not parts:
        return None, root
    return "\n\n".join(parts), root


def _assigned_path_rule_files(root: Path, assigned: Sequence[Path]) -> list[Path]:
    """Narrower ``AGENTS.md`` files on each assigned path's ancestor chain,
    deduplicated and sorted so packet text is stable; the paths arrive
    already resolved and validated inside ``root``."""

    found: set[Path] = set()
    for target in assigned:
        directory = target if target.is_dir() else target.parent
        while directory != root and root in directory.parents:
            candidate = directory / "AGENTS.md"
            if candidate.is_file():
                found.add(candidate)
            directory = directory.parent
    return sorted(found)


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


def sha256_text(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProtectedBlock:
    label: str
    body: str
    boundary: str

    @property
    def digest(self) -> str:
        return sha256_text(self.body)

    def render(self, *, heading_level: int = 2) -> str:
        hashes = "#" * heading_level
        begin = f"<<<ORA-PROTECTED-BEGIN:{self.boundary}>>>"
        end = f"<<<ORA-PROTECTED-END:{self.boundary}>>>"
        return (
            f"{hashes} {self.label}\n\n"
            f"SHA-256: `{self.digest}`\n"
            f"Boundary: `{self.boundary}`\n\n"
            f"{begin}\n{self.body}\n{end}"
        )


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

    def _unique_token(self, bodies: Sequence[str], prefix: str) -> str:
        for _ in range(100):
            token = f"{prefix}-{self._token_factory()}"
            markers = (
                token,
                f"<<<ORA-PROTECTED-BEGIN:{token}>>>",
                f"<<<ORA-PROTECTED-END:{token}>>>",
                f"<<<ORA-ANSWER-BEGIN:{token}>>>",
                f"<<<ORA-ANSWER-END:{token}>>>",
            )
            if not any(marker in body for body in bodies for marker in markers):
                return token
        raise OraReviewError("Could not create a collision-free packet boundary.")

    def protect(
        self, label: str, body: str, *, collision_bodies: Sequence[str]
    ) -> ProtectedBlock:
        token = self._unique_token(collision_bodies, "block")
        return ProtectedBlock(label, body, token)

    def answer_boundary(self, collision_bodies: Sequence[str]) -> AnswerBoundary:
        token = self._unique_token(collision_bodies, "answer")
        return AnswerBoundary(
            begin=f"<<<ORA-ANSWER-BEGIN:{token}>>>",
            end=f"<<<ORA-ANSWER-END:{token}>>>",
        )

    def validation_boundary(self, collision_bodies: Sequence[str]) -> AnswerBoundary:
        token = self._unique_token(collision_bodies, "validation")
        return AnswerBoundary(
            begin=f"<<<ORA-VALIDATION-BEGIN:{token}>>>",
            end=f"<<<ORA-VALIDATION-END:{token}>>>",
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
            output = output.replace("{{VALIDATION_BEGIN}}", answer_boundary.begin)
            output = output.replace("{{VALIDATION_END}}", answer_boundary.end)
        elif "{{ANSWER_" in output or "{{VALIDATION_" in output:
            raise OraReviewError("A bounded-output packet has no supplied boundary.")

        bodies = [
            material.original,
            *material.later_user_messages,
            *material.prior_assistant_turns,
            *material.governing_context,
            *(item.body for item in stage_material),
        ]
        if material.commitment is not None:
            bodies.append(material.commitment)
        if self.instruction_prefix:
            bodies.append(self.instruction_prefix)

        user_blocks: list[str] = []
        user_blocks.append(
            self.protect(
                "ORIGINAL USER REQUEST — VERBATIM",
                material.original,
                collision_bodies=bodies,
            ).render()
        )
        user_blocks.append(
            self._render_group(
                "LATER USER MESSAGES — VERBATIM, CHRONOLOGICAL",
                "LATER USER MESSAGE",
                material.later_user_messages,
                bodies,
            )
        )
        user_blocks.append(
            self._render_group(
                "PRIOR ASSISTANT CONTEXT — VERBATIM",
                "PRIOR ASSISTANT TURN",
                material.prior_assistant_turns,
                bodies,
            )
        )
        user_blocks.append(
            self._render_group(
                "OTHER GOVERNING CONTEXT — VERBATIM",
                "GOVERNING CONTEXT",
                material.governing_context,
                bodies,
            )
        )
        if material.commitment is not None:
            user_blocks.append(
                self.protect(
                    "USER COMMITMENT — VERBATIM",
                    material.commitment,
                    collision_bodies=bodies,
                ).render()
            )

        if stage_material:
            stage_blocks = "\n\n".join(
                self.protect(item.label, item.body, collision_bodies=bodies).render()
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
        collision_bodies: Sequence[str],
    ) -> str:
        if not values:
            return f"## {heading}\n\nNone supplied."
        blocks = "\n\n".join(
            self.protect(
                f"{item_label} {index}", value, collision_bodies=collision_bodies
            ).render(heading_level=3)
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


_VERDICT = re.compile(r"^VERDICT: (PASS|FAIL)[ \t]*\r?$", re.MULTILINE)


def parse_verdict(response: str) -> str:
    """Parse one verdict only when it is the final nonblank line."""

    matches = list(_VERDICT.finditer(response))
    if len(matches) != 1:
        raise MalformedResponse(
            "The review did not contain exactly one anchored PASS or FAIL verdict."
        )
    if response[matches[0].end() :].strip():
        raise MalformedResponse("The verdict was not the final nonblank line.")
    return matches[0].group(1)
