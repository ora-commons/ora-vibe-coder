"""Exact Markdown packet construction and mechanical response parsing."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.resources import files

from .errors import MalformedResponse, OraReviewError
from .models import AnswerBoundary, StageMaterial, UserMaterial


TokenFactory = Callable[[], str]


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
        return (
            "# CONTROLLING ORA INSTRUCTIONS\n\n"
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
