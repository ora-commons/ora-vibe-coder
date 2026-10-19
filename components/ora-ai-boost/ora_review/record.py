"""One append-only, atomically replaced Markdown record per invocation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .models import StageMaterial, UserMaterial
from .packet import PacketBuilder


class RunRecord:
    def __init__(self, path: Path, initial_text: str) -> None:
        self.path = path
        self._text = initial_text
        self._write()

    @classmethod
    def create(
        cls,
        *,
        tool: str,
        ending: str,
        route: str,
        material: UserMaterial,
        instruction_snapshot: Sequence[StageMaterial],
        run_root: Path | None = None,
        breadth: str | None = None,
        native_engine: str | None = None,
        native_model_selector: str | None = None,
        selected_peer: str | None = None,
        requested_roots: Sequence[str] = (),
    ) -> "RunRecord":
        root = run_root or (Path.home() / ".ora-adversarial-review" / "runs")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{run_id}-{uuid.uuid4().hex[:10]}"
        run_dir = root.expanduser().resolve() / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        path = run_dir / "RUN.md"

        builder = PacketBuilder()
        material_bodies = [
            material.original,
            *material.later_user_messages,
            *material.prior_assistant_turns,
            *material.governing_context,
        ]
        if material.commitment is not None:
            material_bodies.append(material.commitment)

        title = (
            "# Ora Validator Run"
            if tool == "ora-validator"
            else "# Ora Adversarial Review Run"
        )
        config_lines = [
            title,
            "",
            f"Run: `{run_id}`",
            f"Tool: `{tool}`",
            f"Ending: `{ending}`",
            f"Route at start: `{route}`",
        ]
        if native_engine is not None:
            config_lines.append(f"Native engine: `{native_engine}`")
        if native_model_selector is not None:
            config_lines.append(
                f"Requested native model selector: `{native_model_selector}`"
            )
        if selected_peer is not None:
            config_lines.extend(
                [
                    f"Selected peer: `{selected_peer}`",
                    "Fallback: `none`",
                ]
            )
        if requested_roots:
            config_lines.extend(["", "Requested roots:"])
            config_lines.extend(f"- `{root}`" for root in requested_roots)
        if breadth is not None:
            config_lines.append(f"Breadth: `{breadth}`")
        config_lines.extend(["", "## Instruction snapshot", ""])
        snapshots = []
        for item in instruction_snapshot:
            snapshots.append(
                builder.protect(
                    item.label,
                    item.body,
                    collision_bodies=[*material_bodies, *(x.body for x in instruction_snapshot)],
                ).render(heading_level=3)
            )
        config_lines.append("\n\n".join(snapshots))
        config_lines.extend(["", "## Protected supplied material", ""])
        config_lines.append(
            builder.protect(
                "ORIGINAL USER REQUEST — VERBATIM",
                material.original,
                collision_bodies=material_bodies,
            ).render(heading_level=3)
        )
        for label, values in (
            ("LATER USER MESSAGE", material.later_user_messages),
            ("PRIOR ASSISTANT TURN", material.prior_assistant_turns),
            ("GOVERNING CONTEXT", material.governing_context),
        ):
            for index, body in enumerate(values, start=1):
                config_lines.extend(
                    [
                        "",
                        builder.protect(
                            f"{label} {index}", body, collision_bodies=material_bodies
                        ).render(heading_level=3),
                    ]
                )
        if material.commitment is not None:
            config_lines.extend(
                [
                    "",
                    builder.protect(
                        "USER COMMITMENT — VERBATIM",
                        material.commitment,
                        collision_bodies=material_bodies,
                    ).render(heading_level=3),
                ]
            )
        return cls(path, "\n".join(config_lines).rstrip() + "\n")

    def append(self, title: str, body: str) -> None:
        self._text += f"\n## {title}\n\n{body}\n"
        self._write()

    def append_artifact(self, title: str, body: str) -> None:
        block = PacketBuilder().protect(title.upper(), body, collision_bodies=[body])
        self.append(title, block.render(heading_level=3))

    def finish(self, status: str, notices: Sequence[str] = ()) -> None:
        lines = [f"Status: **{status}**"]
        if notices:
            lines.extend(["", "Notices:"])
            lines.extend(f"- {notice}" for notice in notices)
        self.append("Terminal result", "\n".join(lines))

    def _write(self) -> None:
        encoded = self._text.encode("utf-8")
        temporary = self.path.with_name(f".RUN.md.tmp-{os.getpid()}-{uuid.uuid4().hex}")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary.exists():
                temporary.unlink()
