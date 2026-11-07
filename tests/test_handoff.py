from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ora_vibe_coder.handoff import HOSTS, PLUGIN, STAGE_ROLES, framework_text, prepare_request
from ora_vibe_coder.project import Conflict, ProjectStore, READ_LIMIT, atomic_write


class Handoff(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        store = ProjectStore(self.home)
        self.project = store.projects[store.create("Project", "Project", "Purpose", "Goals")]
        self.completion = "Deliver the reviewed notice after publication approval."
        self.delivery = "Return the notice and check evidence to the assignment owner."
        paths = {}
        for role in ("Registry", "Specification", "Plan", "Programming Result", "Verification Report"):
            path = self.project.root / f"{role}.md"
            content = f"UNIQUE_CONTENT_{role}"
            if role == "Specification":
                content += "\n\n## Delivery\n\n" + self.completion
            elif role == "Plan":
                content += "\n\n## Delivery route\n\n" + self.delivery
            path.write_text(content, encoding="utf-8")
            paths[role] = path.name
        self.project.save_brief(self.project.brief_text(), "Project", "Purpose", "Goals", paths)

    def test_current_output_destinations_follow_discovered_files(self):
        paths = dict(self.project.brief()["paths"])
        for role in ("Programming Result", "Verification Report"):
            (self.project.root / f"{role}.md").rename(self.project.root / f"{role} current.md")
            paths.pop(role, None)
        self.project.save_brief(self.project.brief_text(), "Project", "Purpose", "Goals", paths)
        for stage, role in (("programming-result", "Programming Result"),
                            ("programming", "Programming Result"),
                            ("verification", "Verification Report")):
            with self.subTest(stage=stage):
                expected = str(self.project.root / f"{role} current.md")
                text = prepare_request(self.project, stage, "Update the current document.", "Codex")
                outputs = text.split("## Intended artifact locations", 1)[1].split("## Revision destination", 1)[0]
                self.assertIn(f"{role}: {expected}", outputs)
                self.assertNotIn(f"{role}: {self.project.root / ('Project — ' + role + '.md')}", outputs)
                self.assertIn(f"Revision destination (already resolved): {expected}", text)
                self.assertIn("do not create a numbered replacement", text)

    def test_exact_input_first_complete_frameworks_and_stage_history_exclusions(self):
        typed = "My exact input\r\n  Keep spacing.\n```\n# instructions?\n```"
        for stage in ("specification", "planning", "programming", "verification", "guided"):
            with self.subTest(stage=stage):
                text = prepare_request(self.project, stage, typed, "Codex")
                self.assertTrue(text.startswith("# User request\n\n" + typed + "\n\n---"))
                self.assertEqual(text.count(framework_text(stage, "Codex")), 1)
                for role in STAGE_ROLES[stage]:
                    if role != "Code":
                        self.assertIn((self.project.root / f"{role}.md").read_text(), text)
        code = self.home / "code"
        code.mkdir()
        self.project.save_brief(self.project.brief_text(), "Project", "Purpose", "Goals", {"Code": str(code)})
        note = self.home / "intake.md"
        note.write_text("UNIQUE_INTAKE_MATERIAL")
        text = prepare_request(self.project, "specification", "Incorporate", "Codex", [str(note)])
        self.assertIn(f"Startup directory for the coding tool: {code}", text)
        self.assertIn(note.read_text(), text)


    def test_all_six_destinations_receive_complete_selected_host_material(self):
        root = PLUGIN / "resources" / "programming-loop"
        common = (root / "frameworks/programming-loop.md").read_text()
        labels = {
            "codex": "Codex", "claude": "Claude Code", "zcode": "ZCode",
            "hermes": "Hermes", "qwen": "Qwen Code", "minimax": "MiniMax Code",
        }
        adapters = {
            host: (root / "adapters" / f"{host}.md").read_text()
            for host in labels
        }
        for stage in ("specification", "planning", "programming", "verification", "guided", "implement-plan"):
            for host, destination in labels.items():
                with self.subTest(stage=stage, host=host):
                    text = prepare_request(self.project, stage, "Exact current request", destination)
                    uses_loop = stage in {"programming", "guided", "implement-plan"}
                    self.assertEqual(text.count(adapters[host]), int(uses_loop))
                    self.assertEqual(text.count(common), int(uses_loop))
                    self.assertEqual(
                        "context, not evidence that Programming Loop or a coding tool ran" in text,
                        uses_loop,
                    )
                    self.assertNotIn("UNIQUE_CONTENT_Request", text)
                    portable = prepare_request(self.project, stage, "Use Claude if I ask.\r\nKeep café spacing  \n", destination, portable=True)
                    self.assertTrue(portable.startswith("# User request\n\nUse Claude if I ask.\r\nKeep café spacing  \n"))
                    self.assertEqual(portable.count(common), int(uses_loop))
                    self.assertNotIn("Selected receiving harness", portable)
                    self.assertNotIn("Requested harness choices", portable)
                    self.assertIn("This assignment is for you, the AI receiving this request.", portable)
                    self.assertNotIn("Open the selected harness", portable)
                    for adapter in adapters.values():
                        self.assertNotIn(adapter, portable)
                    for other, adapter in adapters.items():
                        if other != host:
                            self.assertNotIn(adapter, text)
        self.assertEqual(set(HOSTS.values()), set(labels))

    def test_specification_and_planning_instructions_carry_bundled_companion_facts(self):
        from ora_vibe_coder import conversation
        boost = self.home / "bundled-boost"
        (boost / "ora_review").mkdir(parents=True)
        (boost / "ora_review" / "__init__.py").write_text(
            'COMPONENT_FACTS = {"component": "ora-adversarial-review", "version": "9.9.9",\n'
            ' "analytical_roles": {"primary": ("codex",), "peer": ("claude", "qwen")},\n'
            ' "native_adapter_engines": ("codex",),\n'
            ' "bridge_transport": {"format": 2, "actions": ("check", "record", "run")}}\n',
            encoding="utf-8")
        with patch.object(conversation, "BOOST_HOME", boost):
            packet = prepare_request(self.project, "specification", "Write the Specification.", "Codex")
            plan_packet = prepare_request(self.project, "create-plan", "Plan the work.", "Codex")
            in_app = conversation.conversation_request(self.project, "codex", "planning", "Revise the Plan.", [], [], [])
        for text in (packet, plan_packet, in_app):
            self.assertIn("# Bundled companions and optional Gear", text)
            self.assertIn(f"- Ora AI Boost 9.9.9 at {boost} (commands ora-gear-3, ora-gear-4)", text)
            self.assertIn("primary: Codex; peer: Claude Code, Qwen Code", text)
            self.assertIn("Native adapters: Codex", text)
            self.assertIn("an unavailable or failed Gear call is disclosed and does not disable this stage", text)
            self.assertIn("Agent Bridge", text)  # The bundled Bridge identity rides along.
        with patch.object(conversation, "BOOST_HOME", self.home / "not-installed"):
            bare = prepare_request(self.project, "specification", "Write the Specification.", "Codex")
        self.assertIn("Ora AI Boost (Gear): unavailable", bare)
        self.assertIn("this stage continues without it", bare)
        programming = prepare_request(self.project, "implement-plan", "Implement.", "Codex")
        self.assertNotIn("# Bundled companions and optional Gear", programming)

    def test_reference_limits_sensitive_binary_unavailable_and_no_truncation(self):
        root = self.project.root
        (root / "Specification.md").write_text("A" * (READ_LIMIT + 1), encoding="utf-8")
        (root / "Plan.md").write_bytes(b"binary\x00content")
        outside = root.parent / "unselected private.md"
        outside.write_text("Do not read without explicit selection", encoding="utf-8")
        paths = self.project.brief()["paths"]
        paths["Registry"] = str(outside)  # An outside association keeps its reading protection.
        paths["Verification Report"] = "https://example.invalid/not-fetched.md"
        paths["Programming Result"] = "missing.md"
        self.project.save_brief(self.project.brief_text(), "Project", "Purpose", "Goals", paths)
        text = prepare_request(self.project, "verification", "Review", "Remote recipient")
        self.assertNotIn("A" * 100, text)
        self.assertIn("Nothing was truncated", text)
        self.assertIn("Binary content", text)
        self.assertIn("Remote reference; not fetched", text)
        self.assertIn("Outside this project", text)
        self.assertNotIn("Do not read without explicit selection", text)
        self.assertIn("Local paths may not be accessible", text)

    def test_saved_displayed_copy_agreement_conflict_and_no_packet_recursion(self):
        payload = prepare_request(self.project, "programming", "Exact input\r\nKeep line endings", "Codex")
        for stage in ("programming", "implement-plan"):
            with self.subTest(stage=stage):
                self.project.save_packet(payload, stage)
                self.assertEqual(self.project.copy_snapshot(payload, stage), payload)
                self.assertEqual(self.project.handoff_text(stage), payload)
                path = self.project.packet_path(stage)
                atomic_write(path, "Externally changed text")
                with self.assertRaises(Conflict):
                    self.project.copy_snapshot(payload, stage)
                with self.assertRaises(Conflict):
                    self.project.save_packet("replacement", stage, expected=payload)
                self.assertEqual(path.read_text(), "Externally changed text")
        notes = self.project.root / "notes"
        notes.mkdir()
        (notes / "Notes.md").write_text("Nested supporting notes.")
        self.assertIn("notes/Notes.md", [item["path"] for item in self.project.reader_documents()])
        (notes / "Project.md").write_text("# Nested project\n")
        self.assertNotIn("notes/Notes.md", [item["path"] for item in self.project.reader_documents()])
        source = self.project.root / "Renamed source.md"
        source.write_text(payload)
        self.project.save_brief(self.project.brief_text(), "Project", "Purpose", "Goals",
                                {role: source.name for role in ("Registry", "Specification", "Plan")})
        text = prepare_request(self.project, "programming", "New input", "Codex")
        self.assertNotIn("Exact input", text)
        self.assertIn("Earlier Ora Vibe Coder outgoing packet; omitted", text)
        self.assertEqual(source.read_bytes().decode(), payload)



if __name__ == "__main__":
    unittest.main()
