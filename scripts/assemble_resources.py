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
import stat
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ora_vibe_coder import loop_integrity


RESOURCE_PATHS = loop_integrity.VENDORED_PATHS
VENDORED_PATHS = loop_integrity.VENDORED_PATHS
VIBE_MANIFEST_FOLDERS = (".codex-plugin", ".claude-plugin")

ASSEMBLER = "ora-vibe-coder/scripts/assemble_resources.py"
TRANSACTION_SCHEMA = "ora-vibe-resource-assembly/v1"
LOCK_NAME = ".programming-loop-assembly-lock"
TRANSACTION_PREFIX = ".programming-loop-assembly-"
STATE_NAME = "TRANSACTION.json"
COMMIT_NAME = "COMMITTED.json"
SAFE_DIRECTORY_CLEANUP = (
    all(function in os.supports_dir_fd for function in (os.open, os.stat, os.unlink, os.rmdir))
    and os.listdir in os.supports_fd
    and os.stat in os.supports_follow_symlinks
    and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")
)


class AssemblyError(ValueError):
    pass


class RecoveryRequired(AssemblyError):
    """Automatic rollback did not finish; retained recovery needs inspection."""


def regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise AssemblyError(f"Missing or non-regular Loop resource: {path}")
    data = path.read_bytes()
    if not data.strip():
        raise AssemblyError(f"Empty Loop resource: {path}")
    return data


