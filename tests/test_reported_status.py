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

    def test_canonical_yaml_and_vault_metadata_are_read_without_rewriting(self):
        for stage, value in (("specification", "APPROVED"), ("planning", "AWAITING APPROVAL"),
                             ("programming", "PASSED"), ("verification", "INCOMPLETE")):
            text = f"---\nnexus:\n  - ora\ntags: [active]\nstatus: {value}\n---\n# Document\n\nContent.\n"
            self.assertEqual(reported_status(stage, text, "source", field="Status")["label"], value)
        for text in ("---\nstatus: PASSED\nstatus: PASSED\n---\n", "---\nstatus: mystery\n---\n",
                     "---\nstatus: PASSED\n", "---\nstatus PASSED\n---\n",
                     '---\nstatus: PASSED\nowner: "unclosed\n---\n',
                     "---\nstatus: PASSED\ntags: [unclosed\n---\n",
                     "---\nstatus: PASSED\n  nested: invalid\n---\n",
                     "---\nstatus: PASSED\nowner: invalid: scalar\n---\n"):
            self.assertFalse(reported_status("programming", text, "source", field="Status")["label"] == "PASSED")
        for review in ("PASSED", "NOT PASSED", "INCOMPLETE", "CHANGED"):
            text = f"---\nstatus: APPROVED\nreview: {review}\n---\n# Specification\n\nBuild useful behavior.\n"
            facts = assessment_facts("specification", text)
            self.assertEqual(facts["outcome"], review)
            self.assertFalse(facts["issues"])
        from ora_vibe_coder.project import not_started
        recorded = ("# Document\n\nvibe_document: specification\nStatus: DRAFT\nReview:\n"
                    "Date: October 20\n\n## Requirements\n")
        self.assertTrue(not_started(recorded))
        for content in ("Summary: Implemented record export.", "**Summary:** Implemented record export.",
                        "Requirements: Preserve all records.", "Approach: Reuse the existing exporter."):
            with self.subTest(opening_content=content):
                self.assertFalse(not_started(f"# Document\n\n{content}\n"))
                self.assertFalse(not_started(recorded.replace("\n## Requirements", f"\n{content}\n\n## Requirements")))
        for empty in ("", "null", "Null", "NULL", "~", "null # unset"):
            self.assertFalse(assessment_facts("specification", f"---\nstatus: DRAFT\nreview: {empty}\n---\n# Specification\n")["present"])
            for stage, field in (("programming", "Status"), ("verification", "Verdict")):
                blank = f"---\nstatus: {empty}\nreview: null\n---\n# Report\n\n## Findings\n"
                self.assertEqual(reported_status(stage, blank, "source", field=field)["label"], "Not reported")
                self.assertTrue(not_started(blank))
                substantive = blank + "\nRequired evidence is missing.\n"
                self.assertFalse(not_started(substantive))
                self.assertEqual(reported_status(stage, substantive, "source", field=field)["label"], "Not reported")
        for invalid in ('"null"', "'~'", "arbitrary", "\nstatus:", "\n  verdict: PASSED"):
            text = f"---\nstatus: {invalid}\n---\n# Report\n\n## Findings\n"
            for stage in ("programming", "verification"):
                self.assertTrue(reported_status(stage, text, "source", field="Status")["label"].startswith("Unknown"), text)
        for record in ("review: PASSED\nreview: PASSED", "review: arbitrary", 'review: "null"', "review:\n  verdict: PASSED"):
            self.assertTrue(assessment_facts("planning", f"---\n{record}\n---\n# Plan\n")["issues"])

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
        self.assertEqual(later["applies"], "unconfirmed")
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
                self.assertEqual(assessment_facts(stage, explanatory.replace("The intended work is defined.", "The work changed."))["applies"], "unconfirmed")
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
                self.assertEqual(assessment_facts(stage, changed)["applies"], "unconfirmed")
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
            for body in ("## Current outcome\nVerdict: NOT PASSED\n",
                         "## Current outcome\nVerdict: PASSED — but required checks failed.\n",
                         "## Current outcome\nPASSED\n\nHowever the export is unfinished.\n"):
                canonical = "---\nstatus: PASSED\n---\n# Report\n\n" + body
                self.assertEqual(read_conclusion(stage, canonical)["label"], "")
                self.assertNotEqual(reported_status(stage, canonical, "report", field="Status")["kind"], "positive")
            canonical = f"---\nstatus: PASSED\n---\n# Report\n\n## Current outcome\nVerdict: {word}\n\n## Earlier review\nVerdict: NOT PASSED\n"
            self.assertEqual(read_conclusion(stage, canonical)["label"], "PASSED")
            for text in (f"**Status: {word}.** But two checks failed.",
                         f"Status: {word}\n\nBut the export is unfinished.",
                         f"Status: {word}\n\nNOT PASSED after rerun: two checks fail.",
                         f"Status: {word}\n\nIN PROGRESS because required checks are running.",
                         f"Status: {word}\n\nHowever, I retract this verdict.",
                         f"Status: {word}\n\nThis verdict is withdrawn.",
                         f"Status: {word}\n\nI retract this verdict.",
                         f"Status: {word}\n\n{word} was premature.",
                         f"Status: {word}\n\n{word} isn't justified yet.",
                         f"Status: {word}\n\n{word} cannot be confirmed yet.",
                         f"Status: {word}\n\n{word} proved illusory.",
                         f"Status: {word} — it can’t be confirmed yet.",
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
            for body in ("Verdict: PASSED\nStatus: INCOMPLETE\n",
                         "Verdict: PASSED — but required decisions are missing.\n",
                         "Verdict: PASSED\n\nThe review failed.\n",
                         "Verdict: PASSED\n\nHowever the delivery choice is unfinished.\n"):
                canonical = "---\nstatus: APPROVED\nreview: PASSED\n---\n# Document\n\n## Current review\n" + body
                facts = assessment_facts(stage, canonical)
                self.assertTrue(facts["issues"], body)
        for stage in ("specification", "planning"):
            for explanation in (
                "Complete reviewer evidence and source authority have concrete implementation routes.",
                "Complete source evidence supports the implementation route.",
                "Complete rollback evidence exists for the planned migration route.",
                "PASSED means the available Plan is sufficient to guide the intended work.",
                "PASSED means the reviewed Plan is sufficient for the next step.",
                "Complete reviewer evidence and source authority have concrete implementation routes. "
                "Reviewer material is supplied at the existing input points while retaining each review procedure. "
                "Supplementary data keeps its attribution. If that route cannot preserve protected instructions, "
                "the conflict returns to the owner before the dependent change proceeds. "
                "Changes to active rejection rules remain reserved for the owner's decision.",
                "Complete recovery evidence supports the planned route. The existing backup preserves each file. "
                "If a restore cannot retain the original meaning, the owner decides before work proceeds.",
                "PASSED means the available Plan is sufficient to guide the intended work. "
                "It does not verify implementation, independently establish complete Specification coverage, "
                "grant approval or block any stage.",
                "PASSED means the reviewed Plan can guide the next stage. "
                "This explanation does not certify working software or grant permission to start.",
                "Earlier I retracted the prior verdict. The present review is separate.",
                'The reviewer quoted "I retract this verdict." as a historical example.',
                "If new evidence appears, retract this verdict before proceeding.",
                "I will withdraw this verdict if later evidence conflicts with it.",
                "This is planning-only evidence; it does not certify unbuilt software."):
                text = "## Current review\nVerdict: PASSED\n\n" + explanation
                self.assertEqual(read_conclusion(stage, text, review=True)["label"], "PASSED", text)
            for definition in ("means", "establishes", "denotes", "indicates"):
                text = ("## Current review\nVerdict: PASSED\n\nNo required deficiencies found. "
                        "This assessment uses the supplied Plan and Registry, independently of their recorded reviews. "
                        "I did not inspect the underlying code, separate Specification or production state, or run checks. "
                        f"PASSED {definition} planning sufficiency; it does not verify implementation or grant approval.")
                self.assertEqual(read_conclusion(stage, text, review=True)["label"], "PASSED", text)
                self.assertEqual(read_conclusion(stage, text + " I retract this verdict.", review=True)["label"], "", text)
                limited = f"## Current review\nVerdict: PASSED\n\nPASSED {definition} only partial planning sufficiency."
                self.assertEqual(read_conclusion(stage, limited, review=True)["label"], "", limited)
            for conclusion in ("PASSED but required work remains.", "COMPLETE with pending required checks.",
                               "Verdict: PASSED\nVerdict: PASSED", "Verdict: PASSED\n\nThe review failed.",
                               "Verdict: PASSED\n\nINCOMPLETE because the Plan lacks a rollback step.",
                               "Verdict: PASSED\n\nNOT PASSED because required migration checks remain unverified.",
                               "Verdict: PASSED\n\nHowever, I retract this verdict.",
                               "Verdict: PASSED\n\nThis verdict is withdrawn.",
                               "Verdict: PASSED\n\nI retract this verdict.",
                               "Verdict: PASSED\n\nWe hereby revoke the current conclusion.",
                               "Verdict: PASSED\n\nI have rescinded my assessment.",
                               "Verdict: PASSED\n\nHowever, the Plan still lacks a rollback step."):
                self.assertEqual(read_conclusion(stage, "## Current review\n" + conclusion, review=True)["label"], "", conclusion)
            for qualification in (
                "PASSED only for unit checks; required deployment checks failed.",
                "PASSED has been withdrawn because the current candidate failed.",
                "Passed 3 of 5 checks.",
                "Complete not counting the migration step.",
                "Passed only for the Specification sections.",
                "PASSED is limited to the unit checks.",
                "PASSED applies solely to the Specification sections.",
                "COMPLETE is restricted to the document changes.",
                "PASSED has been retracted.",
                "PASSED is revoked.",
                "COMPLETE has been rescinded.",
                "PASSED no longer holds.",
                "PASSED was premature; the Plan lacks a rollback step.",
                "PASSED isn't justified until the migration is checked.",
                "COMPLETE cannot be confirmed yet.",
                "PASSED can't be confirmed yet.",
                "PASSED wasn’t justified by the evidence.",
                "PASSED proved illusory after the migration review.",
                "PASSED should be disregarded.",
                "COMPLETE source evidence supports the implementation route.",
                "PASSED means the reviewed Plan is sufficient for the next step; PASSED proved illusory.",
                "Complete source evidence supports the implementation route. However, this verdict is withdrawn.",
                "Complete source evidence supports the implementation route. The procedure preserves the inputs. "
                "I retract this verdict.",
                "PASSED means the available Plan can guide the next stage. The intended route is recorded. "
                "This verdict is withdrawn.",
                "Complete reviewer evidence and source authority have concrete implementation routes. But required work remains.",
                "PASSED means the available Plan is sufficient to guide the intended work. PASSED was premature.",
                "PASSED means the available Plan is sufficient to guide the intended work.\nPASSED proved illusory.",
                "Complete reviewer evidence and source authority have concrete implementation routes.\nVerdict: NOT PASSED"):
                text = "## Current review\nVerdict: PASSED\n\n" + qualification
                self.assertEqual(read_conclusion(stage, text, review=True)["label"], "", text)
            for qualification in ("that verdict was premature.", "it isn't justified yet.",
                                  "it can’t be confirmed yet.", "it cannot be confirmed yet."):
                for conclusion in ("Verdict: PASSED — ", "The review passed; "):
                    text = "## Current review\n" + conclusion + qualification
                    self.assertEqual(read_conclusion(stage, text, review=True)["label"], "", text)
        advisory = "Verdict: 🟢 PASSED — advisory review of this implementation Plan, not verification of code or live publication."
        self.assertEqual(read_conclusion("planning", advisory, review=True)["label"], "PASSED")
        self.assertEqual(read_conclusion("planning", advisory + " But required checks failed.", review=True)["label"], "")
        old_report = "Verdict: PASSED\n\n## Readiness\nThis is the current independent verdict for revision `38a5ceb5980868d14c48a2c11b4b0855edb5ce73`."
        self.assertIn("38a5ceb", reported_status("verification", old_report, "report", field="Verdict")["basis_note"])

    def test_incomplete_review_explanation_does_not_retract_its_verdict(self):
        text = ("Verdict: INCOMPLETE\n\nThe Plan has useful steps.\n\n"
                "But several required choices are not made.\n\n- A delivery route is missing.\n")
        self.assertEqual(read_conclusion("planning", text, review=True)["label"], "INCOMPLETE")
        self.assertEqual(read_conclusion("planning", text.replace("INCOMPLETE", "COMPLETE", 1),
                                         review=True)["label"], "")

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
        self.assertEqual(assessment_facts("specification", substantive, [document])["applies"], "unconfirmed")
        self.assertEqual(assessment_facts("specification", reviewed)["applies"], "unconfirmed")
        modern = document + f"\n## Current review\nVerdict: COMPLETE\nBasis: {review_basis(document)}\nBasis format: content-v2\n"
        self.assertEqual(assessment_facts("specification", modern)["applies"], "current")
        self.assertEqual(assessment_facts("specification", modern.replace("Keep the user's work.", "Delete it."))["applies"], "unconfirmed")

    def test_explicit_current_legacy_reports_do_not_read_historical_failures_as_current(self):
        result = "Programming: COMPLETE — This revision replaces the earlier INCOMPLETE result.\n"
        self.assertEqual(read_conclusion("programming", result)["label"], "COMPLETE")
        report = "# Verification Report\n\n> **Current report: round 2 — PASSED**\n\n**PASSED**\n\n## Round 1 — historical\nNOT PASSED\n"
        self.assertEqual(reported_verdict(report), "PASSED")
        report = "# Report\n\n**Current verdict (round 3, 19 October 2026): PASSED.** Current scope passed.\n\n## Round 3 — current report (verbatim)\nPASSED\n"
        self.assertEqual(reported_verdict(report), "PASSED")
        self.assertEqual(reported_verdict("# Report\n\n**Current verdict (round 3): PASSED.** Current scope passed.\n"), "PASSED")
        # A faithful small legacy opening: older failed rounds and a separate
        # live-answer acceptance checkpoint do not retract the current pass.
        scoped = ("# Verification Report\n\n**Current verdict (round 3, 19 October 2026): PASSED.** "
                  "Candidate: revision abc1234. Round 1 returned NOT PASSED (a defect); "
                  "both findings were corrected and confirmed resolved in round 2; "
                  "round 3 resolved the one remaining evidence gap (the supplied check output showed 8 passed). "
                  "The verdict accepts the reviewed implementation; it does not establish the user's acceptance "
                  "of the flagged live answer (the user's checkpoint, still pending at save time).\n\n"
                  "## Round 3 — current report (verbatim)\n\nPASSED\n\n"
                  "## Round 1 — history\n\nNOT PASSED\n")
        self.assertEqual(reported_verdict(scoped), "PASSED")
        for retraction in ("But the current required check failed.",
                           "However the current implementation is unfinished.",
                           "Round 3 returned NOT PASSED.",
                           "Round 1 returned NOT PASSED, but the current privacy check is still failing.",
                           "Round 1 returned NOT PASSED and current required checks remain unfinished.",
                           "It does not establish the user's acceptance of the live answer because current export checks failed."):
            current = scoped.replace("Candidate: revision abc1234.", retraction)
            self.assertNotEqual(reported_verdict(current), "PASSED", retraction)
        acceptance_test = "Current verdict (round 3): PASSED. User acceptance tests are still pending.\n"
        self.assertNotEqual(reported_verdict(acceptance_test), "PASSED")
        for continuing in ("Round 1 returned NOT PASSED for a defect that remains unresolved.",
                           "Round 2 returned INCOMPLETE because required checks remain unfinished."):
            report = "Current verdict (round 3): PASSED. " + continuing
            self.assertNotEqual(reported_verdict(report), "PASSED", continuing)
        duplicated = reported_status("programming", "Status: PASSED\nStatus: PASSED\n", "result", field="Status")
        self.assertNotEqual(duplicated["kind"], "positive")
        self.assertIn("Duplicate", duplicated["reason"])
        review = "# Specification\n\n## Current review\nVerdict: COMPLETE — this does not verify working software.\n"
        self.assertEqual(assessment_facts("specification", review)["outcome"], "PASSED")
        misleading = "Status: PASSED — This report supersedes the earlier report; required checks remain unfinished."
        self.assertNotEqual(read_conclusion("verification", misleading)["label"], "PASSED")
        misleading = "Status: COMPLETE — Project.md Programming stays IN PROGRESS for later scope, but current required checks remain unfinished."
        self.assertNotEqual(read_conclusion("programming", misleading)["label"], "COMPLETE")
        legacy = "## Current review\nVerdict: INCOMPLETE\n\n- The delivery requirement is missing.\n"
        self.assertEqual(assessment_facts("planning", legacy)["outcome"], "NOT PASSED")
        canonical = "---\nreview: INCOMPLETE\n---\n# Plan\n"
        self.assertEqual(assessment_facts("planning", canonical)["outcome"], "INCOMPLETE")

    def test_representative_invented_programming_results_preserve_scoped_success_and_caveats(self):
        paragraphs = [
            ("Programming: COMPLETE — 2031-04-12. Delivery checks D1–D3 confirmed DEMO-410's handoff: "
             "**Cedar Desk 2.7.1** was released (tag `v2.7.1` → public main "
             "`0123456789abcdef0123456789abcdef01234567`, archive `cedar-desk-2.7.1.zip` "
             "sha-256 `0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef`), "
             "independently verified PASSED by a fresh reviewer in round 5, with no material findings. "
             "The assignment covered release evidence and delivery records only; it required no application edits. "
             "This revision replaces the earlier INCOMPLETE result, which awaited DEMO-410's round-2 review "
             "and worktree cleanup."),
            ("Status: COMPLETE — The first delivery was implemented, independently reviewed, corrected, "
             "and verified (review round 4: PASSED), then merged and installed in the running Cedar Desk "
             "workspace; its records are saved and task-owned files removed. A separate acceptance decision "
             "is Morgan's to make: whether the detailed mode's flagged sample answer meets the Specification's "
             "human judgement criterion. The overall project closes after Morgan records that judgement."),
            ("Status: COMPLETE — The Plan's two assigned deliveries are merged to the application and document "
             "repositories and verified. Delivery A adds library folders and document handling; Delivery B adds "
             "exports plus move, restore, and removal actions. Both are available in the running Cedar Desk "
             "workspace and its document store. A third milestone is reserved for later planning after DEMO-275 "
             "connects activity messages to move actions; Project.md's Programming field stays IN PROGRESS "
             "for that remaining part, as the Plan specifies."),
        ]
        for paragraph in paragraphs:
            with self.subTest(project=paragraph[:90]):
                result = read_conclusion("programming", paragraph)
                self.assertEqual(result["label"], "COMPLETE")
                self.assertEqual(result["evidence"], [paragraph])


if __name__ == "__main__":
    unittest.main()
