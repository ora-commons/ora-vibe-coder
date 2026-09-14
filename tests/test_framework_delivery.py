import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from ora_vibe_coder import handoff, loop_integrity
from ora_vibe_coder.handoff import HOSTS, LOOP_FILES, framework_text
from ora_vibe_coder.installer import SKILL_HOMES, install
from ora_vibe_coder.project import ProjectError


PACKAGE = Path(__file__).resolve().parents[1] / "plugins" / "ora-vibe-coder"
ASSEMBLY_SPEC = importlib.util.spec_from_file_location(
    "vibe_assemble_resources", PACKAGE.parents[1] / "scripts" / "assemble_resources.py"
)
assembly = importlib.util.module_from_spec(ASSEMBLY_SPEC)
ASSEMBLY_SPEC.loader.exec_module(assembly)
STAGES = {
    "specification": "ora-specification",
    "planning": "ora-planning",
    "programming": "ora-programming",
    "verification": "ora-verification",
    "guided": "ora-vibe-coder",
}
PACKAGE_FILES = set(assembly.RESOURCE_PATHS)


def markdown_links(text):
    return re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)


class FrameworkDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.shared_path = PACKAGE / "references" / "shared-contract.md"
        self.shared = self.shared_path.read_text(encoding="utf-8")
        self.roles_path = PACKAGE / "references" / "role-and-assignment.md"
        self.roles = self.roles_path.read_text(encoding="utf-8")
        self.bodies = {
            stage: (PACKAGE / "frameworks" / f"{name}.md").read_text(encoding="utf-8")
            for stage, name in STAGES.items()
        }

    def assembly_fixture(self, directory):
        source = PACKAGE.parents[1] / "components" / "programming-loop"
        packaged = PACKAGE / "resources" / "programming-loop"
        private_root = Path(directory) / "repo"
        plugin = private_root / "plugins/ora-vibe-coder"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        manifests = []
        replacements = {}
        for folder in assembly.VIBE_MANIFEST_FOLDERS:
            manifest = plugin / folder / "plugin.json"
            data = json.loads((PACKAGE / folder / "plugin.json").read_text())
            data["version"] = "0.1.0"
            manifest.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifests.append(manifest)
            data["version"] = "9.9.9"
            replacements[manifest] = (
                json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
        target = plugin / "resources/programming-loop"
        target.parent.mkdir()
        shutil.copytree(packaged, target)
        (target / "README.md").write_bytes(b"previous generated resources\n")
        destinations = (*manifests, target)
        before = {path: assembly.snapshot_descriptor(path) for path in destinations}
        return {
            "source": source,
            "packaged": packaged,
            "root": private_root,
            "control_parent": private_root,
            "manifests": manifests,
            "target": target,
            "destinations": destinations,
            "before": before,
            "replacements": replacements,
        }

    def assert_fixture_before(self, fixture):
        self.assertEqual(
            {path: assembly.snapshot_descriptor(path) for path in fixture["destinations"]},
            fixture["before"],
        )

    def assert_fixture_replaced(self, fixture):
        for manifest in fixture["manifests"]:
            self.assertEqual(manifest.read_bytes(), fixture["replacements"][manifest])
        self.assertEqual(
            assembly.snapshot_descriptor(fixture["target"]),
            assembly.snapshot_descriptor(fixture["packaged"]),
        )

    def test_generated_loop_resources_are_exact_identified_component_inputs(self):
        root = PACKAGE / "resources" / "programming-loop"
        source = PACKAGE.parents[1] / "components" / "programming-loop"
        authority = loop_integrity.authority_metadata()
        actual_vendored = {
            str(path.relative_to(source))
            for path in source.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        self.assertEqual(actual_vendored, set(assembly.VENDORED_PATHS))
        source_files, source_modes, source_tree = loop_integrity.read_snapshot(source)
        self.assertEqual(source_tree, authority["source_tree"])
        packaged_files, packaged_modes, packaged_tree = loop_integrity.read_snapshot(
            root, allowed_extra={"SOURCE.json"}
        )
        self.assertEqual(packaged_files, source_files)
        self.assertEqual(packaged_modes, source_modes)
        self.assertEqual(packaged_tree, source_tree)
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            conflicting = temporary / "conflicting"
            with self.assertRaisesRegex(assembly.AssemblyError, "conflicts"):
                assembly.assemble(source, revision="0" * 40, target=conflicting)
            self.assertFalse(conflicting.exists())
            generated = assembly.assemble(source, target=temporary / "resources")
            self.assertEqual(
                {
                    path.relative_to(generated): path.read_bytes()
                    for path in generated.rglob("*") if path.is_file()
                },
                {
                    path.relative_to(root): path.read_bytes()
                    for path in root.rglob("*") if path.is_file()
                },
            )
        identity = json.loads((root / "SOURCE.json").read_text())
        self.assertEqual(
            {name: identity.get(name) for name in authority},
            authority,
        )
        self.assertEqual(identity["component"], "programming-loop")
        self.assertEqual(identity["source"], "programming-loop")
        self.assertEqual(identity["version"], (source / "VERSION").read_text().strip())
        self.assertEqual(set(identity["files"]), PACKAGE_FILES)
        self.assertTrue(LOOP_FILES < PACKAGE_FILES)
        actual = {
            str(path.relative_to(root))
            for path in root.rglob("*") if path.is_file()
        }
        self.assertEqual(actual, PACKAGE_FILES | {"SOURCE.json"})
        for name, expected in identity["files"].items():
            with self.subTest(resource=name):
                self.assertEqual((root / name).read_bytes(), (source / name).read_bytes())
                self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), expected)
        for folder in (".codex-plugin", ".claude-plugin"):
            self.assertEqual(
                json.loads((PACKAGE / folder / "plugin.json").read_text())["version"],
                (PACKAGE / "VERSION").read_text().strip(),
            )

    def test_divergent_vendored_snapshot_is_rejected_before_replacement(self):
        source = PACKAGE.parents[1] / "components" / "programming-loop"
        root = PACKAGE / "resources" / "programming-loop"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            copied = temporary / "copied-source"
            target = temporary / "existing-resources"
            shutil.copytree(source, copied)
            shutil.copytree(root, target)
            before = {
                path.relative_to(target): path.read_bytes()
                for path in target.rglob("*") if path.is_file()
            }
            framework = copied / "frameworks/programming-loop.md"
            framework.write_bytes(framework.read_bytes() + b"\nmodified byte\n")
            with self.assertRaisesRegex(assembly.AssemblyError, "does not match reviewed"):
                assembly.assemble(copied, target=target)
            self.assertEqual(
                {
                    path.relative_to(target): path.read_bytes()
                    for path in target.rglob("*") if path.is_file()
                },
                before,
            )
            shutil.rmtree(copied)
            shutil.copytree(source, copied)
            mode_file = copied / "scripts/install.py"
            original_executable = bool(mode_file.stat().st_mode & 0o111)
            mode_file.chmod(0o755 if not original_executable else 0o644)
            if bool(mode_file.stat().st_mode & 0o111) != original_executable:
                with self.assertRaisesRegex(assembly.AssemblyError, "does not match reviewed"):
                    assembly.assemble(copied, target=target)
                self.assertEqual(
                    {
                        path.relative_to(target): path.read_bytes()
                        for path in target.rglob("*") if path.is_file()
                    },
                    before,
                )
            self.assertEqual(list(temporary.glob(".programming-loop-*")), [])

    def test_cache_and_unexpected_directory_content_cannot_validate_as_exact(self):
        source = PACKAGE.parents[1] / "components" / "programming-loop"
        root = PACKAGE / "resources" / "programming-loop"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            target = temporary / "existing-resources"
            shutil.copytree(root, target)
            before = {
                path.relative_to(target): path.read_bytes()
                for path in target.rglob("*") if path.is_file()
            }
            cases = (
                ("cache-file", lambda copied: (
                    (copied / "__pycache__").mkdir(),
                    (copied / "__pycache__/cached.pyc").write_bytes(b"cache"),
                ), "exact 17 files"),
                ("empty-cache-directory", lambda copied: (
                    (copied / "__pycache__").mkdir(),
                ), "unexpected directories"),
                ("cache-symlink", lambda copied: (
                    (copied / "__pycache__").mkdir(),
                    (copied / "__pycache__/alias").symlink_to(copied / "VERSION"),
                ), "symbolic link"),
            )
            for name, mutate, message in cases:
                with self.subTest(snapshot_item=name):
                    copied = temporary / name
                    shutil.copytree(source, copied)
                    mutate(copied)
                    with self.assertRaisesRegex(assembly.AssemblyError, message):
                        assembly.assemble(copied, target=target)
                    self.assertEqual(
                        {
                            path.relative_to(target): path.read_bytes()
                            for path in target.rglob("*") if path.is_file()
                        },
                        before,
                    )
            copied_resources = temporary / "handoff-resources"
            shutil.copytree(root, copied_resources)
            (copied_resources / "__pycache__").mkdir()
            with mock.patch.object(handoff, "LOOP", copied_resources):
                with self.assertRaisesRegex(ProjectError, "conflicting provenance"):
                    handoff.loop_resources("programming", "Codex")
            self.assertEqual(list(temporary.glob(".programming-loop-*")), [])

    def test_assembly_contention_precedes_output_reads_and_preserves_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.assembly_fixture(directory)
            lock = fixture["root"] / assembly.LOCK_NAME
            lock.mkdir()
            sentinel = lock / "not-owned.txt"
            sentinel.write_bytes(b"leave me")
            leftover = fixture["root"] / (assembly.TRANSACTION_PREFIX + "prior")
            leftover.mkdir()
            (leftover / "not-owned.txt").write_bytes(b"prior state")
            with mock.patch.object(assembly, "ROOT", fixture["root"]), \
                    mock.patch.object(assembly, "vibe_manifest_outputs") as read_outputs:
                with self.assertRaisesRegex(assembly.AssemblyError, "no outputs were touched"):
                    assembly.assemble(fixture["source"], target=fixture["target"])
            read_outputs.assert_not_called()
            self.assert_fixture_before(fixture)
            self.assertEqual(sentinel.read_bytes(), b"leave me")
            self.assertEqual((leftover / "not-owned.txt").read_bytes(), b"prior state")

    def test_concurrent_cooperating_run_is_blocked_before_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.assembly_fixture(directory)
            preparing = threading.Event()
            resume = threading.Event()
            errors = []
            real_prepare = assembly.vibe_manifest_outputs

            def pause_preparation():
                preparing.set()
                if not resume.wait(10):
                    raise AssertionError("test did not resume assembler")
                return real_prepare()

            def first_run():
                try:
                    assembly.assemble(fixture["source"], target=fixture["target"])
                except BaseException as error:
                    errors.append(error)

            with mock.patch.object(assembly, "ROOT", fixture["root"]), \
                    mock.patch.object(assembly, "vibe_manifest_outputs", side_effect=pause_preparation) as prepare:
                worker = threading.Thread(target=first_run)
                worker.start()
                try:
                    self.assertTrue(preparing.wait(10))
                    with self.assertRaisesRegex(assembly.AssemblyError, "no outputs were touched"):
                        assembly.assemble(fixture["source"], target=fixture["target"])
                    self.assertEqual(prepare.call_count, 1)
                    self.assert_fixture_before(fixture)
                finally:
                    resume.set()
                    worker.join(10)
                self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assert_fixture_replaced(fixture)
            self.assertEqual(list(fixture["root"].glob(".programming-loop-*")), [])

    def test_lock_replacement_is_preserved_during_preparation_and_release(self):
        for boundary in ("preparation", "release"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                fixture = self.assembly_fixture(directory)
                lock = fixture["root"] / assembly.LOCK_NAME
                original = fixture["root"] / "displaced-lock"
                sentinel = lock / "not-owned.txt"
                real_prepare = assembly.vibe_manifest_outputs
                real_rmdir = Path.rmdir
                injected = []

                def replace_lock():
                    lock.rename(original)
                    lock.mkdir()
                    sentinel.write_bytes(b"replacement lock")
                    injected.append(True)

                def prepare():
                    prepared = real_prepare()
                    if boundary == "preparation":
                        replace_lock()
                    return prepared

                def rmdir(path):
                    # Inject after the last identity check, at the real delete.
                    if path == lock and boundary == "release":
                        replace_lock()
                    return real_rmdir(path)

                errors = io.StringIO()
                with mock.patch.object(assembly, "ROOT", fixture["root"]), \
                        mock.patch.object(assembly, "vibe_manifest_outputs", side_effect=prepare), \
                        mock.patch.object(Path, "rmdir", autospec=True, side_effect=rmdir), \
                        mock.patch.object(assembly.sys, "stderr", errors):
                    if boundary == "preparation":
                        with self.assertRaisesRegex(assembly.AssemblyError, "ownership changed"):
                            assembly.assemble(fixture["source"], target=fixture["target"])
                    else:
                        assembly.assemble(fixture["source"], target=fixture["target"])
                self.assertEqual(injected, [True])
                self.assertEqual(sentinel.read_bytes(), b"replacement lock")
                self.assertEqual(set(lock.iterdir()), {sentinel})
                self.assertEqual(list(original.iterdir()), [])
                self.assertIn(str(lock), errors.getvalue())
                if boundary == "preparation":
                    self.assert_fixture_before(fixture)
                else:
                    self.assert_fixture_replaced(fixture)

    def test_manifest_edit_during_preparation_is_preserved_before_any_output_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.assembly_fixture(directory)
            edited = fixture["manifests"][1]
            user_data = json.loads(edited.read_text(encoding="utf-8"))
            user_data["user-note"] = "preserve this concurrent edit"
            user_bytes = (json.dumps(user_data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            real_backups_complete = assembly.backups_complete

            def edit_after_backups(transaction, state, destinations):
                complete = real_backups_complete(transaction, state, destinations)
                edited.write_bytes(user_bytes)
                return complete

            with mock.patch.object(assembly, "ROOT", fixture["root"]), \
                    mock.patch.object(assembly, "backups_complete", side_effect=edit_after_backups):
                with self.assertRaisesRegex(assembly.AssemblyError, "manifest changed during assembly preparation"):
                    assembly.assemble(fixture["source"], target=fixture["target"])
            self.assertEqual(edited.read_bytes(), user_bytes)
            for destination in (*fixture["manifests"][:1], fixture["target"]):
                self.assertEqual(assembly.snapshot_descriptor(destination), fixture["before"][destination])
            self.assertEqual(list(fixture["root"].glob(".programming-loop-*")), [])

    def test_each_destination_and_commit_switch_boundary_is_atomic(self):
        boundaries = [
            (operation, index, timing)
            for operation in ("displace", "install")
            for index in range(3)
            for timing in ("before", "after")
        ] + [("commit", None, timing) for timing in ("before", "after")]
        for operation, index, timing in boundaries:
            with self.subTest(operation=operation, destination=index, timing=timing), \
                    tempfile.TemporaryDirectory() as directory:
                fixture = self.assembly_fixture(directory)
                real_replace = assembly.os.replace
                real_marker = assembly.AcquiredDirectory.marker
                injected = []

                def failing_replace(old, new):
                    old_path, new_path = Path(old), Path(new)
                    match = (
                        operation == "displace" and old_path == fixture["destinations"][index]
                        and new_path.parent.name == "displaced"
                    ) or (
                        operation == "install" and new_path == fixture["destinations"][index]
                        and old_path.parent.name == "new"
                    )
                    if match and not injected:
                        injected.append(True)
                        if timing == "after":
                            real_replace(old, new)
                        raise OSError(f"forced {timing} {operation} failure")
                    return real_replace(old, new)

                def failing_marker(transaction, name, data=None):
                    if operation == "commit" and name == assembly.COMMIT_NAME and data is not None:
                        injected.append(True)
                        if timing == "after":
                            real_marker(transaction, name, data)
                        raise OSError(f"forced {timing} commit failure")
                    return real_marker(transaction, name, data)

                with mock.patch.object(assembly, "ROOT", fixture["root"]), \
                        mock.patch.object(assembly.os, "replace", side_effect=failing_replace), \
                        mock.patch.object(assembly.AcquiredDirectory, "marker", autospec=True, side_effect=failing_marker):
                    if operation == "commit" and timing == "after":
                        assembly.assemble(fixture["source"], target=fixture["target"])
                    else:
                        with self.assertRaisesRegex(OSError, f"forced {timing} {operation}"):
                            assembly.assemble(fixture["source"], target=fixture["target"])
                self.assertEqual(injected, [True])
                if operation == "commit" and timing == "after":
                    self.assert_fixture_replaced(fixture)
                else:
                    self.assert_fixture_before(fixture)
                self.assertEqual(list(fixture["root"].glob(".programming-loop-*")), [])

    def test_rollback_failure_retains_complete_mapped_old_set(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.assembly_fixture(directory)
            real_replace = assembly.os.replace

            def fail_install_then_restore(old, new):
                old_path, new_path = Path(old), Path(new)
                if new_path == fixture["manifests"][0] and old_path.parent.name in {"new", "restore"}:
                    raise OSError("forced install or rollback failure")
                return real_replace(old, new)

            with mock.patch.object(assembly, "ROOT", fixture["root"]), \
                    mock.patch.object(assembly.os, "replace", side_effect=fail_install_then_restore):
                with self.assertRaisesRegex(
                        assembly.RecoveryRequired, "complete immutable old output set and exact destination map remain") as raised:
                    assembly.assemble(fixture["source"], target=fixture["target"])
            transactions = list(fixture["root"].glob(assembly.TRANSACTION_PREFIX + "*"))
            self.assertEqual(len(transactions), 1)
            transaction = transactions[0]
            self.assertIn(str(transaction), str(raised.exception))
            state = json.loads((transaction / assembly.STATE_NAME).read_bytes())
            assembly.validate_state(state, fixture["destinations"], transaction.name.removeprefix(assembly.TRANSACTION_PREFIX))
            for index, entry in enumerate(state["destinations"]):
                self.assertTrue(entry["existed"])
                self.assertEqual(
                    assembly.snapshot_descriptor(transaction / f"backup/output-{index}"),
                    fixture["before"][Path(entry["destination"])],
                )
            self.assertFalse((fixture["root"] / assembly.LOCK_NAME).exists())

    def test_replaced_transaction_before_commit_preserves_backups_without_claiming_their_location(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.assembly_fixture(directory)
            preserved = fixture["root"] / "moved-original"
            real_marker = assembly.AcquiredDirectory.marker
            replaced = []

            def replace_before_commit(transaction, name, data=None):
                if name == assembly.COMMIT_NAME and data is not None:
                    transaction.path.rename(preserved)
                    transaction.path.mkdir()
                    (transaction.path / "not-owned.txt").write_bytes(b"replacement")
                    replaced.append(transaction.path)
                return real_marker(transaction, name, data)

            with mock.patch.object(assembly, "ROOT", fixture["root"]), \
                    mock.patch.object(assembly.AcquiredDirectory, "marker", autospec=True,
                                      side_effect=replace_before_commit):
                with self.assertRaisesRegex(
                        assembly.RecoveryRequired, "original transaction's current location is unverified") as raised:
                    assembly.assemble(fixture["source"], target=fixture["target"])
            self.assertEqual(len(replaced), 1)
            self.assertIn(str(replaced[0]), str(raised.exception))
            self.assertNotIn(f"recovery state remains at {replaced[0]}", str(raised.exception))
            self.assertEqual((replaced[0] / "not-owned.txt").read_bytes(), b"replacement")
            self.assert_fixture_replaced(fixture)
            self.assertFalse((preserved / assembly.COMMIT_NAME).exists())
            state = json.loads((preserved / assembly.STATE_NAME).read_bytes())
            assembly.validate_state(state, fixture["destinations"])
            for index, destination in enumerate(fixture["destinations"]):
                self.assertEqual(
                    assembly.snapshot_descriptor(preserved / f"backup/output-{index}"),
                    fixture["before"][destination],
                )
            self.assertFalse((fixture["root"] / assembly.LOCK_NAME).exists())

    def test_postcommit_cleanup_uses_open_handle_and_never_adopts_leftovers(self):
        for failure in ("before-traversal", "final-rmdir", "partial-children", "unsupported-platform"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                fixture = self.assembly_fixture(directory)
                control = fixture["root"]
                preserved = control / "preserved-original"
                external = control / "outside-transaction.txt"
                external.write_bytes(b"do not follow this link")
                real_clear = assembly.clear_directory
                real_rmdir = Path.rmdir
                real_cleanup = assembly.AcquiredDirectory.cleanup
                transaction_paths = []
                injected = []

                def replace_transaction(path):
                    path.rename(preserved)
                    path.mkdir()
                    (path / "not-owned.txt").write_bytes(b"replacement transaction")
                    injected.append(True)

                def clear(handle):
                    # This is the actual descriptor-anchored traversal entry,
                    # after all preparation, commit and identity validation.
                    if not injected and failure == "before-traversal":
                        replace_transaction(transaction_paths[0])
                    if not injected and failure == "partial-children":
                        (transaction_paths[0] / assembly.STATE_NAME).unlink()
                        injected.append(True)
                        raise OSError("forced partial cleanup")
                    return real_clear(handle)

                def rmdir(path):
                    if transaction_paths and path == transaction_paths[0] and failure == "final-rmdir":
                        replace_transaction(path)
                    return real_rmdir(path)

                def cleanup(transaction):
                    transaction_paths.append(transaction.path)
                    (transaction.path / "external-link").symlink_to(external)
                    return real_cleanup(transaction)

                errors = io.StringIO()
                supported = failure != "unsupported-platform" and assembly.SAFE_DIRECTORY_CLEANUP
                with mock.patch.object(assembly, "ROOT", fixture["root"]), \
                        mock.patch.object(assembly, "SAFE_DIRECTORY_CLEANUP", supported), \
                        mock.patch.object(assembly, "clear_directory", side_effect=clear), \
                        mock.patch.object(Path, "rmdir", autospec=True, side_effect=rmdir), \
                        mock.patch.object(assembly.AcquiredDirectory, "cleanup", autospec=True, side_effect=cleanup), \
                        mock.patch.object(assembly.sys, "stderr", errors):
                    self.assertEqual(assembly.assemble(fixture["source"], target=fixture["target"]), fixture["target"])
                transaction = transaction_paths[0]
                self.assert_fixture_replaced(fixture)
                self.assertIn("committed coherently", errors.getvalue())
                self.assertIn(str(transaction), errors.getvalue())
                self.assertIn("later runs leave it untouched", errors.getvalue())
                self.assertEqual(external.read_bytes(), b"do not follow this link")
                self.assertFalse((control / assembly.LOCK_NAME).exists())
                self.assertEqual(list(fixture["target"].parent.glob(".programming-loop-*")), [])
                if failure in {"before-traversal", "final-rmdir"}:
                    self.assertEqual((transaction / "not-owned.txt").read_bytes(), b"replacement transaction")
                    self.assertEqual(list(preserved.iterdir()), [])
                elif failure == "unsupported-platform":
                    self.assertIn("unavailable on this platform", errors.getvalue())
                prior = assembly.snapshot_descriptor(transaction)
                with mock.patch.object(assembly, "ROOT", fixture["root"]):
                    assembly.assemble(fixture["source"], target=fixture["target"])
                self.assert_fixture_replaced(fixture)
                self.assertEqual(assembly.snapshot_descriptor(transaction), prior)
                self.assertEqual(list(control.glob(assembly.TRANSACTION_PREFIX + "*")), [transaction])

    def test_native_entries_load_the_packaged_shared_role_and_canonical_sources(self):
        """Both native packages discover the same five loaders, not behavior copies."""
        codex = json.loads((PACKAGE / ".codex-plugin" / "plugin.json").read_text())
        claude = json.loads((PACKAGE / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(codex["name"], claude["name"])
        self.assertEqual(codex["version"], claude["version"])
        self.assertEqual((PACKAGE / codex["skills"]).resolve(), (PACKAGE / "skills").resolve())
        self.assertEqual({path.name for path in (PACKAGE / "skills").iterdir()}, set(STAGES.values()))
        for stage, name in STAGES.items():
            with self.subTest(stage=stage):
                loader = PACKAGE / "skills" / name / "SKILL.md"
                text = loader.read_text(encoding="utf-8")
                frontmatter, body = text.split("---", 2)[1:]
                self.assertIn(f"name: {name}\n", frontmatter)
                self.assertIn("description: ", frontmatter)
                resolved = [(loader.parent / link).resolve() for link in markdown_links(body)]
                self.assertCountEqual(resolved, [
                    self.shared_path.resolve(),
                    self.roles_path.resolve(),
                    (PACKAGE / "frameworks" / f"{name}.md").resolve(),
                ])
                # Native entries only select files. Substantive methods are not
                # repeated there, where host variants could silently diverge.
                self.assertNotIn("\n## ", body)
                self.assertNotIn(self.shared, body)
                self.assertNotIn(self.roles, body)
                self.assertNotIn(self.bodies[stage], body)
                for path in resolved:
                    self.assertTrue(path.is_file(), path)
                    self.assertTrue(path.is_relative_to(PACKAGE.resolve()), path)

        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory).resolve()
            home = temporary_root / "home"
            install(
                source=PACKAGE.parents[1], home=home,
                destination=temporary_root / "app", hosts=tuple(SKILL_HOMES),
                platform="linux",
            )
            installed_resources = temporary_root / "app/plugins/ora-vibe-coder/resources/programming-loop"
            self.assertEqual(
                {
                    path.relative_to(installed_resources): path.read_bytes()
                    for path in installed_resources.rglob("*") if path.is_file()
                },
                {
                    path.relative_to(PACKAGE / "resources/programming-loop"): path.read_bytes()
                    for path in (PACKAGE / "resources/programming-loop").rglob("*") if path.is_file()
                },
            )
            for host, host_home in SKILL_HOMES.items():
                installed_loop = home / host_home / "skills/programming-loop"
                installed_identity = json.loads((installed_loop / "SOURCE.json").read_text())
                self.assertEqual(installed_identity["source"], "programming-loop")
                self.assertEqual(installed_identity["source_kind"], "vendored-snapshot")
                self.assertEqual(
                    installed_identity["public_release_repository"],
                    "https://github.com/" + loop_integrity.authority_metadata()[
                        "public_release_repository"
                    ],
                )
                self.assertEqual(
                    installed_identity["source_revision"],
                    loop_integrity.authority_metadata()["source_revision"],
                )
                self.assertEqual(
                    installed_identity["source_tree"],
                    loop_integrity.authority_metadata()["source_tree"],
                )
                self.assertIsNone(installed_identity["source_manifest_sha256"])
                for name in ("VERSION", "README.md", "LICENSE", "NOTICE.md",
                             "frameworks/programming-loop.md", f"adapters/{host}.md"):
                    self.assertEqual(
                        (installed_loop / name).read_bytes(),
                        (PACKAGE / "resources/programming-loop" / name).read_bytes(),
                    )
                for stage, name in STAGES.items():
                    with self.subTest(installed_host=host, installed_stage=stage):
                        entry = home / host_home / "skills" / name / "SKILL.md"
                        operations = f"./resources/programming-loop/adapters/{host}.md"
                        self.assertEqual(
                            operations in entry.read_text(encoding="utf-8"),
                            stage in {"programming", "guided"},
                        )

    def test_handoff_reports_public_snapshot_and_rejects_conflicting_provenance(self):
        authority = loop_integrity.authority_metadata()
        packet = framework_text("programming", "Codex")
        self.assertIn("Vibe validates its bundled snapshot of Programming Loop 1.0.0's 17 product files and modes", packet)
        self.assertIn("This packet includes the universal Loop framework and, for a supported destination, exactly one selected host adapter.", packet)
        self.assertIn(
            f"public release {authority['public_release_repository']}", packet
        )
        self.assertIn(
            f"authoritative source revision {authority['source_revision']}", packet
        )
        self.assertIn("public release separately carries its delivery manifest", packet)
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "programming-loop"
            shutil.copytree(PACKAGE / "resources/programming-loop", copied)
            identity_path = copied / "SOURCE.json"
            identity = json.loads(identity_path.read_text())
            identity["authoritative_repository"] = "conflicting/source"
            identity_path.write_text(json.dumps(identity), encoding="utf-8")
            with mock.patch.object(handoff, "LOOP", copied):
                with self.assertRaisesRegex(ProjectError, "conflicting provenance"):
                    handoff.loop_resources("programming", "Codex")

            shutil.rmtree(copied)
            shutil.copytree(PACKAGE / "resources/programming-loop", copied)
            framework = copied / "frameworks/programming-loop.md"
            framework.write_bytes(framework.read_bytes() + b"\nself-attested change\n")
            identity_path = copied / "SOURCE.json"
            identity = json.loads(identity_path.read_text())
            identity["files"]["frameworks/programming-loop.md"] = hashlib.sha256(
                framework.read_bytes()
            ).hexdigest()
            identity_path.write_text(json.dumps(identity), encoding="utf-8")
            with mock.patch.object(handoff, "LOOP", copied):
                with self.assertRaisesRegex(ProjectError, "conflicting provenance"):
                    handoff.loop_resources("programming", "Codex")

    def test_one_authority_pin_allows_a_coherent_offline_advance(self):
        source = PACKAGE.parents[1] / "components" / "programming-loop"
        current_authority = loop_integrity.authority_metadata()
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            advanced_source = temporary / "advanced-source"
            shutil.copytree(source, advanced_source)
            readme = advanced_source / "README.md"
            readme.write_bytes(readme.read_bytes() + b"\nReviewed next release.\n")
            advanced_tree = loop_integrity.read_snapshot(advanced_source)[2]
            advanced_revision = "b" * 40
            advanced_authority = {
                **loop_integrity.authority_metadata(),
                "source_revision": advanced_revision,
                "source_tree": advanced_tree,
            }
            with mock.patch.object(loop_integrity, "AUTHORITY", advanced_authority):
                generated = assembly.assemble(
                    advanced_source,
                    revision=advanced_revision,
                    target=temporary / "resources",
                )
                with mock.patch.object(handoff, "LOOP", generated):
                    packet = handoff.loop_resources("programming", "Codex")
            self.assertIn(f"authoritative source revision {advanced_revision}", packet)
            self.assertNotIn(current_authority["source_revision"], packet)

    def test_each_standalone_packet_contains_full_shared_role_and_selected_text_once(self):
        """Fresh recipients receive complete sources, including completion obligations."""
        for stage in STAGES:
            if stage == "guided":
                continue
            with self.subTest(stage=stage):
                packet = framework_text(stage, "Codex")
                self.assertEqual(packet.count(self.shared), 1)
                self.assertEqual(packet.count(self.roles), 1)
                self.assertEqual(packet.count(self.bodies[stage]), 1)
                for other in STAGES:
                    if other != stage:
                        self.assertNotIn(self.bodies[other], packet)
                adapter = (PACKAGE / "resources/programming-loop/adapters/codex.md").read_text()
                self.assertEqual(packet.count(adapter), int(stage == "programming"))
                method = (PACKAGE / "resources/programming-loop/frameworks/programming-loop.md").read_text()
                self.assertEqual(packet.count(method), int(stage == "programming"))
        with mock.patch("ora_vibe_coder.handoff.loop_resources", side_effect=AssertionError):
            for stage in ("specification", "planning", "verification"):
                with self.subTest(loop_independent_stage=stage):
                    framework_text(stage, "Codex")

    def test_guided_packet_delivers_all_four_actual_stage_bodies(self):
        """The guide must not depend on a native sibling being installed."""
        packet = framework_text("guided", "Claude Code")
        self.assertEqual(packet.count(self.shared), 1)
        self.assertEqual(packet.count(self.roles), 1)
        for stage, body in self.bodies.items():
            with self.subTest(stage=stage):
                self.assertEqual(packet.count(body), 1)
        self.assertEqual(packet.count((PACKAGE / "resources/programming-loop/frameworks/programming-loop.md").read_text()), 1)
        self.assertEqual(packet.count((PACKAGE / "resources/programming-loop/adapters/claude.md").read_text()), 1)

    def test_each_entry_selects_one_complete_host_adapter_without_cross_host_material(self):
        root = PACKAGE / "resources" / "programming-loop"
        adapters = {
            host: (root / "adapters" / f"{host}.md").read_text()
            for host in set(HOSTS.values())
        }
        for stage in STAGES:
            for destination, host in HOSTS.items():
                with self.subTest(stage=stage, destination=destination):
                    packet = framework_text(stage, destination)
                    self.assertEqual(
                        packet.count(adapters[host]),
                        int(stage in {"programming", "guided"}),
                    )
                    for other, text in adapters.items():
                        if other != host:
                            self.assertNotIn(text, packet)

    def test_direct_markdown_sources_have_working_packaged_references(self):
        """Manual package users can follow every shared, role, and stage reference."""
        sources = [(self.shared_path, self.shared), (self.roles_path, self.roles)]
        sources.extend((PACKAGE / "frameworks" / f"{name}.md", self.bodies[stage])
                       for stage, name in STAGES.items())
        for source, text in sources:
            with self.subTest(source=source.name):
                references = {(source.parent / link).resolve()
                              for link in markdown_links(text)}
                if source == self.shared_path:
                    self.assertIn(self.roles_path.resolve(), references)
                elif source.parent == PACKAGE / "frameworks":
                    self.assertIn(self.shared_path.resolve(), references)
                for path in references:
                    self.assertTrue(path.is_file(), path)
                    self.assertTrue(path.is_relative_to(PACKAGE.resolve()), path)
                if source.name == "ora-vibe-coder.md":
                    self.assertTrue({
                        (PACKAGE / "frameworks" / f"{other}.md").resolve()
                        for key, other in STAGES.items() if key != "guided"
                    }.issubset(references))


if __name__ == "__main__":
    unittest.main()