def vibe_manifest_outputs() -> tuple[str, dict[Path, bytes], dict[Path, tuple[bytes, int]]]:
    """Prepare both native manifests from Vibe's neutral version source."""
    plugin = ROOT / "plugins/ora-vibe-coder"
    version = regular_bytes(plugin / "VERSION").decode("utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise AssemblyError("Vibe VERSION must identify a release, such as 1.0.0")
    outputs = {}
    originals = {}
    for folder in VIBE_MANIFEST_FOLDERS:
        manifest = plugin / folder / "plugin.json"
        original = regular_bytes(manifest)
        original_mode = manifest.stat().st_mode & 0o777
        originals[manifest] = (original, original_mode)
        data = json.loads(original)
        if data.get("version") == version:
            outputs[manifest] = original
        else:
            data["version"] = version
            outputs[manifest] = (
                json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
    return version, outputs, originals


def require_prepared_manifests(
        originals: dict[Path, tuple[bytes, int]]) -> None:
    """Reject a manifest edit made after its replacement was prepared."""
    for manifest, (expected_bytes, expected_mode) in originals.items():
        try:
            current_bytes = regular_bytes(manifest)
            current_mode = manifest.stat().st_mode & 0o777
        except (OSError, AssemblyError) as error:
            raise AssemblyError(
                f"Vibe manifest changed during assembly preparation: {manifest}"
            ) from error
        if current_bytes != expected_bytes or current_mode != expected_mode:
            raise AssemblyError(
                f"Vibe manifest changed during assembly preparation: {manifest}"
            )


def path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _executable(path: Path) -> bool:
    return bool(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def snapshot_descriptor(path: Path) -> dict[str, object]:
    """Hash all bytes, path types, links, and executable file modes."""
    digest = hashlib.sha256()
    if path.is_file():
        data = path.read_bytes()
        digest.update(b"file\0")
        digest.update(b"1\0" if _executable(path) else b"0\0")
        digest.update(data)
        return {
            "kind": "file",
            "sha256": digest.hexdigest(),
        }
    if path.is_symlink() or not path.is_dir():
        raise AssemblyError(f"Assembly output is not a file or directory: {path}")
    for item in sorted(path.rglob("*"), key=lambda value: value.relative_to(path).as_posix()):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        if item.is_symlink():
            digest.update(b"link\0" + relative + b"\0" + os.fsencode(os.readlink(item)) + b"\0")
        elif item.is_file():
            data = item.read_bytes()
            digest.update(b"file\0" + relative + b"\0")
            digest.update(b"1\0" if _executable(item) else b"0\0")
            digest.update(str(len(data)).encode("ascii") + b"\0" + data)
        elif item.is_dir():
            digest.update(b"directory\0" + relative + b"\0")
        else:
            raise AssemblyError(f"Assembly output contains a special file: {item}")
    return {"kind": "directory", "sha256": digest.hexdigest()}


def _fsync_files(path: Path) -> None:
    files = [path] if path.is_file() and not path.is_symlink() else [
        item for item in path.rglob("*") if item.is_file() and not item.is_symlink()
    ]
    for item in files:
        with item.open("rb") as stream:
            os.fsync(stream.fileno())


def copy_snapshot(source: Path, destination: Path, kind: str) -> None:
    """Create a complete copy without ever consuming the source."""
    if kind == "file":
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    elif kind == "directory":
        shutil.copytree(source, destination, symlinks=True)
    else:
        raise AssemblyError(f"Unsupported assembly output kind: {kind}")
    _fsync_files(destination)


def durable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def directory_identity(path: Path) -> tuple[int, int]:
    current = path.lstat()
    if not stat.S_ISDIR(current.st_mode):
        raise AssemblyError(f"Assembly path is not a plain directory: {path}")
    return current.st_dev, current.st_ino


def clear_directory(handle: int) -> None:
    """Delete only entries reached through the retained directory handle."""
    for name in os.listdir(handle):
        entry = os.stat(name, dir_fd=handle, follow_symlinks=False)
        if stat.S_ISDIR(entry.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=handle)
            try:
                opened = os.fstat(child)
                if (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino):
                    raise AssemblyError("Assembly cleanup directory changed while opening")
                clear_directory(child)
            finally:
                os.close(child)
            # A replacement containing anything cannot be removed by rmdir.
            os.rmdir(name, dir_fd=handle)
        else:
            # unlink removes a link itself and never follows its target.
            os.unlink(name, dir_fd=handle)


class AcquiredDirectory:
    """An invocation-owned directory; saved markers never grant ownership."""

    def __init__(self, path: Path):
        self.path = path
        self.identity = directory_identity(path)
        self.handle = None
        if SAFE_DIRECTORY_CLEANUP:
            self.handle = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            opened = os.fstat(self.handle)
            if (opened.st_dev, opened.st_ino) != self.identity:
                self.close()
                raise AssemblyError(f"Assembly directory changed while opening; preserving {path}")

    def require_current(self) -> None:
        try:
            current = directory_identity(self.path)
        except (OSError, AssemblyError):
            current = None
        if current != self.identity:
            raise AssemblyError(
                f"Assembly directory ownership changed at {self.path}; replacement preserved"
            )

    def close(self) -> None:
        if self.handle is not None:
            os.close(self.handle)
            self.handle = None

    def remove_empty(self) -> None:
        self.require_current()
        # Never recursively delete a lock or an occupant of the acquired name.
        self.path.rmdir()

    def cleanup(self) -> None:
        if self.handle is None:
            raise AssemblyError("handle-anchored cleanup is unavailable on this platform")
        clear_directory(self.handle)
        self.remove_empty()

    def marker(self, name: str, data: bytes | None = None) -> bytes:
        """Read/write a marker inside the still-open transaction."""
        self.require_current()
        if self.handle is None:
            path = self.path / name
            if data is None:
                return regular_bytes(path)
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return data
        flags = os.O_RDONLY if data is None else os.O_WRONLY | os.O_CREAT | os.O_EXCL
        handle = os.open(name, flags | os.O_NOFOLLOW, 0o600, dir_fd=self.handle)
        with os.fdopen(handle, "rb" if data is None else "wb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise AssemblyError(f"Assembly marker is not a regular file: {self.path / name}")
            if data is None:
                return stream.read()
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return data


def validate_state(data: object, expected_destinations: tuple[Path, ...],
                   transaction_id: str | None = None) -> dict[str, object]:
    """Accept only this assembler's exact schema and destination mapping."""
    if not isinstance(data, dict) or set(data) != {
            "assembler", "schema", "transaction_id", "destinations"}:
        raise AssemblyError("Assembly transaction marker has an unknown schema")
    if data["assembler"] != ASSEMBLER or data["schema"] != TRANSACTION_SCHEMA:
        raise AssemblyError("Assembly transaction marker is not owned by this assembler")
    identifier = data["transaction_id"]
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
        raise AssemblyError("Assembly transaction identifier is invalid")
    if transaction_id is not None and identifier != transaction_id:
        raise AssemblyError("Assembly transaction marker does not match its path")
    entries = data["destinations"]
    if not isinstance(entries, list) or len(entries) != len(expected_destinations):
        raise AssemblyError("Assembly transaction destination map is incomplete")
    keys = {"destination", "existed", "old", "replacement"}
    for entry, expected in zip(entries, expected_destinations):
        if not isinstance(entry, dict) or set(entry) != keys:
            raise AssemblyError("Assembly transaction destination entry is invalid")
        if entry["destination"] != str(expected):
            raise AssemblyError("Assembly transaction destination map does not match this repository")
        if not isinstance(entry["existed"], bool):
            raise AssemblyError("Assembly transaction destination state is invalid")
        if entry["existed"] != (entry["old"] is not None):
            raise AssemblyError("Assembly transaction prior-state map is invalid")
        descriptors = (entry["replacement"],) if entry["old"] is None else (
            entry["old"], entry["replacement"])
        if any(
            not isinstance(value, dict)
            or set(value) != {"kind", "sha256"}
            or value["kind"] not in {"file", "directory"}
            or not isinstance(value["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
            for value in descriptors
        ):
            raise AssemblyError("Assembly transaction snapshot identity is invalid")
    return data


def read_state(transaction: AcquiredDirectory, expected_destinations: tuple[Path, ...],
               name: str = STATE_NAME) -> dict[str, object]:
    try:
        data = json.loads(transaction.marker(name))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AssemblyError(f"Assembly transaction marker cannot be read: {transaction.path / name}") from error
    return validate_state(
        data, expected_destinations, transaction.path.name.removeprefix(TRANSACTION_PREFIX)
    )


def _state_bytes(state: dict[str, object]) -> bytes:
    return (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _warn(message: str) -> None:
    try:
        sys.stderr.write(f"Warning: {message}\n")
    except BaseException:
        pass


def _matches(path: Path, descriptor: dict[str, object] | None) -> bool:
    if descriptor is None:
        return not path_present(path)
    if not path_present(path):
        return False
    try:
        return snapshot_descriptor(path) == descriptor
    except (OSError, AssemblyError):
        return False


def backups_complete(transaction: AcquiredDirectory, state: dict[str, object],
                     expected_destinations: tuple[Path, ...]) -> bool:
    """Verify the retained map and every old snapshot before claiming recovery."""
    try:
        if read_state(transaction, expected_destinations) != state:
            return False
        return all(
            not entry["existed"]
            or _matches(transaction.path / f"backup/output-{index}", entry["old"])
            for index, entry in enumerate(state["destinations"])
        )
    except BaseException:
        return False


def commit_complete(transaction: AcquiredDirectory, state: dict[str, object],
                    expected_destinations: tuple[Path, ...]) -> bool:
    try:
        return (
            read_state(transaction, expected_destinations, COMMIT_NAME) == state
            and read_state(transaction, expected_destinations) == state
            and all(_matches(Path(entry["destination"]), entry["replacement"])
                    for entry in state["destinations"])
        )
    except BaseException:
        return False


def rollback_outputs(transaction: AcquiredDirectory, entries: list[dict[str, object]]) -> None:
    """Infer changed destinations from retained paths and restore immutable copies."""
    transaction.require_current()
    root = transaction.path
    restores = {}
    for index, entry in enumerate(entries):
        destination = Path(entry["destination"])
        changed = path_present(root / f"displaced/output-{index}") or not path_present(
            root / f"new/output-{index}"
        )
        if entry["existed"] and changed and not _matches(destination, entry["old"]):
            restore = root / f"restore/output-{index}"
            copy_snapshot(root / f"backup/output-{index}", restore, entry["old"]["kind"])
            if snapshot_descriptor(restore) != entry["old"]:
                raise AssemblyError(f"Rollback copy is incomplete for {destination}")
            restores[index] = restore

    rollback_errors = []
    for index, entry in reversed(tuple(enumerate(entries))):
        destination = Path(entry["destination"])
        changed = path_present(root / f"displaced/output-{index}") or not path_present(
            root / f"new/output-{index}"
        )
        if not changed or _matches(destination, entry["old"]):
            continue
        try:
            transaction.require_current()
            displaced = root / f"rollback-displaced/output-{index}"
            displaced.parent.mkdir(parents=True, exist_ok=True)
            if path_present(destination):
                os.replace(destination, displaced)
            if entry["existed"]:
                os.replace(restores[index], destination)
        except BaseException as error:
            rollback_errors.append(error)
    if rollback_errors:
        raise rollback_errors[0]


def switch_outputs(transaction: AcquiredDirectory, lock: AcquiredDirectory,
                   state: dict[str, object], destinations: tuple[Path, ...]) -> None:
    """Install the set; only a validated marker plus coherent outputs commits it."""
    entries = state["destinations"]
    try:
        for index, entry in enumerate(entries):
            lock.require_current()
            transaction.require_current()
            destination = Path(entry["destination"])
            if not _matches(destination, entry["old"]):
                raise AssemblyError(f"Assembly destination changed during preparation: {destination}")
            if entry["old"] == entry["replacement"]:
                continue
            displaced = transaction.path / f"displaced/output-{index}"
            displaced.parent.mkdir(parents=True, exist_ok=True)
            if entry["existed"]:
                os.replace(destination, displaced)
            os.replace(transaction.path / f"new/output-{index}", destination)
        lock.require_current()
        if not all(_matches(Path(entry["destination"]), entry["replacement"]) for entry in entries):
            raise AssemblyError("Assembled outputs are not coherent")
        transaction.marker(COMMIT_NAME, _state_bytes(state))
        if not commit_complete(transaction, state, destinations):
            raise AssemblyError("Assembly commit marker or replacement set is incomplete")
    except BaseException as replacement_error:
        if commit_complete(transaction, state, destinations):
            return  # The marker completed before a signal/exception was delivered.
        try:
            lock.require_current()
            transaction.require_current()
            if not backups_complete(transaction, state, destinations):
                raise AssemblyError("Assembly rollback backups or map are incomplete")
            rollback_outputs(transaction, entries)
        except BaseException as rollback_error:
            try:
                transaction.require_current()
            except (OSError, AssemblyError) as ownership_error:
                detail = (
                    f"{ownership_error}; the original transaction's current location is unverified; "
                    "no transaction cleanup was attempted"
                )
            else:
                retained = (
                    "the complete immutable old output set and exact destination map remain"
                    if backups_complete(transaction, state, destinations)
                    else "unverified recovery state remains"
                )
                detail = f"{retained} at {transaction.path}"
            raise RecoveryRequired(
                f"Assembly replacement and rollback both failed; {detail}; "
                f"{rollback_error}"
            ) from replacement_error
        raise


def assemble(loop_source: Path, revision: str | None = None,
             target: Path | None = None) -> Path:
    # Reserve before reading any output. Cooperating runs cannot prepare stale
    # manifests or enter replacement together. This does not sandbox arbitrary
    # same-user changes to the repository's live output paths.
    lock_path = Path(ROOT).absolute() / LOCK_NAME
    try:
        lock_path.mkdir(mode=0o700)
    except FileExistsError as error:
        raise AssemblyError(
            f"Another resource assembly owns the lock path {lock_path}; no outputs were touched"
        ) from error
    lock = None
    try:
        lock = AcquiredDirectory(lock_path)
        return assemble_locked(loop_source, revision, target, lock)
    finally:
        if lock is not None:
            try:
                lock.remove_empty()
            except BaseException as error:
                _warn(f"assembly lock was preserved at {lock_path}: {error}")
            finally:
                lock.close()
        else:
            _warn(f"assembly lock could not be opened; preserving {lock_path}")


def assemble_locked(loop_source: Path, revision: str | None,
                    target: Path | None, lock: AcquiredDirectory) -> Path:
    try:
        authority = loop_integrity.authority_metadata()
    except loop_integrity.LoopIntegrityError as error:
        raise AssemblyError(str(error)) from error
    if revision is not None and revision != authority["source_revision"]:
        raise AssemblyError(
            "Requested Loop revision conflicts with Vibe's reviewed authoritative source revision"
        )
    source = Path(loop_source).resolve(strict=True)
    target = Path(target) if target else ROOT / "plugins/ora-vibe-coder/resources/programming-loop"
    target = target.absolute()
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise AssemblyError(f"Generated resource target is not a plain directory: {target}")

    try:
        payload, modes, source_tree = loop_integrity.read_snapshot(source)
    except loop_integrity.LoopIntegrityError as error:
        raise AssemblyError(str(error)) from error
    if source_tree != authority["source_tree"]:
        raise AssemblyError(
            f"Programming Loop snapshot Git tree {source_tree} does not match reviewed "
            f"source tree {authority['source_tree']}; no resources were replaced"
        )
    version = payload["VERSION"].decode("utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise AssemblyError("Loop VERSION must identify a release, such as 1.0.0")
    _, manifest_outputs, manifest_originals = vibe_manifest_outputs()
    identity = {
        **authority,
        "component": "programming-loop",
        "source": "programming-loop",
        "version": version,
        "files": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(payload.items())
        },
    }

    lock.require_current()
    target.parent.mkdir(parents=True, exist_ok=True)
    destinations = tuple((*manifest_outputs.keys(), target))
    transaction_path = Path(tempfile.mkdtemp(prefix=TRANSACTION_PREFIX, dir=ROOT))
    transaction = None
    committed = False
    recovery_required = False
    try:
        transaction = AcquiredDirectory(transaction_path)
        new_root = transaction.path / "new"
        staged_manifests = []
        for index, (manifest, replacement) in enumerate(manifest_outputs.items()):
            transaction.require_current()
            staging = new_root / f"output-{index}"
            durable_write(staging, replacement)
            transaction.require_current()
            staging.chmod(manifest_originals[manifest][1])
            staged_manifests.append(staging)

        resource_index = len(staged_manifests)
        staged = new_root / f"output-{resource_index}"
        for name, data in payload.items():
            transaction.require_current()
            destination = staged / name
            durable_write(destination, data)
            transaction.require_current()
            destination.chmod(0o755 if modes[name] == "100755" else 0o644)
        transaction.require_current()
        durable_write(
            staged / "SOURCE.json",
            (json.dumps(identity, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        transaction.require_current()
        try:
            staged_payload, staged_modes, staged_tree = loop_integrity.read_snapshot(
                staged, allowed_extra={"SOURCE.json"}
            )
        except loop_integrity.LoopIntegrityError as error:
            raise AssemblyError(str(error)) from error
        if (staged_payload != payload or staged_modes != modes
                or staged_tree != authority["source_tree"]):
            raise AssemblyError("Staged Loop resources do not preserve the reviewed Git tree")

        entries = []
        kinds = ("file",) * len(staged_manifests) + ("directory",)
        for index, (destination, kind) in enumerate(zip(destinations, kinds)):
            transaction.require_current()
            staging = new_root / f"output-{index}"
            replacement = snapshot_descriptor(staging)
            existed = path_present(destination)
            old = snapshot_descriptor(destination) if existed else None
            backup_name = f"backup/output-{index}" if existed else None
            if existed:
                backup = transaction.path / backup_name
                copy_snapshot(destination, backup, kind)
                transaction.require_current()
                if snapshot_descriptor(destination) != old or snapshot_descriptor(backup) != old:
                    raise AssemblyError(f"Immutable assembly backup is incomplete for {destination}")
            entries.append({
                "destination": str(destination),
                "existed": existed,
                "old": old,
                "replacement": replacement,
            })
        state = {
            "assembler": ASSEMBLER,
            "schema": TRANSACTION_SCHEMA,
            "transaction_id": transaction.path.name.removeprefix(TRANSACTION_PREFIX),
            "destinations": entries,
        }
        transaction.marker(STATE_NAME, _state_bytes(state))
        if not backups_complete(transaction, state, destinations):
            raise AssemblyError("Assembly transaction backup set is incomplete before replacement")
        lock.require_current()
        require_prepared_manifests(manifest_originals)
        for entry in entries:
            destination = Path(entry["destination"])
            if not _matches(destination, entry["old"]):
                raise AssemblyError(
                    f"Assembly destination changed during preparation: {destination}"
                )

        try:
            switch_outputs(transaction, lock, state, destinations)
        except RecoveryRequired:
            recovery_required = True
            raise
        committed = True
        return target
    finally:
        if transaction is not None:
            try:
                if not recovery_required:
                    transaction.cleanup()
            except BaseException as error:
                outcome = "assembly committed coherently" if committed else "assembly did not commit"
                _warn(
                    f"{outcome}; isolated assembly state may remain at {transaction.path}: {error}. "
                    "Inspect this exact path manually; later runs leave it untouched."
                )
            finally:
                transaction.close()
        else:
            _warn(f"assembly transaction could not be opened; preserving {transaction_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop-source", required=True, type=Path)
    parser.add_argument(
        "--source-revision",
        help="Optional assertion; must equal the reviewed revision in ora_vibe_coder/loop_integrity.py",
    )
    args = parser.parse_args()
    print(assemble(args.loop_source, args.source_revision))
