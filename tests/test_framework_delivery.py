import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from ora_vibe_coder.handoff import HOSTS, LOOP_FILES, framework_text
from ora_vibe_coder.installer import SKILL_HOMES, install


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

    def test_generated_loop_resources_are_exact_identified_component_inputs(self):
        root = PACKAGE / "resources" / "programming-loop"
        source = PACKAGE.parents[1] / "components" / "programming-loop"
        with tempfile.TemporaryDirectory() as directory:
            generated = assembly.assemble(source, target=Path(directory) / "resources")
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
            for host, host_home in SKILL_HOMES.items():
                for stage, name in STAGES.items():
                    with self.subTest(installed_host=host, installed_stage=stage):
                        entry = home / host_home / "skills" / name / "SKILL.md"
                        operations = f"./resources/programming-loop/adapters/{host}.md"
                        self.assertEqual(
                            operations in entry.read_text(encoding="utf-8"),
                            stage in {"programming", "guided"},
                        )

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
