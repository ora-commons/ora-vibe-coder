import unittest

from ora_vibe_coder.status import QUALITY, VALUES, reported_status


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

    def test_verification_only_reads_own_overview_field_not_prior_report(self):
        text = "# Project\nVerification: NOT PASSED — REVIEW INCOMPLETE\nProgramming: COMPLETE\n\n## Report\nPASSED\nVerification: PASSED\n"
        result = self.status("verification", text)
        self.assertEqual(result["kind"], "attention")
        self.assertNotEqual(result["literal"], "PASSED")
        for value in QUALITY - {"PASSED"}:
            self.assertNotEqual(self.status("verification", f"Verification: {value}")["kind"], "positive")


if __name__ == "__main__":
    unittest.main()
