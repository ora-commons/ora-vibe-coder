import unittest

from ora_vibe_coder.project import not_started
from ora_vibe_coder.status import (VALUES, assessment_facts, overview_status, reported_status,
                                   review_basis, review_disposition)


class ReportedStatus(unittest.TestCase):
    def status(self, stage, text):
        return reported_status(stage, text, "selected current file")

    def test_exact_yaml_values_with_missing_malformed_duplicate_and_off_list(self):
        for stage, values in VALUES.items():
            for value in values:
                with self.subTest(stage=stage, value=value):
                    result = self.status(stage, f"---\nstatus: {value}\n---\n# Document\nBody prose.\n")
                    self.assertEqual(result["label"], value)
                    self.assertEqual(result["kind"] == "positive", value in {"APPROVED", "PASSED"})
        for broken, named in (("---\nstatus: PASSED\nstatus: NOT PASSED\n---\n", "Duplicate status fields in opening YAML: PASSED, NOT PASSED."),
                              ("---\nstatus: \"PASSED \"\n---\n", "PASSED"),
                              ("---\nstatus: PASSED\n", "not closed"),
                              ("---\nstatus: COMPLETE\n---\n", "COMPLETE"),
                              ("---\nstatus: passed\n---\n", "passed"),
                              ("---\nstatus:\n---\n", "(blank)"),
                              ("---\nstatus:\n  nested: true\n---\n", "scalar")):
            label = self.status("programming", broken)["label"]
            self.assertTrue(label.startswith("Unknown"), (broken, label))
            self.assertIn(named, label)
        for stage in VALUES:
            self.assertEqual(self.status(stage, f"# {stage}\n\nStatus: APPROVED\nVerdict: PASSED\n")["label"],
                             "Not reported")

    def test_body_wording_never_changes_a_yaml_verdict(self):
        contradictory = ("---\nstatus: PASSED\n---\n# Report\n\nVerdict: NOT PASSED. But every check failed.\n\n"
                         "Status: INCOMPLETE\n\n## Earlier review\nVerdict: NOT PASSED\n")
        self.assertEqual(self.status("verification", contradictory)["label"], "PASSED")
        failing = "---\nstatus: NOT PASSED\n---\nThe work is complete and every check passed.\n"
        self.assertEqual(self.status("verification", failing)["label"], "NOT PASSED")

    def test_review_values_off_list_and_legacy_bodies(self):
        for review in ("PASSED", "NOT PASSED", "INCOMPLETE", "CHANGED"):
            facts = assessment_facts("specification", f"---\nstatus: APPROVED\nreview: {review}\n---\n# Specification\n")
            self.assertEqual((facts["verdict"], facts["issues"]), (review, []))
        self.assertFalse(assessment_facts("specification", "---\nstatus: APPROVED\n---\n# S\n")["present"])
        off = assessment_facts("specification", "---\nreview: COMPLETE\n---\n")
        self.assertEqual((off["verdict"], off["issues"][0]), ("", "Unknown YAML review value: COMPLETE"))
        legacy = "# Specification\n\n## Current review\nVerdict: COMPLETE\nBasis: " + "a" * 64 + "\n"
        self.assertFalse(assessment_facts("specification", legacy)["present"])

    def test_review_basis_stage_and_finding_count(self):
        basis = review_basis("---\nstatus: DRAFT\n---\n# Specification\n\n## Requirements\nKeep the work.\n")

        def reviewed(value, body="Keep the work.", bullets=(), stage="Specification"):
            text = (f"---\nstatus: DRAFT\nreview: {value}\n---\n# Specification\n\n## Requirements\n{body}\n"
                    f"## Current review\nStage: {stage}\nBasis: {basis}\nBasis format: content-v2\n")
            return text + "".join(f"- {item}\n" for item in bullets)

        facts = assessment_facts("specification", reviewed("PASSED"))
        self.assertEqual((facts["verdict"], facts["applies"], facts["issues"]), ("PASSED", "current", []))
        self.assertEqual(assessment_facts("specification", reviewed("PASSED", body="Changed."))["applies"], "unconfirmed")
        self.assertEqual(assessment_facts("specification", reviewed("NOT PASSED", bullets=("One gap.", "Two gaps.")))["findings"], 2)
        self.assertIsNone(assessment_facts("specification", reviewed("PASSED", bullets=("One note.",)))["findings"])
        mismatched = assessment_facts("specification", reviewed("PASSED", stage="Plan"))
        self.assertEqual((mismatched["verdict"], mismatched["applies"], mismatched["issues"]),
                         ("PASSED", "unconfirmed", []))
        changed = assessment_facts("specification", reviewed("CHANGED"))
        self.assertEqual((changed["verdict"], changed["applies"]), ("CHANGED", "earlier"))

    def test_disposition_reads_yaml_only(self):
        self.assertEqual(review_disposition("---\ndisposition: SEVERE\n---\n"), "SEVERE")
        for text in ("", "Review disposition: SETTLED\n",
                     "---\ndisposition: SETTLED\ndisposition: SETTLED\n---\n",
                     "---\ndisposition: SETTLED\n  nested: true\n---\n",
                     "---\ndisposition: settled\n---\n", "---\nstatus: PASSED\n---\n"):
            self.assertEqual(review_disposition(text), "", text)

    def test_overview_literal_read_and_template_detection(self):
        self.assertEqual(overview_status("programming", "# Project\n\nProgramming: IN PROGRESS\n", "p")["label"], "IN PROGRESS")
        self.assertEqual(overview_status("verification", "# Project\n\nVerification: NOT STARTED\n", "p")["literal"], "NOT STARTED")
        self.assertEqual(overview_status("programming", "# Project\n", "p")["label"], "Not reported")
        self.assertTrue(not_started("# Document\n\nStatus: DRAFT\n\n## Requirements\n"))
        for value in VALUES["programming"]:
            self.assertFalse(not_started(f"---\nstatus: {value}\n---\n# Result\n\n## Checks\n"))
        self.assertFalse(not_started("# Document\n\nRequirements: Preserve records.\n"))


if __name__ == "__main__":
    unittest.main()
