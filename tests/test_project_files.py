import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ora_vibe_coder.project import Conflict, ProjectError, ProjectStore, atomic_write


class ProjectFiles(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.store = ProjectStore(self.home)

    def project(self, name="One"):
        key = self.store.create(name, name, "Description", "Goals")
        return self.store.projects[key]

    def test_two_projects_preserve_sources_and_unknown_overview_fields(self):
        description = "Purpose\n\n## Goals\nKeep this detail"
        with self.assertRaisesRegex(ProjectError, "Description cannot contain.*Your input is retained"):
            self.store.create("One", "One", description, "Actual goal")
        self.assertFalse((self.home / "One").exists())
        first, second = self.project(), self.project("Two")
        source = first.root / "existing.md"
        source.write_text("Original source", encoding="utf-8")
        original = first.brief_text() + "\n## Unowned notes\n\nKeep this exactly.\n"
        original = original.replace("Programming: NOT STARTED", "Programming: COMPLETE\nOwner: Larry")
        original = original.replace("Name: One", "  Name: One")
        atomic_write(first.root / "Project.md", original)
        self.assertEqual(first.brief()["name"], "One")
        description = "Changed description\n\n### Keep this detail\nAll text remains."
        saved = first.save_brief(original, "Changed name", description, "Same goals", {"Specification": str(source), "Code": str(second.root)})
        self.assertEqual(saved["name"], "Changed name")
        self.assertEqual(first.brief()["name"], "Changed name")
        self.assertEqual(first.brief()["description"], description)
        self.assertEqual(source.read_text(), "Original source")
        self.assertIn("Owner: Larry", first.brief_text())
        self.assertIn("Programming: COMPLETE", first.brief_text())
        self.assertIn("## Unowned notes\n\nKeep this exactly.\n", first.brief_text())
        self.assertEqual(first.brief()["paths"]["Specification"], "existing.md")
        self.assertEqual(second.brief()["name"], "Two")
        self.assertEqual(sorted(path.name for path in second.root.iterdir()), ["Project.md"])

    def test_observed_conflict_preserves_current_file_and_retained_input(self):
        project = self.project()
        loaded = project.brief_text()
        current = loaded.replace("Programming: NOT STARTED", "Programming: IN PROGRESS")
        atomic_write(project.root / "Project.md", current)
        with self.assertRaises(Conflict) as caught:
            project.save_brief(loaded, "My unsaved name", "typed", "goals", {})
        self.assertEqual(caught.exception.current, current)
        self.assertEqual(project.brief_text(), current)
        # Explicit rereview permits another save while preserving the result.
        project.save_brief(current, "My unsaved name", "typed", "goals", {})
        self.assertIn("Programming: IN PROGRESS", project.brief_text())
        current = project.brief_text()
        with self.assertRaisesRegex(ProjectError, "Goals cannot contain.*nothing was saved"):
            project.save_brief(current, "Retained new name", "typed", "Actual goal\n\n## Artifact Paths\nKeep this detail", {})
        self.assertEqual(project.brief_text(), current)

    def test_atomic_failure_preserves_old_packet_and_removes_only_staging(self):
        project = self.project()
        project.save_packet("old packet", None, False)
        with patch("ora_vibe_coder.project.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                project.save_packet("new input", "old packet", True)
        self.assertEqual(project.handoff_text(), "old packet")
        self.assertEqual(sorted(path.name for path in project.root.iterdir()), ["Handoff.md", "Project.md"])

    def test_collisions_aliases_traversal_and_explicit_external_selection(self):
        project = self.project()
        with self.assertRaises((OSError, ProjectError)):
            self.store.create("../escape", "bad", "", "")
        with self.assertRaises(FileExistsError):
            self.project()
        external = self.home / "private.md"
        external.write_text("Explicit private document", encoding="utf-8")
        project.save_brief(project.brief_text(), "One", "", "", {"Specification": str(external)})
        self.assertTrue(project.material("Specification")["needs_selection"])
        self.assertIsNone(project.material("Specification")["text"])
        project.approve_reference("Specification", str(external))
        self.assertEqual(project.material("Specification")["text"], "Explicit private document")
        link = project.root / "linked.md"
        link.symlink_to(external)
        with self.assertRaises(ProjectError):
            project.save_brief(project.brief_text(), "One", "", "", {"Specification": "linked.md"})
        (project.root / "Handoff.md").symlink_to(external)
        with self.assertRaises(ProjectError):
            project.save_packet("bad", None, False)
        self.assertEqual(external.read_text(), "Explicit private document")

    def test_hardlink_source_collision_and_sequential_framework_result_updates(self):
        project = self.project()
        source = project.root / "source.md"
        source.write_text("Source stays intact", encoding="utf-8")
        project.save_brief(project.brief_text(), "One", "", "", {"Plan": "source.md"})
        os.link(source, project.root / "Handoff.md")
        with self.assertRaises(ProjectError):
            project.save_packet("replacement", "Source stays intact", True)
        self.assertEqual(source.read_text(), "Source stays intact")
        # Simulate each framework rereading and minimally editing its own field.
        # Then prove the app retains both externally reported results on a save.
        atomic_write(project.root / "Project.md", project.brief_text().replace("Programming: NOT STARTED", "Programming: COMPLETE"))
        reread = project.brief_text()
        atomic_write(project.root / "Project.md", reread.replace("Verification: NOT STARTED", "Verification: NOT PASSED"))
        project.save_brief(project.brief_text(), "One", "After framework results", "Goals", {"Plan": "source.md"})
        final = project.brief_text()
        self.assertIn("Programming: COMPLETE", final)
        self.assertIn("Verification: NOT PASSED", final)
        self.assertIn("- Plan: source.md", final)


if __name__ == "__main__":
    unittest.main()
