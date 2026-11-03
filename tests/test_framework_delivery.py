import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest import mock

from ora_vibe_coder import handoff, loop_integrity
from ora_vibe_coder.handoff import framework_text
from ora_vibe_coder.installer import SKILL_HOMES, install
from ora_vibe_coder.project import ProjectError


PACKAGE = Path(__file__).resolve().parents[1] / "plugins" / "ora-vibe-coder"
STAGES = {
    "specification": "ora-specification",
    "planning": "ora-planning",
    "programming": "ora-programming",
    "verification": "ora-verification",
    "guided": "ora-vibe-coder",
}


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
        repository = PACKAGE.parents[1]
        for component, reader, authority in (
            ("programming-loop", loop_integrity.read_snapshot, loop_integrity.authority_metadata),
            ("agent-bridge", loop_integrity.read_bridge_snapshot, loop_integrity.bridge_authority_metadata),
            ("ora-ai-boost", loop_integrity.read_boost_snapshot, loop_integrity.boost_authority_metadata),
        ):
            with self.subTest(component=component):
                source = reader(repository / "components" / component)
                self.assertEqual(source[2], authority()["source_tree"])
                if component != "agent-bridge":
                    packaged = PACKAGE / "resources" / component
                    self.assertEqual(reader(packaged, allowed_extra={"SOURCE.json"}), source)
                    identity = json.loads((packaged / "SOURCE.json").read_text())
                    self.assertEqual({key: identity[key] for key in authority()}, authority())


    def test_native_entries_load_the_packaged_shared_role_and_canonical_sources(self):
        for stage, name in STAGES.items():
            loader = PACKAGE / "skills" / name / "SKILL.md"
            text = loader.read_text()
            self.assertIn(f"name: {name}\n", text)
            self.assertCountEqual(
                [(loader.parent / link).resolve() for link in markdown_links(text)],
                [self.shared_path.resolve(), self.roles_path.resolve(),
                 (PACKAGE / "frameworks" / f"{name}.md").resolve()],
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            install(source=PACKAGE.parents[1], home=home, destination=root / "app",
                    hosts=tuple(SKILL_HOMES), platform="linux")
            for host, host_home in SKILL_HOMES.items():
                with self.subTest(host=host):
                    installed = home / host_home / "skills/ora-programming-loop"
                    identity = json.loads((installed / "SOURCE.json").read_text())
                    self.assertEqual(identity["host"], host)
                    self.assertEqual(identity["source_revision"],
                                     loop_integrity.authority_metadata()["source_revision"])
                    for name in ("frameworks/programming-loop.md", f"adapters/{host}.md"):
                        self.assertEqual((installed / name).read_bytes(),
                                         (PACKAGE / "resources/programming-loop" / name).read_bytes())
                    for stage, name in STAGES.items():
                        entry = home / host_home / "skills" / name / "SKILL.md"
                        self.assertEqual(f"./resources/programming-loop/adapters/{host}.md" in entry.read_text(),
                                         stage in {"programming", "guided"})


    def test_handoff_reports_public_snapshot_and_rejects_conflicting_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "programming-loop"
            shutil.copytree(PACKAGE / "resources/programming-loop", copied)
            identity_path = copied / "SOURCE.json"
            identity = json.loads(identity_path.read_text())
            for changed, message in (({"authoritative_repository": "conflicting/source"}, "conflicting provenance"),
                                     ({"component": "programming-loop"}, "conflicting provenance")):
                identity_path.write_text(json.dumps({**identity, **changed}))
                with mock.patch.object(handoff, "LOOP", copied):
                    with self.assertRaisesRegex(ProjectError, message):
                        handoff.loop_resources("programming", "Codex")
            framework = copied / "frameworks/programming-loop.md"
            framework.write_bytes(framework.read_bytes() + b"\nchanged\n")
            identity["files"]["frameworks/programming-loop.md"] = hashlib.sha256(framework.read_bytes()).hexdigest()
            identity_path.write_text(json.dumps(identity))
            with mock.patch.object(handoff, "LOOP", copied):
                with self.assertRaisesRegex(ProjectError, "mismatched"):
                    handoff.loop_resources("programming", "Codex")


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
