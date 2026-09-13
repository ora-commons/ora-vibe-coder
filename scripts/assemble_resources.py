#!/usr/bin/env python3
"""Assemble Vibe's generated Loop context from one explicit component root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


ROOT = Path(__file__).resolve().parents[1]
HOSTS = ("codex", "claude", "zcode", "hermes", "qwen", "minimax")
RESOURCE_PATHS = (
    "VERSION",
    "LICENSE",
    "NOTICE.md",
    "README.md",
    "frameworks/programming-loop.md",
    *(f"adapters/{host}.md" for host in HOSTS),
    "scripts/install.py",
    "skills/programming-loop/SKILL.md",
    "profiles/claude/programming-loop-reviewer.md",
    "profiles/zcode/programming-loop-reviewer.md",
    "profiles/qwen/programming-loop-reviewer.md",
)


class AssemblyError(ValueError):
    pass


def regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise AssemblyError(f"Missing or non-regular Loop resource: {path}")
    data = path.read_bytes()
    if not data.strip():
        raise AssemblyError(f"Empty Loop resource: {path}")
    return data


def sync_vibe_versions() -> str:
    """Derive native manifest versions from Vibe's neutral version source."""
    plugin = ROOT / "plugins/ora-vibe-coder"
    version = regular_bytes(plugin / "VERSION").decode("utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise AssemblyError("Vibe VERSION must identify a release, such as 1.0.0")
    for folder in (".codex-plugin", ".claude-plugin"):
        manifest = plugin / folder / "plugin.json"
        data = json.loads(regular_bytes(manifest))
        if data.get("version") == version:
            continue
        data["version"] = version
        replacement = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=manifest.parent,
                prefix=".plugin-version-", delete=False) as stream:
            staging = Path(stream.name)
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(staging, manifest)
        finally:
            staging.unlink(missing_ok=True)
    return version


def assemble(loop_source: Path, revision: str | None = None,
             target: Path | None = None) -> Path:
    source = Path(loop_source).resolve(strict=True)
    target = Path(target) if target else ROOT / "plugins/ora-vibe-coder/resources/programming-loop"
    target = target.absolute()
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise AssemblyError(f"Generated resource target is not a plain directory: {target}")

    payload = {name: regular_bytes(source / name) for name in RESOURCE_PATHS}
    version = payload["VERSION"].decode("utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise AssemblyError("Loop VERSION must identify a release, such as 1.0.0")
    sync_vibe_versions()
    identity = {
        "component": "programming-loop",
        "source": "programming-loop",
        "version": version,
        "files": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(payload.items())
        },
    }
    if revision:
        identity["source_revision"] = revision

    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.parent / ".programming-loop-previous"
    if backup.exists():
        raise AssemblyError(
            f"Previous generated resources remain at {backup}; preserve or remove them before retrying"
        )
    staging_root = Path(tempfile.mkdtemp(prefix=".programming-loop-stage-", dir=target.parent))
    staged = staging_root / "programming-loop"
    try:
        for name, data in payload.items():
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (staged / "SOURCE.json").write_text(
            json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for name, data in payload.items():
            if regular_bytes(staged / name) != data:
                raise AssemblyError(f"Staged Loop resource differs: {name}")

        previous = target.exists()
        try:
            if previous:
                os.replace(target, backup)
            os.replace(staged, target)
        except BaseException:
            if previous and backup.exists():
                if target.exists():
                    shutil.rmtree(target)
                os.replace(backup, target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return target
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop-source", required=True, type=Path)
    parser.add_argument("--source-revision")
    args = parser.parse_args()
    print(assemble(args.loop_source, args.source_revision))
