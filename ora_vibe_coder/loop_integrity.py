"""Verify Vibe's vendored Programming Loop and Agent Bridge against reviewed Git identities."""

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

# This is the single maintainer update point for a reviewed Bridge runtime
# import. The Bridge repository is public and authoritative in one place, so
# the authoritative and public release repositories name the same source.
BRIDGE_AUTHORITY = {
    "authoritative_repository": "ora-commons/agent-bridge",
    "public_release_repository": "ora-commons/agent-bridge",
    "source_revision": "6fa124252baa55c5860161ed509321fab8371d83",
    "source_tree": "5f6fa7605c4db32048e2210d367e0ea757bc7fab",
    "vendored_snapshot": "components/agent-bridge",
}

BRIDGE_PATHS = (
    "LICENSE",
    "NOTICE",
    "README.md",
    "bridge/__init__.py",
    "bridge/__main__.py",
    "bridge/claude.py",
    "bridge/cli.py",
    "bridge/codex.py",
    "bridge/connectors.py",
    "bridge/errors.py",
    "bridge/hermes.py",
    "bridge/locking.py",
    "bridge/minimax.py",
    "bridge/peer.py",
    "bridge/qwen.py",
    "bridge/record.py",
    "bridge/runner.py",
    "bridge/session.py",
    "bridge/zcode.py",
)


class LoopIntegrityError(ValueError):
    pass


def _validated_authority(authority: dict[str, str], component: str) -> dict[str, str]:
    required = {
        "authoritative_repository",
        "public_release_repository",
        "source_revision",
        "source_tree",
        "vendored_snapshot",
    }
    if set(authority) != required or not all(
            isinstance(authority[name], str) and authority[name]
            for name in required):
        raise LoopIntegrityError(f"{component} authority metadata is incomplete")
    for name in ("source_revision", "source_tree"):
        if not re.fullmatch(r"[0-9a-f]{40}", authority[name]):
            raise LoopIntegrityError(f"{component} {name} is not a Git SHA-1 identity")
    vendored = PurePosixPath(authority["vendored_snapshot"])
    if (vendored.is_absolute() or ".." in vendored.parts
            or str(vendored) != authority["vendored_snapshot"]):
        raise LoopIntegrityError(f"{component} vendored snapshot path is invalid")
    return dict(authority)


def authority_metadata() -> dict[str, str]:
    """Return a validated copy so consumers never carry their own pins."""
    return _validated_authority(AUTHORITY, "Programming Loop")


def bridge_authority_metadata() -> dict[str, str]:
    """The Agent Bridge runtime's reviewed identity, validated the same way."""
    return _validated_authority(BRIDGE_AUTHORITY, "Agent Bridge")


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
    """Read the exact 17 Loop files: their bytes, Git modes, and tree ID."""
    return _read_exact_snapshot(root, VENDORED_PATHS, allowed_extra, "Programming Loop")


def read_bridge_snapshot(root: Path, *, allowed_extra: set[str] | None = None
                         ) -> tuple[dict[str, bytes], dict[str, str], str]:
    """Read the exact 19 Bridge runtime files: bytes, Git modes, and tree ID."""
    return _read_exact_snapshot(root, BRIDGE_PATHS, allowed_extra, "Agent Bridge")


def _read_exact_snapshot(root: Path, vendored_paths: tuple[str, ...],
                         allowed_extra: set[str] | None, component: str
                         ) -> tuple[dict[str, bytes], dict[str, str], str]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise LoopIntegrityError(f"{component} snapshot is not a plain directory: {root}")
    expected = set(vendored_paths)
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
            raise LoopIntegrityError(f"{component} snapshot contains a symbolic link: {relative}")
        # Generated Python caches are not shipped source: a vendored runtime
        # creates __pycache__ directories (and .pyc files) the moment it runs,
        # so both are excluded from the exact-file check. Anything else inside
        # a cache directory is unexpected content and still fails.
        if item.is_dir():
            if item.name != "__pycache__":
                actual_directories.add(relative.as_posix())
            continue
        if not item.is_file():
            raise LoopIntegrityError(f"{component} snapshot contains a special file: {relative}")
        if item.suffix == ".pyc":
            continue
        if "__pycache__" in relative.parts:
            raise LoopIntegrityError(
                f"{component} snapshot contains a non-cache file in __pycache__: {relative}")
        actual_files.add(relative.as_posix())
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
            f"{component} snapshot does not contain its exact {len(vendored_paths)} files: "
            + "; ".join(detail)
        )

    files, modes = {}, {}
    for name in vendored_paths:
        path = root / name
        data = path.read_bytes()
        if not data.strip():
            raise LoopIntegrityError(f"Empty {component} snapshot file: {name}")
        files[name] = data
        modes[name] = "100755" if path.stat().st_mode & 0o111 else "100644"
    return files, modes, _tree_id(files, modes)
