"""Deterministic tests. Pure stdlib unittest so `make test` needs no dependencies."""

import json
import unittest
from pathlib import Path

from dpa_review.review import build_packet, render_markdown
from dpa_review.checks import assess_transfer

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "data" / "sample_dpa.json").read_text(encoding="utf-8"))


def _by_id(packet, rule_id):
    return next(f for f in packet.findings if f.rule_id == rule_id)


class TransferAssessment(unittest.TestCase):
    def test_eea_country_needs_no_mechanism(self):
        status, sev, _ = assess_transfer("FR", "none")
        self.assertEqual(status, "PRESENT")
        self.assertEqual(sev, "INFO")

    def test_adequacy_country_is_low_risk(self):
        status, sev, _ = assess_transfer("JP", "adequacy")
        self.assertEqual(status, "PRESENT")
        self.assertEqual(sev, "LOW")

    def test_third_country_without_mechanism_is_high_severity(self):
        status, sev, _ = assess_transfer("US", "none")
        self.assertEqual(status, "MISSING")
        self.assertEqual(sev, "HIGH")

    def test_sccs_need_review_not_block(self):
        status, sev, _ = assess_transfer("US", "sccs")
        self.assertEqual(status, "NEEDS_REVIEW")
        self.assertEqual(sev, "LOW")


class DataPrivacyFrameworkAssessment(unittest.TestCase):
    """EU-US DPF: Art. 45 adequacy decision (EU) 2023/1795, limited to listed US organisations."""

    def test_dpf_is_an_art45_adequacy_basis_not_art46(self):
        status, sev, detail = assess_transfer("US", "dpf", dpf_certified=True, includes_hr_data=False)
        self.assertEqual(status, "PRESENT")
        self.assertEqual(sev, "LOW")
        self.assertIn("Art. 45", detail)
        self.assertIn("2023/1795", detail)
        self.assertNotIn("Art. 46", detail)

    def test_dpf_without_active_certification_has_no_valid_basis(self):
        status, sev, detail = assess_transfer("US", "dpf")
        self.assertEqual(status, "MISSING")
        self.assertEqual(sev, "HIGH")
        self.assertIn("Data Privacy Framework List", detail)

    def test_dpf_does_not_cover_importers_outside_the_us(self):
        status, sev, _ = assess_transfer("IN", "dpf", dpf_certified=True, includes_hr_data=False)
        self.assertEqual(status, "MISSING")
        self.assertEqual(sev, "HIGH")

    def test_dpf_hr_data_needs_hr_certification(self):
        status, sev, detail = assess_transfer("US", "dpf", dpf_certified=True, includes_hr_data=True)
        self.assertEqual(status, "MISSING")
        self.assertEqual(sev, "HIGH")
        self.assertIn("HR data", detail)

    def test_dpf_hr_data_with_hr_certification_is_covered(self):
        status, sev, _ = assess_transfer(
            "US", "dpf", dpf_certified=True, dpf_covers_hr_data=True, includes_hr_data=True
        )
        self.assertEqual(status, "PRESENT")
        self.assertEqual(sev, "LOW")

    def test_dpf_with_unknown_hr_scope_needs_review(self):
        status, sev, _ = assess_transfer("US", "dpf", dpf_certified=True)
        self.assertEqual(status, "NEEDS_REVIEW")
        self.assertEqual(sev, "MEDIUM")

    def _dpf_dpa(self, certified):
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["art28_clauses"]["subprocessor_flowdown"] = True  # isolate the transfer findings
        dpa["processing"]["includes_hr_data"] = False
        dpa["transfers"]["mechanisms"]["US"] = "dpf"
        dpa["transfers"]["dpf_certified"] = {"US": certified}
        dpa["subprocessors"][1]["transfer_mechanism"] = "dpf"
        dpa["subprocessors"][1]["dpf_certified"] = certified
        return dpa

    def test_certified_dpf_transfers_need_no_transfer_impact_assessment(self):
        packet = build_packet(self._dpf_dpa(certified=True))
        for rule_id in ("transfer.us", "transfer.subprocessor.support_tools_llc"):
            finding = _by_id(packet, rule_id)
            self.assertEqual(finding.status, "PRESENT")
            self.assertIn("Art. 44-45", finding.citation)
            self.assertIn("Commission Implementing Decision (EU) 2023/1795", finding.citation)
        self.assertNotIn("transfer.impact_assessment", {f.rule_id for f in packet.findings})
        self.assertEqual(packet.review_state, "CLEARED_FOR_REVIEW")

    def test_uncertified_dpf_transfers_block_the_packet(self):
        packet = build_packet(self._dpf_dpa(certified=False))
        for rule_id in ("transfer.us", "transfer.subprocessor.support_tools_llc"):
            finding = _by_id(packet, rule_id)
            self.assertEqual(finding.status, "MISSING")
            self.assertEqual(finding.severity, "HIGH")
        self.assertIn("Data Privacy Framework List", _by_id(packet, "transfer.us").remediation)
        self.assertEqual(packet.review_state, "BLOCKED")


class SamplePacket(unittest.TestCase):
    def setUp(self):
        self.packet = build_packet(SAMPLE)

    def test_planted_us_transfer_defect_is_caught(self):
        # A US sub-processor with no transfer mechanism must be flagged HIGH/MISSING.
        finding = _by_id(self.packet, "transfer.us")
        self.assertEqual(finding.status, "MISSING")
        self.assertEqual(finding.severity, "HIGH")
        self.assertIn("Art. 44", finding.citation)

    def test_planted_flowdown_defect_is_caught(self):
        finding = _by_id(self.packet, "subprocessor.flowdown")
        self.assertEqual(finding.status, "MISSING")
        self.assertEqual(finding.citation, "GDPR Art. 28(4)")

    def test_overall_state_is_blocked(self):
        # Open HIGH findings must block the packet, the equivalent of "marked for rejection".
        self.assertEqual(self.packet.review_state, "BLOCKED")

    def test_every_finding_has_a_citation(self):
        for f in self.packet.findings:
            self.assertTrue(f.citation.strip(), msg=f"missing citation on {f.rule_id}")

    def test_output_is_deterministic(self):
        again = build_packet(SAMPLE)
        self.assertEqual(render_markdown(self.packet), render_markdown(again))

    def test_adequacy_subprocessor_is_not_flagged(self):
        finding = _by_id(self.packet, "transfer.jp")
        self.assertEqual(finding.status, "PRESENT")


class CuredPacket(unittest.TestCase):
    def test_fixing_defects_clears_high_findings(self):
        cured = json.loads(json.dumps(SAMPLE))
        cured["art28_clauses"]["subprocessor_flowdown"] = True
        cured["transfers"]["mechanisms"]["US"] = "sccs"
        cured["transfers"]["transfer_impact_assessment"] = True
        cured["subprocessors"][1]["transfer_mechanism"] = "sccs"
        packet = build_packet(cured)
        self.assertEqual(packet.summary["high_open"], 0)
        self.assertIn(packet.review_state, {"NEEDS_REVIEW", "CLEARED_FOR_REVIEW"})


if __name__ == "__main__":
    unittest.main()
