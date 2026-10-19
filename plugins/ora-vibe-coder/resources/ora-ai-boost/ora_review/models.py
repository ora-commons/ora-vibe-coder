"""Data passed through the two fixed review graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class UserMaterial:
    original: str
    later_user_messages: tuple[str, ...] = ()
    prior_assistant_turns: tuple[str, ...] = ()
    governing_context: tuple[str, ...] = ()
    commitment: str | None = None


@dataclass(frozen=True)
class StageMaterial:
    label: str
    body: str


@dataclass(frozen=True)
class AnswerBoundary:
    begin: str
    end: str


@dataclass
class ReviewHistory:
    original_answer: str
    current_answer: str
    reviews: list[str] = field(default_factory=list)
    revisions: list[str] = field(default_factory=list)
    verdicts: list[str] = field(default_factory=list)
    status: str | None = None
    notices: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunResult:
    answer: str
    status: str
    run_path: str
    notices: tuple[str, ...] = ()
    technical_incomplete: bool = False

    @property
    def exit_code(self) -> int:
        return 1 if self.technical_incomplete else 0


class CallAdapter(Protocol):
    """One fresh, exact packet-in/final-body-out model call."""

    engine: str

    def call(self, packet: str, *, role: str) -> str:
        """Return one final response unchanged or raise CallFailure."""
