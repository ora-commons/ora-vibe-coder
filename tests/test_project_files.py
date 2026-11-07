import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ora_vibe_coder.handoff import prepare_request
from ora_vibe_coder.project import Conflict, ProjectError, ProjectStore, atomic_write
from ora_vibe_coder.status import review_basis

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
        frontmatter = "---\r\nName: YAML name\r\nProgramming: NOT STARTED\r\nVerification: PASSED\r\n## Goals\r\ntags: [project]\r\n---\r\n\r\n"
        original = frontmatter + original
        atomic_write(first.root / "Project.md", original)
        self.assertEqual(first.brief()["name"], "One")
        description = "Changed description\n\n### Keep this detail\nAll text remains."
        saved = first.save_brief(original, "Changed name", description, "Same goals", {"Specification": str(source), "Code": str(second.root)})
        self.assertEqual(saved["name"], "Changed name")
        self.assertEqual(saved["statuses"]["programming"]["label"], "COMPLETE")
        self.assertEqual(saved["statuses"]["verification"]["label"], "NOT STARTED")
        self.assertTrue(first.brief_text().startswith(frontmatter + "# Project\n"))
        self.assertEqual(first.brief_text().count("Name: Changed name"), 1)
        self.assertNotIn("Name: One", first.brief_text())
        self.assertEqual(first.brief()["name"], "Changed name")
        self.assertEqual(first.brief()["description"], description)
        self.assertEqual(source.read_text(), "Original source")
        self.assertIn("Owner: Larry", first.brief_text())
        self.assertIn("Programming: COMPLETE", first.brief_text())
        self.assertIn("## Unowned notes\n\nKeep this exactly.\n", first.brief_text())
        self.assertEqual(first.brief()["paths"]["Specification"], "existing.md")
        self.assertEqual(second.brief()["name"], "Two")
        self.assertEqual(sorted(path.name for path in second.root.iterdir()),
                         ["Plan.md", "Project.md", "Registry.md", "Specification.md"])

    def test_yaml_with_missing_or_duplicate_body_name_preserves_the_original(self):
        project = self.project()
        frontmatter = "---\nName: YAML name\nOwner: YAML owner\n---\n\n"
        original = frontmatter + project.brief_text().replace("Name: One\n", "")
        atomic_write(project.root / "Project.md", original)
        saved = project.save_brief(original, "Added name", "Description", "Goals", {})
        self.assertEqual(saved["name"], "Added name")
        self.assertEqual(saved["statuses"]["programming"]["label"], "NOT STARTED")
        self.assertTrue(project.brief_text().startswith(frontmatter + "# Project\n"))
        for prefix in ("", frontmatter):
            with self.subTest(frontmatter=bool(prefix)):
                duplicate = prefix + "# Project\nName: One\n**Name:** Another\nOwner: Larry\n"
                atomic_write(project.root / "Project.md", duplicate)
                with self.assertRaisesRegex(ProjectError, "duplicate Name fields"):
                    project.save_brief(duplicate, "Changed name", "Description", "Goals", {})
                self.assertEqual(project.brief_text(), duplicate)
        unclosed = "---\nName: YAML name\nOwner: Larry\n"
        atomic_write(project.root / "Project.md", unclosed)
        with self.assertRaisesRegex(ProjectError, "unclosed YAML frontmatter"):
            project.save_brief(unclosed, "Changed name", "Description", "Goals", {})
        self.assertEqual(project.brief_text(), unclosed)

    def test_observed_conflict_preserves_current_file_and_retained_input(self):
        project = self.project()
        loaded = project.brief_text()
        current = loaded.replace("Programming: NOT STARTED", "Programming: IN PROGRESS")
        atomic_write(project.root / "Project.md", current)
        with self.assertRaises(Conflict) as caught:
            project.save_brief(loaded, "My unsaved name", "typed", "goals", {})
        self.assertEqual(caught.exception.current, current)
        self.assertEqual(project.brief_text(), current)
        project.save_brief(current, "My unsaved name", "typed", "goals", {})
        self.assertIn("Programming: IN PROGRESS", project.brief_text())
        current = project.brief_text()
        with self.assertRaisesRegex(ProjectError, "Desired outcome cannot contain.*nothing was saved"):
            project.save_brief(current, "Retained new name", "typed", "Actual goal\n\n## Artifact Paths\nKeep this detail", {})
        self.assertEqual(project.brief_text(), current)

    def test_atomic_failure_preserves_old_packet_and_removes_only_staging(self):
        project = self.project()
        project.save_packet("old packet")
        with patch("ora_vibe_coder.project.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                project.save_packet("new input", expected="old packet")
        self.assertEqual(project.handoff_text(), "old packet")
        self.assertEqual(sorted(path.name for path in project.root.iterdir()),
                         ["Handoff.md", "Plan.md", "Project.md", "Registry.md", "Specification.md"])

    def test_folder_discovery_and_override(self):
        folder = self.home / "Work"
        folder.mkdir()
        expected = folder / "Work — Specification.md"
        expected.write_text("# Specification\n\nStatus: DRAFT\n\n## Body\nBehavior.\n", encoding="utf-8")
        (folder / "notes.md").write_text(
            "---\nvibe_document: registry\n---\n\n# Registry\n\n## Notes\nA useful product's notes.\n",
            encoding="utf-8")
        (folder / "spec and plan.md").write_text("# Both roles\n", encoding="utf-8")
        (folder / "my spec draft.md").write_text("# Draft spec\n", encoding="utf-8")
        packet = prepare_request(self.project(), "specification", "Exact input", "Codex")
        (folder / "returned plan.md").write_text(packet, encoding="utf-8")

        key = self.store.open(folder)
        project = self.store.projects[key]
        before = sorted(path.name for path in folder.iterdir())
        snapshot = project.snapshot()
        self.assertEqual(sorted(path.name for path in folder.iterdir()), before)  # Opening creates no files.
        self.assertIsNone(project.brief_text())  # No overview is required.
        documents = snapshot["documents"]
        self.assertEqual(documents["Specification"]["name"], expected.name)
        self.assertEqual(documents["Specification"]["origin"], "discovered")
        self.assertEqual(documents["Registry"]["name"], "notes.md")  # Label in closed frontmatter.
        self.assertIsNone(project.reference("Plan"))  # The outgoing packet is never a revision target.
        self.assertIsNone(project.material("Plan")["text"])
        conflicts = "\n".join(snapshot["discovery_conflicts"])
        self.assertIn("spec and plan.md", conflicts)  # Conflicting identity stays for Choose File.
        self.assertIsNone(snapshot["documents"]["Plan"]["path"])
        self.assertEqual(project.brief()["description"], "")

    def test_newest_result_documents_supply_the_status_unless_explicitly_selected(self):
        project = self.project()
        old_result = project.root / "Programming Result.md"
        new_result = project.root / "Programming Result 2.md"
        old_report = project.root / "Verification Report.md"
        new_report = project.root / "Verification Report 2.md"
        old_result.write_text("---\nstatus: NOT PASSED\n---\n# Result\n", encoding="utf-8")
        new_result.write_text("---\nstatus: PASSED\n---\n# Result\n", encoding="utf-8")
        old_report.write_text("---\nstatus: NOT PASSED\n---\n# Report\n", encoding="utf-8")
        new_report.write_text("---\nstatus: PASSED\n---\n# Report\n", encoding="utf-8")
        for path, time in ((old_result, 100), (new_result, 200), (old_report, 100), (new_report, 200)):
            os.utime(path, (time, time))
        saved = project.snapshot()
        self.assertEqual(saved["documents"]["Programming Result"]["path"], str(new_result))
        self.assertEqual(saved["documents"]["Verification Report"]["path"], str(new_report))
        self.assertEqual(saved["programming_result"]["status"]["label"], "REPORT ERROR")
        self.assertIn("Programming Result.md: NOT PASSED", saved["programming_result"]["status"]["reason"])
        self.assertIn("Verification Report 2.md: PASSED", saved["verification"]["status"]["reason"])
        self.assertEqual(saved["statuses"]["programming"]["label"], "NOT STARTED")
        old_result.write_text("---\nstatus: IN PROGRESS\n---\n# Result\n", encoding="utf-8")
        os.utime(old_result, (100, 100))
        # Discovered with no association, the off-list candidate creates no conflict.
        self.assertEqual(project.snapshot()["programming_result"]["status"]["label"], "PASSED")
        old_result.write_text("---\nstatus: NOT PASSED\n---\n# Result\n", encoding="utf-8")
        os.utime(old_result, (100, 100))
        project.save_brief(project.brief_text(), "One", "Description", "Goals",
                           {"Programming Result": old_result.name, "Verification Report": old_report.name})
        selected = project.snapshot()
        self.assertEqual(selected["documents"]["Programming Result"]["origin"], "association")
        self.assertEqual(selected["programming_result"]["status"]["label"], "NOT PASSED")
        self.assertEqual(selected["verification"]["status"]["label"], "NOT PASSED")
        old_result.write_text("---\nstatus: IN PROGRESS\n---\n# Result\n", encoding="utf-8")
        saved = project.snapshot()
        # The off-list candidate creates no conflict; only its own read errors.
        self.assertEqual(saved["programming_result"]["status"]["label"], "Unknown — YAML status value: IN PROGRESS")
        self.assertNotIn("conflicting current conclusions", saved["programming_result"]["status"]["reason"])
        project.save_brief(project.brief_text(), "One", "Description", "Goals",
                           {"Programming Result": new_result.name, "Verification Report": new_report.name})
        selected = project.snapshot()
        self.assertEqual(selected["programming_result"]["status"]["label"], "PASSED")
        self.assertEqual(selected["verification"]["status"]["label"], "PASSED")

        failed_report = ("---\nstatus: NOT PASSED\ndisposition: SEVERE\n---\n# Verification Report\n"
                         "- R1 — login accepts an empty password.\n"
                         "- R2 — export omits the summary row.\n"
                         "- S1 — export sends addresses outside the account.\n")
        corrected_result = ("---\nstatus: PASSED\ndisposition: SETTLED\n---\n# Programming Result\n"
                            "- R1 — FIXED — empty passwords now fail the login check.\n"
                            "- R2 — REJECTED — the approved scope excludes a summary row.\n"
                            "- S1 — FIXED — removed the outside send; the local-export check passes.\n")
        new_report.write_text(failed_report, encoding="utf-8")
        os.utime(new_report, (300, 300))
        for unfinished in (
                "---\nstatus: PASSED\ndisposition: SETTLED\n---\n# Result\nBuilt unrelated work.\n",
                corrected_result.replace("- R2 — REJECTED — the approved scope excludes a summary row.\n", ""),
                corrected_result.replace("- S1 — FIXED", "- S1 — REJECTED"),
                corrected_result.replace("status: PASSED\n", ""),
                corrected_result.replace("status: PASSED", "status: INCOMPLETE"),
                corrected_result.replace("status: PASSED", "status: PASSED\nstatus: PASSED"),
                corrected_result.replace("disposition: SETTLED\n", ""),
                corrected_result.replace("disposition: SETTLED", "disposition: SETTLED today")):
            with self.subTest(result=unfinished):
                new_result.write_text(unfinished, encoding="utf-8")
                os.utime(new_result, (400, 400))
                self.assertEqual(project.snapshot()["verification"]["status"]["label"], "NOT PASSED")
        new_result.write_text(corrected_result, encoding="utf-8")
        os.utime(new_result, (400, 400))
        corrected = project.snapshot()["verification"]["status"]
        self.assertEqual((corrected["label"], corrected["kind"], corrected["literal"]),
                         ("CORRECTED", "positive", "NOT PASSED"))
        reopened = ProjectStore(self.home)
        self.assertEqual(reopened.projects[reopened.open(project.root)].snapshot()["verification"]["status"]["label"],
                         "CORRECTED")
        self.assertEqual(new_report.read_text(encoding="utf-8"), failed_report)
        # A later report can reuse finding labels without inheriting settlement.
        new_report.write_text(failed_report.replace("login accepts", "login still accepts"), encoding="utf-8")
        os.utime(new_report, (500, 500))
        self.assertEqual(project.snapshot()["verification"]["status"]["label"], "NOT PASSED")

        # Without S labels identifying severity, every current finding needs a fix.
        new_report.write_text("---\nstatus: NOT PASSED\ndisposition: SEVERE\n---\n# Verification Report\n"
                              "- R1 — export sends addresses outside the account.\n"
                              "- R2 — export omits the summary row.\n", encoding="utf-8")
        os.utime(new_report, (600, 600))
        rejection = "- R1 — REJECTED — accepted as current behavior.\n"
        summary_rejection = "- R2 — REJECTED — the approved scope excludes a summary row.\n"
        summary_fix = "- R2 — FIXED — export includes the summary row.\n"
        for decisions, expected in (
                (rejection + summary_rejection, "NOT PASSED"),
                (rejection + summary_rejection + "- R9 — FIXED — unrelated display text is corrected.\n", "NOT PASSED"),
                (rejection + summary_fix, "NOT PASSED"),
                ("- R1 — FIXED — removed the outside send; the local-export check passes.\n"
                 + summary_fix, "CORRECTED")):
            with self.subTest(decisions=decisions):
                new_result.write_text("---\nstatus: PASSED\ndisposition: SETTLED\n---\n# Programming Result\n"
                                      + decisions, encoding="utf-8")
                os.utime(new_result, (700, 700))
                self.assertEqual(project.snapshot()["verification"]["status"]["label"], expected)

    def test_retained_review_snapshot_establishes_applicability(self):
        project = self.project()
        path = project.root / "Specification.md"
        old = "---\nnexus: ora\ndate modified: 2026-10-04\n---\n\n# Specification\n\nStatus: DRAFT\n\n## Requirements\nKeep the work.\n"
        digest = review_basis(old)
        current = old.replace("DRAFT", "APPROVED").replace("2026-10-04", "2026-10-09").replace(
            "## Requirements", "## **Requirements**").replace("---\n", "---\nreview: PASSED\n", 1)
        current += f"\n## Current review\nBasis: {digest}\n"
        path.write_text(current)
        self.assertEqual(project.snapshot()["assessments"]["specification"]["applies"], "unconfirmed")
        record = project.root / ".vibe/0001/session/messages/0002-initiator-to-peer.md"
        record.parent.mkdir(parents=True)
        record.write_text(f"# Review request\n\n## Specification\n\nSource:\n\n```text\n{path}\n```\n\n```text\n{old}\n```\n")
        self.assertFalse([item for item in project.reader_documents() if ".vibe" in item["path"]])
        before = path.read_text()
        assessment = project.snapshot()["assessments"]["specification"]
        self.assertEqual((assessment["verdict"], assessment["applies"]), ("PASSED", "current"))
        self.assertEqual(path.read_text(), before)  # No repair or restamping of the user's document.
        path.write_text(current.replace("Keep the work.", "Change the work."))
        self.assertEqual(project.snapshot()["assessments"]["specification"]["applies"], "unconfirmed")

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
            project.save_packet("bad")
        self.assertEqual(external.read_text(), "Explicit private document")

    def test_recursive_inventory_and_archive_state(self):
        home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, home)
        (home / "Project.md").write_text("# Project\n\nName: Documents Root\nParent: Ora\nProject state: ACTIVE\n\n## Description\n\nTop.\n", encoding="utf-8")
        legacy = home / "legacy project"
        legacy.mkdir()
        legacy_definition = "# Project\n\nName: Legacy\n\n## Description\n\nNo state field yet.\n"
        (legacy / "Project.md").write_text(legacy_definition, encoding="utf-8")
        archive = home / "Archive" / "Old"
        archive.mkdir(parents=True)
        (archive / "Project.md").write_text("# Project\n\nName: Old\nProject state: ARCHIVED\n", encoding="utf-8")
        beneath = archive / "Beneath"
        beneath.mkdir()
        (beneath / "Project.md").write_text("# Project\n\nName: Beneath\nProject state: ACTIVE\n", encoding="utf-8")
        outside_link = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, outside_link)
        (outside_link / "Project.md").write_text("Name: Outside linked project\n", encoding="utf-8")
        (home / "linked directory").symlink_to(outside_link, target_is_directory=True)
        retained = home / ".vibe" / "saved packet"
        retained.mkdir(parents=True)
        (retained / "Project.md").write_text("Name: Retained packet\n", encoding="utf-8")
        store = ProjectStore(home)
        self.addCleanup(store.close)
        entries = {entry["path"]: entry for entry in store.list(include_archived=True)}
        names = {entry["name"]: entry for entry in entries.values()}
        self.assertIn("Documents Root", names)   # Directly in the discovery root.
        self.assertIn("Legacy", names)           # Nested at depth.
        self.assertIn("Beneath", names)          # Discovery continues beneath archived parents.
        self.assertNotIn("Outside linked project", names)
        self.assertNotIn("Retained packet", names)
        self.assertTrue(names["Old"]["archived"])
        self.assertFalse(names["Legacy"]["archived"])
        self.assertEqual(names["Documents Root"]["label"], "Ora → Documents Root")
        self.assertEqual((legacy / "Project.md").read_text(), legacy_definition)
        active = {entry["name"] for entry in store.list()}
        self.assertNotIn("Old", active)
        self.assertIn("Legacy", active)
        self.assertIn("Beneath", active)

        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, outside)
        os.rename(legacy, outside / "moved")
        os.unlink(beneath / "Project.md")
        store.rescan()
        entries = {entry["path"] for entry in store.list(include_archived=True)}
        self.assertNotIn(str(legacy), entries)
        self.assertNotIn(str(beneath), entries)
        self.assertIn(str(home), entries)
        self.assertIn(legacy, {project.root for project in store.projects.values()})

    def test_list_positions_lead_labels_and_set_the_order(self):
        def define(folder, name, position=None, parent="Ora"):
            folder.mkdir(parents=True)
            line = f"Position: {position}\n" if position else ""
            (folder / "Project.md").write_text(f"# Project\n\nName: {name}\n{line}Parent: {parent}\n", encoding="utf-8")
        define(self.home / "a", "ORA-200 — Fix defects", "G1.3")
        define(self.home / "b", "ORA-1 — Fix the approval setting", "G1.10")
        define(self.home / "a" / "c", "ORA-201 — Safety repairs", "G1.3.1", parent="Ora → ORA-200 — Fix defects")
        define(self.home / "d", "ORA-3 — MSI correction", "MSI.1", parent="MSI")
        define(self.home / "e", "ORA-47 — Welcome message", "G2.12")
        define(self.home / "f", "Unplaced project")
        labels = [entry["label"] for entry in ProjectStore(self.home).list(include_archived=True)]
        self.assertEqual(labels, ["G1.3 · Ora → ORA-200 — Fix defects",
                                  "G1.3.1 · Ora → ORA-200 — Fix defects → ORA-201 — Safety repairs",
                                  "G1.10 · Ora → ORA-1 — Fix the approval setting",
                                  "G2.12 · Ora → ORA-47 — Welcome message",
                                  "MSI.1 · MSI → ORA-3 — MSI correction",
                                  "Ora → Unplaced project"])
        entry = next(e for e in ProjectStore(self.home).list() if e["position"] == "G1.3")
        self.assertEqual(entry["lineage"], "Ora → ORA-200 — Fix defects")
        from ora_vibe_coder.project import edit_brief
        original = (self.home / "a" / "Project.md").read_text(encoding="utf-8")
        self.assertIn("Position: G1.3\n", edit_brief(original, "ORA-200 — Fix defects", "New", "Goals", {}))

    def test_create_under_and_parent_labels(self):
        top = self.home / "Ora"
        top.mkdir()
        (top / "Project.md").write_text("# Project\n\nName: Ora\n\n## Description\n\nTop.\n", encoding="utf-8")
        experts = top / "Experts"
        experts.mkdir()
        (experts / "Project.md").write_text("# Project\n\nName: Experts\nParent: Ora\nProject state: ARCHIVED\n\n## Description\n\nSelection.\n", encoding="utf-8")
        selection = experts / "Selection"
        selection.mkdir()
        (selection / "Project.md").write_text("# Project\n\nName: Expert selection\nParent: Ora → Experts\n\n## Description\n\nPick.\n", encoding="utf-8")
        store = ProjectStore(self.home)
        labels = [entry["label"] for entry in store.list(include_archived=True)]
        self.assertIn("Ora → Experts", labels)  # The complete parent name is preserved.
        self.assertIn("Ora → Experts → Expert selection", labels)
        self.assertLess(labels.index("Ora → Experts"), labels.index("Ora → Experts → Expert selection"))  # Full-lineage grouping.
        active = [entry["label"] for entry in store.list()]
        self.assertIn("Ora → Experts → Expert selection", active)  # An active child of an archived parent.
        self.assertNotIn("Ora → Experts", active)

        key = store.create("Selection Notes", "Notes", "Deliberate", "Goals",
                           parent="Ora → Experts → Expert selection", under=str(selection))
        notes = store.projects[key].root
        self.assertEqual(notes, selection / "Selection Notes")  # Selectable nested creation.
        self.assertEqual(sorted(path.name for path in notes.iterdir()),
                         ["Plan.md", "Project.md", "Registry.md", "Specification.md"])
        from ora_vibe_coder.project import not_started
        self.assertTrue(not_started((notes / "Specification.md").read_text()))
        self.assertIn("Parent: Ora → Experts → Expert selection", (notes / "Project.md").read_text())
        with self.assertRaises((OSError, ProjectError)):
            store.create("Selection Notes", "Again", "", "", under=str(selection))
        with self.assertRaises((OSError, ProjectError)):
            store.create("Experts", "Again", "", "", under=str(top))
        self.assertEqual((experts / "Project.md").read_text(encoding="utf-8"),
                         "# Project\n\nName: Experts\nParent: Ora\nProject state: ARCHIVED\n\n## Description\n\nSelection.\n")
        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, outside)
        with self.assertRaisesRegex(ProjectError, "inside the projects home"):
            store.create("Escape", "Escape", "", "", under=str(outside))
        self.assertFalse((outside / "Escape").exists())

    def test_hardlink_source_collision_and_sequential_framework_result_updates(self):
        project = self.project()
        source = project.root / "source.md"
        source.write_text("Source stays intact", encoding="utf-8")
        project.save_brief(project.brief_text(), "One", "", "", {"Plan": "source.md"})
        os.link(source, project.root / "Handoff.md")
        with self.assertRaises(ProjectError):
            project.save_packet("replacement")
        self.assertEqual(source.read_text(), "Source stays intact")
        atomic_write(project.root / "Project.md", project.brief_text().replace("Programming: NOT STARTED", "Programming: COMPLETE"))
        project.save_brief(project.brief_text(), "One", "After framework results", "Goals", {"Plan": "source.md"})
        self.assertIn("Programming: COMPLETE", project.brief_text())

    def test_approval_changed_notice_and_fresh_review_are_independent(self):
        from ora_vibe_coder.status import assessment_facts
        project = self.project()
        document = project.root / "Specification.md"
        template = document.read_text()
        supplied = project.approve_transition("create-plan", {"expected": template, "path": str(document)})
        self.assertIn("status: APPROVED", supplied["Specification"]["text"])
        blank_plan = project.root / "Plan.md"
        blank_plan.write_text("")
        supplied = project.approve_transition("implement-plan", {"expected": "", "path": str(blank_plan)})
        self.assertIn("status: APPROVED", supplied["Plan"]["text"])
        self.assertNotIn("review: PASSED", supplied["Plan"]["text"])
        initial = "---\nnexus:\n  - ora\nstatus: AWAITING APPROVAL\nreview: NOT PASSED\n---\n# Specification\n\n## Requirements\nKeep records for 30 days.\n\n## Current review\nVerdict: NOT PASSED\n\n- Delivery is unclear.\n"
        document.write_text(initial)
        saved, warning = project.approve_document("specification", initial, str(document))
        self.assertFalse(warning)
        self.assertIn("status: APPROVED", saved["text"])
        self.assertIn("review: NOT PASSED", saved["text"])
        self.assertIn("nexus:\n  - ora", saved["text"])
        from ora_vibe_coder.project import Project, Conflict
        reopened = Project(project.root)
        self.assertIsNotNone(reopened._approved_document("Specification", str(document)))
        with self.assertRaises(Conflict):
            reopened.approve_document("specification", initial, str(document))
        cosmetic = saved["text"].replace("## Requirements", "## **Requirements**").replace("30 days.", "30 days.  ")
        document.write_text(cosmetic)
        self.assertIsNone(reopened.document_change("specification"))
        renamed = saved["text"].replace("## Requirements", "## Expected behavior")
        document.write_text(renamed)
        self.assertEqual(reopened.document_change("specification")["state"], "changed")
        material = saved["text"].replace("30 days", "90 days")
        document.write_text(material)
        snapshot = reopened.snapshot()
        self.assertEqual(snapshot["assessments"]["specification"]["change"]["state"], "changed")
        self.assertIn("Plan may need updating", snapshot["plan_notice"])
        changed = document.read_text()
        self.assertIn("status: APPROVED", changed)  # The notice never rewrites the saved fields.
        self.assertNotIn("review: CHANGED", changed)
        self.assertIn("- Delivery is unclear.", changed)
        fresh = changed.replace("review: NOT PASSED", "review: PASSED")
        document.write_text(fresh)
        self.assertEqual(reopened.snapshot()["assessments"]["specification"]["verdict"], "PASSED")
        self.assertIn("status: APPROVED", document.read_text())
        approved = reopened.approve_transition("create-plan")["Specification"]
        self.assertIn("status: APPROVED", approved["text"])
        self.assertIn("review: PASSED", approved["text"])

    def test_approval_preserves_scope_qualification_and_changed_notice(self):
        project = self.project()
        document = project.root / "Plan.md"
        prefix = "---\r\nnexus:\r\n  - ora\r\ntags: [active]\r\n"
        qualified = prefix + "---\r\n# Plan\r\n\r\nStatus: AWAITING APPROVAL — Framework-only scope; public release remains on hold.\r\n\r\n## Approach\r\nUse the existing framework.\r\n"
        document.write_bytes(qualified.encode())
        approved, _warning = project.approve_document("planning", qualified, str(document))
        self.assertTrue(approved["text"].startswith(prefix))
        self.assertIn("Status: APPROVED — Framework-only scope; public release remains on hold.", approved["text"])
        self.assertEqual(project.document_change("planning"), None)
        from ora_vibe_coder.status import meaning_text
        self.assertEqual(meaning_text(qualified), meaning_text(approved["text"]))
        document.write_text(approved["text"].replace("Use the existing framework.", "Use the existing framework and its tests."))
        change = project.document_change("planning")
        self.assertEqual(change["state"], "changed")
        self.assertIn("changed since the recorded approval", change["reason"])
        self.assertIn("Status: APPROVED", document.read_text())

if __name__ == "__main__":
    unittest.main()
