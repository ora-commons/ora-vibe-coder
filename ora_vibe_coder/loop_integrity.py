"""Verify Vibe's vendored Programming Loop against one reviewed Git identity."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re


# This is the single maintainer update point for a reviewed Loop import.
AUTHORITY = {
    "authoritative_repository": "Golfplan18/ora-programming-loop",
    "public_release_repository": "ora-commons/ora-programming-loop",
    "source_revision": "1719eaed5f4c7c5d63dec65e011e6643b46de04c",
    "source_tree": "f38487dd1937fd666a6839becce26244623cc9ad",
    "vendored_snapshot": "components/programming-loop",
}

HOSTS = ("codex", "claude", "zcode", "hermes", "qwen", "minimax")
VENDORED_PATHS = (
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
    "tests/test_distribution.py",
)


class LoopIntegrityError(ValueError):
    pass


def authority_metadata() -> dict[str, str]:
    """Return a validated copy so consumers never carry their own pins."""
    required = {
        "authoritative_repository",
        "public_release_repository",
        "source_revision",
        "source_tree",
        "vendored_snapshot",
    }
    if set(AUTHORITY) != required or not all(
            isinstance(AUTHORITY[name], str) and AUTHORITY[name]
            for name in required):
        raise LoopIntegrityError("Programming Loop authority metadata is incomplete")
    for name in ("source_revision", "source_tree"):
        if not re.fullmatch(r"[0-9a-f]{40}", AUTHORITY[name]):
            raise LoopIntegrityError(f"Programming Loop {name} is not a Git SHA-1 identity")
    vendored = PurePosixPath(AUTHORITY["vendored_snapshot"])
    if (vendored.is_absolute() or ".." in vendored.parts
            or str(vendored) != AUTHORITY["vendored_snapshot"]):
        raise LoopIntegrityError("Programming Loop vendored snapshot path is invalid")
    return dict(AUTHORITY)


def _git_object_id(kind: str, payload: bytes) -> bytes:
    header = f"{kind} {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).digest()


def _tree_id(files: dict[str, bytes], modes: dict[str, str]) -> str:
    root: dict[str, object] = {}
    for relative, data in files.items():
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or str(path) != relative:
            raise LoopIntegrityError(f"Invalid Programming Loop snapshot path: {relative}")
        node = root
        for part in path.parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise LoopIntegrityError(f"Conflicting Programming Loop snapshot path: {relative}")
            node = child
        if path.name in node:
            raise LoopIntegrityError(f"Duplicate Programming Loop snapshot path: {relative}")
        node[path.name] = (modes[relative], _git_object_id("blob", data))

    def hash_tree(node: dict[str, object]) -> bytes:
        entries = []
        for name, value in sorted(
                node.items(),
                key=lambda item: item[0].encode("utf-8")
                + (b"/" if isinstance(item[1], dict) else b"")):
            if isinstance(value, dict):
                mode, object_id = "40000", hash_tree(value)
            else:
                mode, object_id = value
            entries.append(
                mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + object_id
            )
        return _git_object_id("tree", b"".join(entries))

    return hash_tree(root).hex()


def read_snapshot(root: Path, *, allowed_extra: set[str] | None = None
                  ) -> tuple[dict[str, bytes], dict[str, str], str]:
    """Read the exact 17 files and return their bytes, Git modes, and tree ID."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise LoopIntegrityError(f"Programming Loop snapshot is not a plain directory: {root}")
    expected = set(VENDORED_PATHS)
    allowed = set(allowed_extra or ())
    expected_files = expected | allowed
    expected_directories = {
        parent.as_posix()
        for name in expected_files
        for parent in PurePosixPath(name).parents
        if parent != PurePosixPath(".")
    }
    actual_files = set()
    actual_directories = set()
    for item in root.rglob("*"):
        relative = item.relative_to(root)
        if item.is_symlink():
            raise LoopIntegrityError(f"Programming Loop snapshot contains a symbolic link: {relative}")
        if item.is_file():
            actual_files.add(relative.as_posix())
        elif item.is_dir():
            actual_directories.add(relative.as_posix())
        else:
            raise LoopIntegrityError(f"Programming Loop snapshot contains a special file: {relative}")
    if actual_files != expected_files or actual_directories != expected_directories:
        missing = sorted(expected_files - actual_files)
        extra_files = sorted(actual_files - expected_files)
        extra_directories = sorted(actual_directories - expected_directories)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra_files:
            detail.append("unexpected files " + ", ".join(extra_files))
        if extra_directories:
            detail.append("unexpected directories " + ", ".join(extra_directories))
        raise LoopIntegrityError(
            "Programming Loop snapshot does not contain its exact 17 files: " + "; ".join(detail)
        )

    files, modes = {}, {}
    for name in VENDORED_PATHS:
        path = root / name
        data = path.read_bytes()
        if not data.strip():
            raise LoopIntegrityError(f"Empty Programming Loop snapshot file: {name}")
        files[name] = data
        modes[name] = "100755" if path.stat().st_mode & 0o111 else "100644"
    return files, modes, _tree_id(files, modes)
