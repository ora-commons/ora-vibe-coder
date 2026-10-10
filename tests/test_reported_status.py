import tempfile
from pathlib import Path
import unittest

from ora_vibe_coder.project import ProjectStore
from ora_vibe_coder.status import (QUALITY, VALUES, assessment_facts, reported_status, reported_verdict,
                                   review_basis, legacy_review_basis, read_conclusion)


class ReportedStatus(unittest.TestCase):
    def status(self, stage, text):
        return reported_status(stage, text, "selected current file")

    def test_all_exact_values_and_legacy_approval(self):
        positive = {"APPROVED", "Approved product specification", "Approved Implementation Plan", "COMPLETE", "PASSED"}
        for stage, values in VALUES.items():
            field = {"programming": "Programming", "verification": "Verification"}.get(stage, "Status")
            for value in values:
                with self.subTest(stage=stage, value=value):
                    result = self.status(stage, f"# Current document\r\n\r\n**{field}:** {value}  \\\r\n\r\n## Body\r\n")
                    self.assertEqual(result["literal"], value)
                    self.assertEqual(result["kind"] == "positive", value in positive)
                    self.assertEqual(result["source"], "selected current file")

    def test_quoted_code_body_duplicate_and_malformed_never_approve(self):
        samples = ["# Title\n\n## Body\nStatus: APPROVED", "> Status: APPROVED", "```\nStatus: APPROVED\n```",
                   "Ordinary body\nStatus: APPROVED", "Status: APPROVED\nStatus: DRAFT", "Status:", "Status: PASSED",
                   "Status: approved", "Status: APPROVED someday", "", "- Status: APPROVED"]
        for text in samples:
            with self.subTest(text=text):
                self.assertNotEqual(self.status("specification", text)["kind"], "positive")
        self.assertEqual(self.status("planning", "Status: Approved Implementation Plan\n\n## Body")["kind"], "positive")
        self.assertEqual(self.status("specification", "**Status**: `APPROVED`\n")["kind"], "positive")
        for stage, field, value in (("specification", "Status", "APPROVED"), ("planning", "Status", "APPROVED"),
                                    ("programming", "Programming", "COMPLETE"), ("verification", "Verification", "PASSED")):
            for heading in ("# Example from an earlier project", "## Example from an earlier project"):
                with self.subTest(stage=stage, heading=heading):
                    text = f"# Current document\n\n{heading}\n{field}: {value}\n"
                    self.assertEqual(self.status(stage, text)["label"], "Not reported")
                    text = f"# Current document\nDate: September 4\n\n{heading}\n{field}: {value}\n"
                    self.assertEqual(self.status(stage, text)["label"], "Not reported")
            for fence in ("```", "````", "~~~"):
                for indent in ("", "   "):
                    with self.subTest(stage=stage, fence=fence, indent=indent):
                        text = f"# Title\nDate: September 4\n\n{indent}{fence}{field}: {value}\n{field}: {value}\n{fence}\n"
                        self.assertEqual(self.status(stage, text)["label"], "Not reported")
            for indent in ("    ", "\t", "  \t", "        "):
                with self.subTest(stage=stage, indent=indent):
                    text = f"# Title\n\n{indent}{field}: {value}\n{field}: {value}\n"
                    self.assertEqual(self.status(stage, text)["label"], "Not reported")
                    text = f"# Title\nDate: September 4\n\n{indent}{field}: {value}\n"
                    self.assertEqual(self.status(stage, text)["label"], "Not reported")
        self.assertEqual(self.status("specification", "Status: DRAFT\n\n    Status: APPROVED")["label"], "DRAFT")

    def test_yaml_frontmatter_does_not_supply_or_hide_body_status(self):
        for stage, field, approved in (("specification", "Status", "APPROVED"), ("planning", "Status", "APPROVED"),
                                       ("programming", "Programming", "COMPLETE"), ("verification", "Verification", "PASSED")):
            for newline in ("\n", "\r\n", "\r"):
                for closing in ("---", "..."):
                    with self.subTest(stage=stage, newline=newline, closing=closing):
                        frontmatter = f"---\n{field}: {approved}\ntags: [project]\n{closing}\n\n".replace("\n", newline)
                        body = f"# Current document\n\n{field}: IN PROGRESS\n\n## Body\n{field}: {approved}\n".replace("\n", newline)
                        self.assertEqual(self.status(stage, frontmatter + body)["label"], "IN PROGRESS")
                        self.assertEqual(self.status(stage, frontmatter + body.replace("IN PROGRESS", approved))["kind"], "positive")
                        self.assertEqual(self.status(stage, frontmatter)["label"], "Not reported")
                        self.assertEqual(self.status(stage, frontmatter + f"## Example\n{field}: {approved}")["label"], "Not reported")
                        self.assertEqual(self.status(stage, frontmatter + f"{field}: {approved}\n{field}: IN PROGRESS")["kind"], "neutral")
            self.assertEqual(self.status(stage, f"---\n{field}: {approved}\n")["label"], "Not reported")

    def test_verification_only_reads_own_overview_field_not_prior_report(self):
        # The saved Verification Report governs the displayed verdict; the
        # Project.md Verification field is retained legacy history.
        report = "# Verification Report\n\nVerdict: PASSED\n\n## Findings\n\nNone.\n"
        self.assertEqual(reported_verdict(report), "PASSED")
        # Quoted code, body prose, and duplicated fields never supply a verdict.
        for text in ["# Report\n\n## Body\nVerdict: PASSED", "> Verdict: PASSED",
                     "```\nVerdict: PASSED\n```", "Verdict: PASSED\nVerdict: NOT PASSED",
                     "Verdict:", ""]:
            with self.subTest(text=text[:30]):
                self.assertEqual(reported_verdict(text), "")
        home = Path(tempfile.mkdtemp()).resolve()
        store = ProjectStore(home)
        project = store.projects[store.create("One", "One", "", "")]
        (project.root / "Verification Report.md").write_text(report, encoding="utf-8")
        definition = project.brief_text().replace("Verification: NOT STARTED", "Verification: NOT PASSED")
        (project.root / "Project.md").write_text(definition, encoding="utf-8")
        snapshot = project.snapshot()
        self.assertEqual(snapshot["verification"]["verdict"], "PASSED")  # The report governs.
        self.assertEqual(snapshot["verification"]["legacy_field"], "NOT PASSED")  # Labeled legacy, not overriding.
        self.assertEqual(snapshot["statuses"]["verification"]["literal"], "NOT PASSED")  # Reported as saved, not success.
        for value in QUALITY - {"PASSED"}:
            self.assertNotEqual(self.status("verification", f"Verification: {value}")["kind"], "positive")

    def test_bold_result_fields_with_explanations(self):
        result = "# Programming Result\n\n**State: COMPLETE — verification PASSED** (latest round)\n\n## Work\nDone.\n"
        status = reported_status("programming", result, "result.md", field="Status")
        self.assertEqual((status["label"], status["kind"]), ("COMPLETE", "positive"))
        report = "# Verification Report\n\n**Verdict: PASSED** (latest completed review)\n\n## Findings\nNone.\n"
        status = reported_status("verification", report, "report.md", field="Verdict")
        self.assertEqual((status["label"], status["kind"], reported_verdict(report)),
                         ("PASSED", "positive", "PASSED"))
        sentence_verdict = ("# ORA-230 — Verification Report\n\n"
                            "**Verdict: PASSED.** The delivered release meets the supplied requirements.\n\n"
                            "## Earlier review\n\nVerdict: NOT PASSED\n")
        self.assertEqual(reported_status("verification", sentence_verdict, "report.md", field="Verdict")["label"], "PASSED")
        self.assertEqual(reported_verdict(sentence_verdict), "PASSED")
        self.assertNotEqual(reported_status("verification", "Verdict: PASSED. But two checks failed.\n",
                                            "report.md", field="Verdict")["kind"], "positive")
        self.assertNotEqual(reported_status("verification", "Verdict: PASSED. Actually NOT PASSED.\n",
                                            "report.md", field="Verdict")["kind"], "positive")
        # Conflicting opening records and a mere prose claim must not complete a project.
        conflicting = "Status: INCOMPLETE\nState: COMPLETE\n"
        self.assertEqual(reported_status("programming", conflicting, "result.md", field="Status")["kind"], "neutral")
        self.assertEqual(reported_status("programming", "Completed the work.\n", "result.md", field="Status")["kind"], "neutral")
        recorded = "# Programming Result\n\nProgramming: COMPLETE (merged to vault main; see Delivery).\n\n## Delivery\nDone.\n"
        status = reported_status("programming", recorded, "result.md", field="Status")
        self.assertEqual((status["label"], status["kind"]), ("COMPLETE", "positive"))
        conflicting = "Programming: COMPLETE (merged to vault main).\nStatus: INCOMPLETE\n"
        self.assertEqual(reported_status("programming", conflicting, "result.md", field="Status")["kind"], "neutral")

    def test_current_review_and_separate_approval(self):
        request = "# Request\n\n## Goals\nDeliver the product.\n"
        specification = "# Specification\n\nStatus: IN PROGRESS\n\n## Body\n\nThe product behaves.\n"
        basis = review_basis(specification, request)
        self.assertEqual(basis, review_basis(specification.replace("Status: IN PROGRESS", "Status: AWAITING APPROVAL"), request))
        # An assessment is advisory and judged against the assessed document's
        # own substantive content, never against governing or Registry material.
        own_basis = review_basis(specification)
        assessed = ("# Specification\n\nStatus: IN PROGRESS\n\n## Current review\n\n"
                    f"Stage: Specification\nVerdict: COMPLETE\nBasis: {own_basis}\nBasis format: content-v2\n\n## Body\n\nThe product behaves.\n")
        facts = assessment_facts("specification", assessed)
        self.assertEqual(facts["verdict"], "COMPLETE")
        self.assertTrue(facts["issues"] == [])
        self.assertEqual(facts["applies"], "current")
        self.assertFalse(assessment_facts("specification", specification)["present"])
        self.assertFalse(assessment_facts("specification", "")["present"])
        # Recording an assessment, a status, or a type marker changes no basis.
        self.assertEqual(review_basis(assessed), own_basis)
        self.assertEqual(review_basis("---\nvibe_document: specification\n---\n" + assessed), own_basis)
        # Registry notes and upstream documents never participate in the
        # applicability; only the assessed document's own content does.
        self.assertEqual(assessment_facts("specification", assessed)["applies"], "current")
        # A later change to the assessed document identifies the assessment as
        # applying to an earlier version — it never blocks anything.
        changed = assessed.replace("The product behaves.", "The product behaves differently.")
        later = assessment_facts("specification", changed)
        self.assertEqual(later["verdict"], "COMPLETE")
        self.assertEqual(later["applies"], "earlier")
        self.assertEqual(later["basis"], own_basis)
        # INCOMPLETE counts its actual noted deficiencies; a missing list is an
        # unknown count, never zero.
        incomplete = assessed.replace("Verdict: COMPLETE", "Verdict: INCOMPLETE").replace(
            "## Body", "- First gap.\n- Second gap.\n- Third gap.\n\n## Body")
        counted = assessment_facts("specification", incomplete)
        self.assertEqual((counted["verdict"], counted["findings"], counted["applies"]), ("INCOMPLETE", 3, "current"))
        self.assertIsNone(assessment_facts("specification", assessed.replace("Verdict: COMPLETE", "Verdict: INCOMPLETE"))["findings"])
        # Legacy verdict vocabulary stays untranslated, and its multi-document
        # basis cannot claim which document changed: applicability is unconfirmed.
        legacy = assessed.replace("Verdict: COMPLETE", "Verdict: PASSED").replace(f"Basis: {own_basis}", f"Basis: {basis}")
        saved = assessment_facts("specification", legacy)
        self.assertEqual((saved["verdict"], saved["applies"]), ("PASSED", "unconfirmed"))
        changed_legacy = assessment_facts("specification", legacy.replace("The product behaves.", "Rewritten."))
        self.assertEqual(changed_legacy["applies"], "unconfirmed")  # Not a claim the document changed.
        # A present-but-broken record is not NOT REVIEWED.
        for broken in [
                assessed.replace(f"Basis: {own_basis}", "Basis: not-a-digest"),
                assessed.replace("Stage: Specification", "Stage: Plan"),
                assessed + f"\n## Current review\n\nStage: Specification\nVerdict: COMPLETE\nBasis: {own_basis}\n",
                assessed.replace("Verdict: COMPLETE", "Verdict: COMPLETE\nVerdict: INCOMPLETE"),
        ]:
            with self.subTest(text=broken[:60]):
                self.assertTrue(assessment_facts("specification", broken)["present"])
                self.assertTrue(assessment_facts("specification", broken)["issues"])
        unconfirmed = assessment_facts("specification", assessed.replace(f"Basis: {own_basis}\n", ""))
        self.assertEqual((unconfirmed["verdict"], unconfirmed["applies"], unconfirmed["issues"]),
                         ("COMPLETE", "unconfirmed", []))

    def test_explanatory_basis_with_one_matching_sha256(self):
        for stage, label in (("specification", "Specification"), ("planning", "Plan")):
            document = f"# {label}\n\nThe intended work is defined.\n"
            explanatory = (document + f"\n## Current review\n\nStage: {label}\nVerdict: COMPLETE\n"
                           f"Basis: I read the current {label}; its SHA-256 content hash is `<basis>`.\nBasis format: content-v2\n")
            basis = review_basis(explanatory)
            explanatory = explanatory.replace("<basis>", basis)
            with self.subTest(stage=stage):
                facts = assessment_facts(stage, explanatory)
                self.assertEqual((facts["verdict"], facts["applies"], facts["issues"]), ("COMPLETE", "current", []))
                self.assertEqual(assessment_facts(stage, explanatory.replace("The intended work is defined.", "The work changed."))["applies"], "earlier")
                duplicate = explanatory.replace(f"`{basis}`", f"`{basis}` and `{basis}`")
                self.assertTrue(assessment_facts(stage, duplicate)["issues"])
                no_algorithm_name = explanatory.replace("SHA-256 content hash", "unidentified hash")
                self.assertEqual(assessment_facts(stage, no_algorithm_name)["applies"], "current")

    def test_current_review_accepts_clear_basis_label_variants_without_false_currency(self):
        for stage, label in (("specification", "Specification"), ("planning", "Plan")):
            with self.subTest(stage=stage):
                document = f"# {label}\n\n## Scope\n\nBuild the current work.\n"
                reviewed = (document + f"\n## Current review\n\nVerdict: COMPLETE — ready for the next step\n"
                            f"Basis as supplied: `<basis>`\nBasis format: content-v2\n\nThe current {label} is sufficient.\n")
                basis = review_basis(reviewed)
                reviewed = reviewed.replace("<basis>", basis)
                facts = assessment_facts(stage, reviewed)
                self.assertEqual((facts["verdict"], facts["applies"], facts["issues"]),
                                 ("COMPLETE", "current", []))
                changed = reviewed.replace("Build the current work.", "Build different work.")
                self.assertEqual(assessment_facts(stage, changed)["applies"], "earlier")
                conflicting = reviewed.replace(f"`{basis}`", f"`{basis}` and `{'a' * 64}`")
                self.assertTrue(assessment_facts(stage, conflicting)["issues"])

    def test_report_conclusions_allow_explanations_but_not_old_rounds_or_conflicts(self):
        result = "# Programming Result\n\nResult: COMPLETE — all planned work landed.\n\n## Earlier work\nStatus: INCOMPLETE\n"
        report = "# Verification Report\n\nFinal verdict: PASSED — current candidate.\n\n## Round 1\nVerdict: NOT PASSED\n"
        self.assertEqual(reported_status("programming", result, "result.md", field="Status")["label"], "COMPLETE")
        self.assertEqual(reported_status("verification", report, "report.md", field="Verdict")["label"], "PASSED")
        self.assertEqual(reported_verdict(report), "PASSED")
        real_opening = ("---\ntags:\n---\n# ORA-230 — Programming Result\n\n"
                        "Programming completed 8 October 2026 under the approved ORA-230 Plan. "
                        "The Specification remains a draft with an advisory COMPLETE review.\n\n"
                        "## Work performed\n\nThe Loop reviewer returned Verdict: DONE.\n")
        self.assertEqual(reported_status("programming", real_opening, "result.md", field="Status")["label"], "COMPLETE")
        self.assertEqual(reported_status("programming", "# Result\n\nProgramming stopped unfinished.\n\n## Old review\nVerdict: COMPLETE\n",
                                         "result.md", field="Status")["label"], "INCOMPLETE")
        self.assertEqual(reported_status("verification", "# Report\n\nVerification passed on the current candidate.\n",
                                         "report.md", field="Verdict")["label"], "PASSED")
        for misleading in ("Verification passed 3 of 5 checks and failed 2.",
                           "Verification passed earlier, but the current candidate failed."):
            self.assertNotEqual(reported_status("verification", f"# Report\n\n{misleading}\n",
                                                "report.md", field="Verdict")["kind"], "positive")
        self.assertNotEqual(reported_status("programming", "# Result\n\nProgramming completed except for the export step.\n",
                                            "result.md", field="Status")["kind"], "positive")
        self.assertEqual(reported_status("programming", "# Result\n\nThe Specification review is COMPLETE.\n\nProgramming is unfinished.\n",
                                         "result.md", field="Status")["label"], "INCOMPLETE")
        self.assertNotEqual(reported_status("verification", "# Report\n\n## Round 1\nVerdict: PASSED\n",
                                            "report.md", field="Verdict")["kind"], "positive")
        self.assertNotEqual(reported_status("verification", "Verdict: NOT PASSED\nFinal verdict: PASSED\n",
                                            "report.md", field="Verdict")["kind"], "positive")
        self.assertNotEqual(reported_status("verification", "Verdict: PASSED — NOT PASSED\n",
                                            "report.md", field="Verdict")["kind"], "positive")
        self.assertNotEqual(reported_status("programming", "Result: COMPLETE — INCOMPLETE\n",
                                            "result.md", field="Status")["kind"], "positive")

    def test_shared_current_conclusion_wording_and_conflicts(self):
        for stage, word in (("programming", "COMPLETE"), ("verification", "PASSED")):
            for label in ("Status", "State", "Verdict"):
                text = f"---\nnexus:\n  - ora\n---\n\n# Current result\n\n**{label}: {word.lower()}.** All current work is recorded.\n"
                result = read_conclusion(stage, text)
                self.assertEqual(result["label"], word)
                self.assertIn(label, result["evidence"][0])
            self.assertEqual(read_conclusion(stage, f"## Current result\n\n{word}\n")["label"], word)
            self.assertEqual(read_conclusion(stage, f"Status: {word}\nVerdict: {word}.\n")["label"], word)
            for text in (f"**Status: {word}.** But two checks failed.",
                         f"Status: {word}\n\nBut the export is unfinished.",
                         f"Status: {word}\n\n## Current result\nStatus: INCOMPLETE",
                         f"# Report\n\n## Historical round\n{word}",
                         f"# Report\n\n## Earlier review\n### Result\nStatus: {word}",
                         f"# Report\n\n## Example\n### Current result\nStatus: {word}",
                         f"# Report\n\n```markdown\n## Current result\n{word}\n```",
                         f"> ## Current result\n> {word}"):
                with self.subTest(stage=stage, text=text):
                    self.assertEqual(read_conclusion(stage, text)["label"], "")
        # ORA-231: later independent report is clear; its older result belongs to another document.
        self.assertEqual(reported_verdict("# ORA-231 — Verification Report\n\nStatus: PASSED\n\n## Result\n"
                                         "The fresh independent review found no material findings.\n"), "PASSED")
        # ORA-199: explicitly current synthesis plus historical failed rounds.
        report = ("# ORA-199 — Verification Report\n\n**Verdict: PASSED** (latest completed review: round 5; "
                  "rounds 4–5 closed the findings with none remaining.)\n\n"
                  "## Round 1 — historical\nVerdict: NOT PASSED\n")
        self.assertEqual(reported_verdict(report), "PASSED")
        self.assertEqual(reported_verdict("Status: PASSED\n\n## Earlier review\n### Result\n"
                                         "Verdict: NOT PASSED\n\n## Current result\nVerdict: PASSED\n"), "PASSED")
        self.assertEqual(read_conclusion("verification", "Status: COMPLETE")["label"], "")
        for stage in ("specification", "planning"):
            self.assertEqual(read_conclusion(stage, "## Current review\nState: complete.", review=True)["label"], "COMPLETE")
            self.assertNotEqual(reported_status(stage, "Status: COMPLETE", "file")["kind"], "positive")
            example = "# Guide\n\n```markdown\n## Current review\nVerdict: COMPLETE\n```\n"
            self.assertFalse(assessment_facts(stage, example)["present"])
            conflict = "# Plan\n\n## Current review\nVerdict: PASSED\nStatus: INCOMPLETE\n"
            self.assertTrue(assessment_facts(stage, conflict)["issues"])
        old_report = "Verdict: PASSED\n\n## Readiness\nThis is the current independent verdict for revision `38a5ceb5980868d14c48a2c11b4b0855edb5ce73`."
        self.assertIn("38a5ceb", reported_status("verification", old_report, "report", field="Verdict")["basis_note"])

    def test_managed_recording_changes_and_retained_legacy_review(self):
        document = "---\nnexus: ora\ndate created: 2026-10-04\ndate modified: 2026-10-04\n---\n\n# Specification\n\nStatus: DRAFT\n\n## Requirements\nKeep the user's work.\n"
        changed_record = document.replace("Status: DRAFT", "Status: APPROVED").replace("date modified: 2026-10-04", "date modified: 2026-10-09")
        self.assertEqual(review_basis(document), review_basis(changed_record))
        legacy = legacy_review_basis(document)
        reviewed = changed_record + f"\n## Current review\nVerdict: COMPLETE\nBasis: `{legacy}` (as supplied)\n"
        facts = assessment_facts("specification", reviewed, [document])
        self.assertEqual((facts["verdict"], facts["applies"]), ("COMPLETE", "current"))
        self.assertIn("recording details", facts["reason"])
        substantive = reviewed.replace("Keep the user's work.", "Delete the user's work.")
        self.assertEqual(assessment_facts("specification", substantive, [document])["applies"], "earlier")
        self.assertEqual(assessment_facts("specification", reviewed)["applies"], "unconfirmed")
        modern = document + f"\n## Current review\nVerdict: COMPLETE\nBasis: {review_basis(document)}\nBasis format: content-v2\n"
        self.assertEqual(assessment_facts("specification", modern)["applies"], "current")
        self.assertEqual(assessment_facts("specification", modern.replace("Keep the user's work.", "Delete it."))["applies"], "earlier")


if __name__ == "__main__":
    unittest.main()
