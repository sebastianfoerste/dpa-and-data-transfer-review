"""Deterministic tests. Pure stdlib unittest so `make test` needs no dependencies."""

import json
import random
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


# The absence markers decided for DPA-01, written out here rather than read from the code under test.
ABSENCE_MARKERS = ("false", "no", "none", "n/a", "unknown", "not specified", "tbd")
DESCRIPTION_KEYS = ("subject_matter", "duration", "nature_and_purpose")
EEA_ONLY = json.loads((ROOT / "tests" / "fixtures" / "01-eea-only.json").read_text(encoding="utf-8"))
DELETE = object()


class ProcessingDescriptions(unittest.TestCase):
    """Rules processing.subject_matter, processing.duration and processing.nature_and_purpose.

    The rules run here without the input contract, which refuses a blank description or an absence
    marker with exit 3 before any rule runs. The rules still must not read one as PRESENT.
    """

    def described(self, key, value):
        dpa = json.loads(json.dumps(EEA_ONLY))
        if value is DELETE:
            del dpa["processing"][key]
        else:
            dpa["processing"][key] = value
        return build_packet(dpa)

    def test_a_description_or_true_is_present(self):
        for key in DESCRIPTION_KEYS:
            for value in (True, "The term of the main services agreement"):
                with self.subTest(key=key, value=value):
                    packet = self.described(key, value)
                    self.assertEqual(_by_id(packet, f"processing.{key}").status, "PRESENT")
                    self.assertEqual(packet.review_state, "CLEARED_FOR_REVIEW")

    def test_false_null_or_omitted_is_missing(self):
        for key in DESCRIPTION_KEYS:
            for value in (False, None, DELETE):
                with self.subTest(key=key, value=value):
                    packet = self.described(key, value)
                    finding = _by_id(packet, f"processing.{key}")
                    self.assertEqual((finding.status, finding.severity), ("MISSING", "MEDIUM"))
                    self.assertEqual(packet.review_state, "NEEDS_REVIEW")

    def test_no_absence_marker_is_ever_present(self):
        # Property test: in any case and with any surrounding whitespace, a blank string or an
        # absence marker reads as MISSING, so the packet can never be CLEARED_FOR_REVIEW on it.
        rng = random.Random(28)
        for key in DESCRIPTION_KEYS:
            for marker in ABSENCE_MARKERS + ("",):
                variants = {marker, marker.upper(), f"  {marker.title()}\t"}
                variants |= {
                    "".join(rng.choice(" \t\n ") for _ in range(rng.randrange(3)))
                    + "".join(rng.choice((ch.upper(), ch.lower())) for ch in marker)
                    + "".join(rng.choice(" \t\n ") for _ in range(rng.randrange(3)))
                    for _ in range(25)
                }
                for value in sorted(variants):
                    with self.subTest(key=key, value=value):
                        packet = self.described(key, value)
                        finding = _by_id(packet, f"processing.{key}")
                        self.assertEqual((finding.status, finding.severity), ("MISSING", "MEDIUM"))
                        self.assertEqual(packet.review_state, "NEEDS_REVIEW")


if __name__ == "__main__":
    unittest.main()
