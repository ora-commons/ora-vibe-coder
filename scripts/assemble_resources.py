#!/usr/bin/env python3
"""Assemble Vibe's generated component contexts from explicit component roots.

A maintainer runs this by hand inside a Git checkout, so Git is the recovery
mechanism: every destination is validated against its reviewed source tree
before anything is replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ora_vibe_coder import loop_integrity


RESOURCE_PATHS = loop_integrity.VENDORED_PATHS
VIBE_MANIFEST_FOLDERS = (".codex-plugin", ".claude-plugin")


class AssemblyError(ValueError):
    pass


def regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise AssemblyError(f"Missing or non-regular Loop resource: {path}")
    data = path.read_bytes()
    if not data.strip():
        raise AssemblyError(f"Empty Loop resource: {path}")
    return data


def vibe_manifest_outputs() -> tuple[str, dict[Path, bytes]]:
    """Prepare both native manifests from Vibe's neutral version source."""
    plugin = ROOT / "plugins/ora-vibe-coder"
    version = regular_bytes(plugin / "VERSION").decode("utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise AssemblyError("Vibe VERSION must identify a release, such as 1.0.0")
    outputs = {}
    for folder in VIBE_MANIFEST_FOLDERS:
        manifest = plugin / folder / "plugin.json"
        data = json.loads(regular_bytes(manifest))
        data["version"] = version
        outputs[manifest] = (
            json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
    return version, outputs


def path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _replace_output(staged: Path, destination: Path) -> None:
    """Swap one staged output into place by rename; the displaced copy goes.

    A swap that fails midway leaves the old copy in the displaced folder and
    the recovery route is Git, per the module docstring."""
    if path_present(destination):
        displaced = Path(tempfile.mkdtemp(prefix=".assembly-displaced-", dir=destination.parent))
        displaced.rmdir()
        os.replace(destination, displaced)
        os.replace(staged, destination)
        if displaced.is_dir() and not displaced.is_symlink():
            shutil.rmtree(displaced, ignore_errors=True)
        else:
            displaced.unlink(missing_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, destination)


def assemble(loop_source: Path | None = None, revision: str | None = None,
             target: Path | None = None, boost_source: Path | None = None,
             boost_target: Path | None = None) -> Path:
    try:
        authority = loop_integrity.authority_metadata()
    except loop_integrity.LoopIntegrityError as error:
        raise AssemblyError(str(error)) from error
    if revision is not None and revision != authority["source_revision"]:
        raise AssemblyError(
            "Requested Loop revision conflicts with Vibe's reviewed authoritative source revision"
        )
    source = Path(loop_source if loop_source is not None
                  else ROOT / authority["vendored_snapshot"]).resolve(strict=True)
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

    try:
        boost_authority = loop_integrity.boost_authority_metadata()
    except loop_integrity.LoopIntegrityError as error:
        raise AssemblyError(str(error)) from error
    boost_root = Path(boost_source if boost_source is not None
                      else ROOT / boost_authority["vendored_snapshot"]).resolve(strict=True)
    boost_target = Path(boost_target) if boost_target else ROOT / "plugins/ora-vibe-coder/resources/ora-ai-boost"
    boost_target = boost_target.absolute()
    if boost_target.is_symlink() or (boost_target.exists() and not boost_target.is_dir()):
        raise AssemblyError(f"Generated resource target is not a plain directory: {boost_target}")
    try:
        boost_payload, boost_modes, boost_tree = loop_integrity.read_boost_snapshot(boost_root)
    except loop_integrity.LoopIntegrityError as error:
        raise AssemblyError(str(error)) from error
    if boost_tree != boost_authority["source_tree"]:
        raise AssemblyError(
            f"Boost snapshot Git tree {boost_tree} does not match reviewed "
            f"source tree {boost_authority['source_tree']}; no resources were replaced"
        )
    boost_match = re.search(rb'VERSION\s*=\s*"([^"]+)"', boost_payload["ora_review/__init__.py"])
    boost_version = boost_match.group(1).decode("utf-8") if boost_match else ""
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", boost_version):
        raise AssemblyError("Boost VERSION must identify a release, such as 1.0.0")

    _, manifest_outputs = vibe_manifest_outputs()
    identity = {
        **authority,
        # The bundled Loop's own installer (1.3.0) accepts a vendored source
        # only under its renamed component identity, which names the entry it
        # writes (skills/ora-programming-loop).
        "component": "ora-programming-loop",
        "source": "ora-programming-loop",
        "version": version,
        "files": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(payload.items())
        },
    }
    boost_identity = {
        **boost_authority,
        "component": "ora-adversarial-review",
        "source": "ora-adversarial-review",
        "version": boost_version,
        "files": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(boost_payload.items())
        },
    }

    staging_root = Path(tempfile.mkdtemp(prefix=".assembly-", dir=ROOT))
    try:
        staged_loop = staging_root / "programming-loop"
        staged_boost = staging_root / "ora-ai-boost"

        def stage_component(staged: Path, files: dict[str, bytes], file_modes: dict[str, str],
                            source_identity: dict[str, object]):
            staged.mkdir()
            for name, data in files.items():
                destination = staged / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                destination.chmod(0o755 if file_modes[name] == "100755" else 0o644)
            (staged / "SOURCE.json").write_text(
                json.dumps(source_identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        stage_component(staged_loop, payload, modes, identity)
        stage_component(staged_boost, boost_payload, boost_modes, boost_identity)
        outputs = []
        for manifest, replacement in manifest_outputs.items():
            staged_manifest = staging_root / f"manifest-{manifest.parent.name}.json"
            staged_manifest.write_bytes(replacement)
            outputs.append((staged_manifest, manifest))
        outputs.append((staged_loop, target))
        outputs.append((staged_boost, boost_target))
        for staged, destination in outputs:
            _replace_output(Path(staged), Path(destination))
        return target
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--loop-source", type=Path,
        help="Optional Loop component root; defaults to the repository's vendored snapshot",
    )
    parser.add_argument(
        "--source-revision",
        help="Optional assertion; must equal the reviewed revision in ora_vibe_coder/loop_integrity.py",
    )
    parser.add_argument(
        "--boost-source", type=Path,
        help="Optional Boost component root; defaults to the repository's vendored snapshot",
    )
    args = parser.parse_args()
    print(assemble(args.loop_source, args.source_revision, boost_source=args.boost_source))
