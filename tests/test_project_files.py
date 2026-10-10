import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ora_vibe_coder.handoff import prepare_request
from ora_vibe_coder.project import Conflict, ProjectError, ProjectStore, atomic_write
from ora_vibe_coder.status import legacy_review_basis


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
        # Explicit rereview permits another save while preserving the result.
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
        expected = folder / "Work — 02 Specification.md"
        expected.write_text("# Specification\n\nStatus: DRAFT\n\n## Body\nBehavior.\n", encoding="utf-8")
        (folder / "notes.md").write_text(
            "---\nvibe_document: request\n---\n\n# Request\n\n## Description\nA useful product.\n\n## Goals\n- Ship it.\n",
            encoding="utf-8")
        (folder / "ordinary meta.md").write_text(
            "# Product Overview\n\nvibe_document: product overview\n\n## Overview\nWhat it is.\n", encoding="utf-8")
        fresh = folder / "fresh findings.md"
        stale = folder / "stale findings.md"
        fresh.write_text("# Findings\nfresh\n", encoding="utf-8")
        stale.write_text("# Findings\nstale\n", encoding="utf-8")
        (folder / "spec and plan.md").write_text("# Both roles\n", encoding="utf-8")
        (folder / "report.md").write_text("---\nvibe_document: specification\n---\n\n# Report\n", encoding="utf-8")
        (folder / "my spec draft.md").write_text("# Draft spec\n", encoding="utf-8")
        os.utime(fresh, (250, 250))
        os.utime(stale, (100, 100))
        # A recognized outgoing packet, renamed into the folder with a role word.
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
        self.assertEqual(documents["Request"]["name"], "notes.md")  # Label in closed frontmatter.
        self.assertEqual(documents["Product Overview"]["name"], "ordinary meta.md")  # Label in ordinary metadata.
        self.assertEqual(documents["Verification Findings"]["name"], fresh.name)  # Latest modification time.
        os.utime(stale, (300, 300))
        self.assertEqual(project.snapshot()["documents"]["Verification Findings"]["name"], stale.name)
        tie = folder / "a findings.md"
        tie.write_text("# Findings\ntie\n", encoding="utf-8")
        os.utime(tie, (300, 300))
        os.utime(stale, (300, 300))
        self.assertEqual(project.snapshot()["documents"]["Verification Findings"]["name"], tie.name)  # Stable tie order.
        self.assertIsNone(project.reference("Plan"))  # The outgoing packet is never a revision target.
        self.assertIsNone(project.material("Plan")["text"])
        conflicts = "\n".join(snapshot["discovery_conflicts"])
        self.assertIn("spec and plan.md", conflicts)  # Conflicting identity stays for Choose File.
        self.assertIn("report.md", conflicts)
        self.assertIsNone(snapshot["documents"]["Plan"]["path"])
        self.assertIsNone(snapshot["documents"]["Report"]["path"])  # Conflicted files are not proposed as outputs.
        sources = {source["name"]: source["sections"] for source in snapshot["overview_sources"]}
        self.assertIn("Description", sources["notes.md"])
        self.assertIn("Goals", sources["notes.md"])
        self.assertEqual(project.brief()["description"], "")

        # A deliberate association overrides discovery while its file exists.
        chosen = folder / "chosen.md"
        chosen.write_text("# Chosen specification\n", encoding="utf-8")
        project.save_brief(project.brief_text(), "Work", "", "", {"Specification": chosen.name})
        after = project.snapshot()
        self.assertEqual(after["documents"]["Specification"]["origin"], "association")
        self.assertEqual(after["documents"]["Specification"]["name"], chosen.name)
        self.assertEqual(project.material("Specification")["text"], "# Chosen specification\n")
        self.assertEqual(project.reference("Specification"), chosen)

    def test_newest_result_documents_supply_the_status_unless_explicitly_selected(self):
        project = self.project()
        old_result = project.root / "Programming Result.md"
        new_result = project.root / "Programming Result 2.md"
        old_report = project.root / "Verification Report.md"
        new_report = project.root / "Verification Report 2.md"
        old_result.write_text("# Result\n\nStatus: IN PROGRESS\n", encoding="utf-8")
        new_result.write_text("# Result\n\nStatus: complete — all work landed.\n", encoding="utf-8")
        old_report.write_text("# Report\n\nVerdict: NOT PASSED\n", encoding="utf-8")
        new_report.write_text("# Report\n\nVerdict: PASSED\n", encoding="utf-8")
        for path, time in ((old_result, 100), (new_result, 200), (old_report, 100), (new_report, 200)):
            os.utime(path, (time, time))
        saved = project.snapshot()
        self.assertEqual(saved["documents"]["Programming Result"]["path"], str(new_result))
        self.assertEqual(saved["documents"]["Verification Report"]["path"], str(new_report))
        self.assertEqual(saved["programming_result"]["status"]["kind"], "neutral")
        self.assertEqual(saved["verification"]["verdict"], "")
        self.assertIn("Programming Result.md: IN PROGRESS", saved["programming_result"]["status"]["reason"])
        self.assertIn("Verification Report 2.md: PASSED", saved["verification"]["status"]["reason"])
        self.assertEqual(saved["statuses"]["programming"]["label"], "NOT STARTED")
        project.save_brief(project.brief_text(), "One", "Description", "Goals",
                           {"Programming Result": old_result.name, "Verification Report": old_report.name})
        selected = project.snapshot()
        self.assertEqual(selected["documents"]["Programming Result"]["origin"], "association")
        self.assertEqual(selected["programming_result"]["status"]["label"], "IN PROGRESS")
        self.assertEqual(selected["verification"]["status"]["label"], "NOT PASSED")
        # Explicitly identifying the current copies resolves the ambiguity, too.
        project.save_brief(project.brief_text(), "One", "Description", "Goals",
                           {"Programming Result": new_result.name, "Verification Report": new_report.name})
        selected = project.snapshot()
        self.assertEqual(selected["programming_result"]["status"]["label"], "COMPLETE")
        self.assertEqual(selected["verification"]["status"]["label"], "PASSED")

    def test_retained_review_snapshot_establishes_legacy_applicability(self):
        project = self.project()
        path = project.root / "Specification.md"
        old = "---\nnexus: ora\ndate modified: 2026-10-04\n---\n\n# Specification\n\nStatus: DRAFT\n\n## Requirements\nKeep the work.\n"
        digest = legacy_review_basis(old)
        current = old.replace("DRAFT", "APPROVED").replace("2026-10-04", "2026-10-09")
        current += f"\n## Current review\nState: COMPLETE\nBasis: {digest}\n"
        path.write_text(current)
        self.assertEqual(project.snapshot()["assessments"]["specification"]["applies"], "unconfirmed")
        record = project.root / ".vibe/0001/session/messages/0002-initiator-to-peer.md"
        record.parent.mkdir(parents=True)
        record.write_text(f"# Review request\n\n## Specification\n\nSource:\n\n```text\n{path}\n```\n\n```text\n{old}\n```\n")
        before = path.read_text()
        assessment = project.snapshot()["assessments"]["specification"]
        self.assertEqual((assessment["verdict"], assessment["applies"]), ("COMPLETE", "current"))
        self.assertEqual(path.read_text(), before)  # No repair or restamping of the user's document.
        path.write_text(current.replace("Keep the work.", "Change the work."))
        self.assertEqual(project.snapshot()["assessments"]["specification"]["applies"], "earlier")

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
        # A definition directly in the discovery root, a legacy one without a
        # state field, and definitions nested beneath an archived parent.
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
        paused = home / "paused"
        paused.mkdir()
        (paused / "Project.md").write_text("# Project\n\nName: Paused\nProject state: paused\n", encoding="utf-8")
        # Unreadable definitions: oversize, linked, and (when not root) permission-locked.
        oversize = home / "oversize"
        oversize.mkdir()
        (oversize / "Project.md").write_text("# Project\n\nName: Big\n\n" + "x" * (256 * 1024 + 1), encoding="utf-8")
        linked = home / "linked"
        linked.mkdir()
        (linked / "Project.md").symlink_to(legacy / "Project.md")
        locked = home / "locked"
        locked.mkdir()
        (locked / "Project.md").write_text("# Project\n\nName: Locked\n", encoding="utf-8")
        os.chmod(locked / "Project.md", 0)
        self.addCleanup(os.chmod, locked / "Project.md", 0o644)
        readable = os.access(locked / "Project.md", os.R_OK)

        store = ProjectStore(home)
        entries = {entry["path"]: entry for entry in store.list(include_archived=True)}
        names = {entry["name"]: entry for entry in entries.values()}
        self.assertIn("Documents Root", names)   # Directly in the discovery root.
        self.assertIn("Legacy", names)           # Nested at depth.
        self.assertIn("Beneath", names)          # Discovery continues beneath archived parents.
        self.assertNotIn(str(oversize), entries)  # Oversize definition: noticed, not listed.
        self.assertNotIn(str(linked), entries)    # Linked definition: noticed, not listed.
        self.assertTrue(any("could not be read" in notice for notice in store.scan_notices))
        self.assertTrue(any("symbolic link" in notice for notice in store.scan_notices))
        if readable:  # Running as root cannot simulate an unreadable file.
            self.assertIn("Locked", names)
        else:
            self.assertNotIn(str(locked), entries)
        # Archive state: missing means active without rewriting that file.
        self.assertTrue(names["Old"]["archived"])
        self.assertFalse(names["Legacy"]["archived"])
        self.assertFalse(names["Paused"]["archived"])  # Only unambiguous ARCHIVED archives.
        self.assertIn("paused", names["Paused"]["notice"])
        self.assertEqual(names["Documents Root"]["label"], "Ora → Documents Root")
        self.assertEqual((legacy / "Project.md").read_text(), legacy_definition)
        # Archive filtering keeps archived projects out of the default list.
        active = {entry["name"] for entry in store.list()}
        self.assertNotIn("Old", active)
        self.assertIn("Legacy", active)
        self.assertIn("Beneath", active)

        # Moving a definition out and removing one updates the inventory after a rescan,
        # while the open handle and its unsaved session are not discarded.
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
        # A new subproject's Parent copies the lineage, never the position.
        entry = next(e for e in ProjectStore(self.home).list() if e["position"] == "G1.3")
        self.assertEqual(entry["lineage"], "Ora → ORA-200 — Fix defects")
        # Saving the project's brief keeps the position line.
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
        starters = sorted(path.name for path in notes.iterdir())
        self.assertEqual(starters, ["Plan.md", "Project.md", "Registry.md", "Specification.md"])
        for filename in starters:
            self.assertTrue((notes / filename).is_file())
        # Starter templates carry identification and empty headings, nothing invented.
        registry = (notes / "Registry.md").read_text(encoding="utf-8")
        self.assertIn("# Notes — Registry", registry)
        self.assertIn("## Notes", registry)
        self.assertNotIn("APPROVED", registry)
        self.assertNotIn("PASSED", (notes / "Specification.md").read_text(encoding="utf-8"))
        from ora_vibe_coder.project import not_started
        self.assertTrue(not_started(registry))
        self.assertEqual(sorted(path.name for path in experts.rglob("*")),
                         ["Plan.md", "Project.md", "Project.md", "Project.md", "Registry.md",
                          "Selection", "Selection Notes", "Specification.md"])
        entry = next(entry for entry in store.list(include_archived=True) if entry["path"] == str(notes))
        self.assertEqual(entry["label"], "Ora → Experts → Expert selection → Notes")
        self.assertFalse(entry["archived"])  # New projects default to active.
        definition = (notes / "Project.md").read_text(encoding="utf-8")
        self.assertIn("Parent: Ora → Experts → Expert selection\n", definition)
        self.assertIn("Project state: ACTIVE\n", definition)
        self.assertIn("## Description\n\nDeliberate\n\n## Desired outcome\n\nGoals\n\n", definition)
        # The optional description and desired outcome may stay blank.
        blank = store.create("Blank Notes", "Blank Notes", "", "", under=str(selection))
        self.assertIn("## Description\n\n## Desired outcome\n\n## Artifact Paths",
                      (store.projects[blank].root / "Project.md").read_text(encoding="utf-8"))
        # The sort stays stable for identical labels: the folder path breaks the tie.
        twin_a, twin_b = self.home / "twin-a", self.home / "twin-b"
        twin_a.mkdir(); twin_b.mkdir()
        (twin_a / "Project.md").write_text("# Project\n\nName: Twin\n", encoding="utf-8")
        (twin_b / "Project.md").write_text("# Project\n\nName: Twin\n", encoding="utf-8")
        store.rescan()
        twins = [entry["path"] for entry in store.list(include_archived=True) if entry["name"] == "Twin"]
        self.assertEqual(twins, [str(twin_a), str(twin_b)])

        # An existing destination is never reused or overwritten.
        with self.assertRaises((OSError, ProjectError)):
            store.create("Selection Notes", "Again", "", "", under=str(selection))
        with self.assertRaises((OSError, ProjectError)):
            store.create("Experts", "Again", "", "", under=str(top))
        self.assertEqual((experts / "Project.md").read_text(encoding="utf-8"),
                         "# Project\n\nName: Experts\nParent: Ora\nProject state: ARCHIVED\n\n## Description\n\nSelection.\n")
        # Destinations outside the discovery boundary are refused server-side.
        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, outside)
        with self.assertRaisesRegex(ProjectError, "inside the projects home"):
            store.create("Escape", "Escape", "", "", under=str(outside))
        self.assertFalse((outside / "Escape").exists())
        # A failure partway through creation removes only that attempt's files;
        # earlier real files and the existing destination are preserved.
        from ora_vibe_coder import project as project_module
        original_write = project_module.atomic_write
        writes = []
        def failing_write(path, text):
            writes.append(Path(path).name)
            if len(writes) == 3:  # After Project.md and Registry.md, before Specification.md.
                raise OSError("disk failure")
            return original_write(path, text)
        with patch.object(project_module, "atomic_write", side_effect=failing_write):
            with self.assertRaises(OSError):
                store.create("Broken", "Broken", "", "")
        self.assertEqual(writes[:2], ["Project.md", "Registry.md"])
        self.assertFalse((selection / "Broken").exists())
        self.assertTrue((notes / "Project.md").is_file())  # The earlier creation is untouched.
        self.assertEqual((experts / "Project.md").read_text(encoding="utf-8"),
                         "# Project\n\nName: Experts\nParent: Ora\nProject state: ARCHIVED\n\n## Description\n\nSelection.\n")

    def test_hardlink_source_collision_and_sequential_framework_result_updates(self):
        project = self.project()
        source = project.root / "source.md"
        source.write_text("Source stays intact", encoding="utf-8")
        project.save_brief(project.brief_text(), "One", "", "", {"Plan": "source.md"})
        os.link(source, project.root / "Handoff.md")
        with self.assertRaises(ProjectError):
            project.save_packet("replacement")
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
