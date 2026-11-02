"""One append-only Markdown run record per invocation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .models import StageMaterial, UserMaterial


class RunRecord:
    def __init__(self, path: Path, initial_text: str) -> None:
        self.path = path
        self.path.write_text(initial_text, encoding="utf-8")

    @classmethod
    def create(
        cls,
        *,
        tool: str,
        route: str,
        material: UserMaterial,
        instruction_snapshot: Sequence[StageMaterial],
        instruction_prefix: str | None = None,
        instruction_prefix_provenance: str | None = None,
        run_root: Path | None = None,
        breadth: str | None = None,
        native_engine: str | None = None,
        native_model_selector: str | None = None,
        native_effort_selector: str | None = None,
    ) -> "RunRecord":
        root = run_root or (Path.home() / ".ora-adversarial-review" / "runs")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{run_id}-{uuid.uuid4().hex[:10]}"
        run_dir = root.expanduser().resolve() / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        path = run_dir / "RUN.md"

        lines = [
            "# Ora Adversarial Review Run",
            "",
            f"Run: `{run_id}`",
            f"Tool: `{tool}`",
            f"Route at start: `{route}`",
        ]
        if native_engine is not None:
            lines.append(f"Native engine: `{native_engine}`")
        if native_model_selector is not None:
            lines.append(f"Requested native model selector: `{native_model_selector}`")
        if native_effort_selector is not None:
            lines.append(
                f"Requested native reasoning effort: `{native_effort_selector}`"
            )
        if breadth is not None:
            lines.append(f"Breadth: `{breadth}`")
        if instruction_prefix_provenance is not None:
            lines.append(f"Global instruction master: `{instruction_prefix_provenance}`")
        lines.extend(["", "## Instruction snapshot", ""])
        if instruction_prefix:
            lines.extend([
                "### RESOLVED INSTRUCTION PREFIX — VERBATIM",
                "",
                instruction_prefix,
                "",
            ])
        for item in instruction_snapshot:
            lines.extend([f"### {item.label}", "", item.body, ""])
        lines.extend(["## Supplied material — verbatim", ""])
        lines.extend(["### ORIGINAL USER REQUEST — VERBATIM", "", material.original, ""])
        for label, values in (
            ("LATER USER MESSAGE", material.later_user_messages),
            ("PRIOR ASSISTANT TURN", material.prior_assistant_turns),
            ("GOVERNING CONTEXT", material.governing_context),
        ):
            for index, body in enumerate(values, start=1):
                lines.extend([f"### {label} {index} — VERBATIM", "", body, ""])
        if material.commitment is not None:
            lines.extend([
                "### USER COMMITMENT — VERBATIM",
                "",
                material.commitment,
                "",
            ])
        return cls(path, "\n".join(lines).rstrip() + "\n")

    def append(self, title: str, body: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## {title}\n\n{body}\n")

    def append_artifact(self, title: str, body: str) -> None:
        self.append(title, body)

    def finish(self, status: str, notices: Sequence[str] = ()) -> None:
        lines = [f"Status: **{status}**"]
        if notices:
            lines.extend(["", "Notices:"])
            lines.extend(f"- {notice}" for notice in notices)
        self.append("Terminal result", "\n".join(lines))
