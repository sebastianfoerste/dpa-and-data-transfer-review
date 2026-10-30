"""Deterministic tests. Pure stdlib unittest so `make test` needs no dependencies."""

import json
import random
import tempfile
import unittest
from pathlib import Path

from dpa_review.review import OPEN_STATUSES, build_packet, render_markdown
from dpa_review.checks import assess_transfer
from tests.helpers import run_cli

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
        self.assertEqual(finding.citation, "GDPR Art. 28(4) read with Art. 28(3)(d)")

    def test_general_authorisation_without_change_notice_is_caught(self):
        # The sample authorises sub-processors generally and records no change-notice and
        # objection mechanism, which reads as not found.
        finding = _by_id(self.packet, "subprocessor.change_notice_and_objection")
        self.assertEqual((finding.status, finding.severity), ("MISSING", "HIGH"))

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
        cured["art28_clauses"]["subprocessor_change_notice_and_objection"] = True
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


class DataSubjectCategories(unittest.TestCase):
    """Rule processing.data_subjects: GDPR Art. 28(3), first subparagraph, has the contract set out
    the categories of data subjects. Fixture 01 records every other fact, so this rule alone decides
    whether it clears."""

    def with_data_subjects(self, value):
        dpa = json.loads(json.dumps(EEA_ONLY))
        if value is DELETE:
            del dpa["processing"]["data_subjects"]
        else:
            dpa["processing"]["data_subjects"] = value
        return dpa

    def test_listed_categories_are_present(self):
        for name, dpa, listed in (
            ("sample", SAMPLE, "customer end users"),
            ("fixture 01", EEA_ONLY, "customers, prospects"),
        ):
            with self.subTest(input=name):
                finding = _by_id(build_packet(dpa), "processing.data_subjects")
                self.assertEqual((finding.status, finding.severity), ("PRESENT", "MEDIUM"))
                self.assertEqual(finding.citation, "GDPR Art. 28(3)")
                self.assertIn(listed, finding.detail)
                self.assertEqual(finding.remediation, "")
        self.assertEqual(build_packet(EEA_ONLY).review_state, "CLEARED_FOR_REVIEW")

    def test_omitted_null_or_empty_is_missing(self):
        for label, value in (("omitted", DELETE), ("null", None), ("empty list", [])):
            with self.subTest(data_subjects=label):
                packet = build_packet(self.with_data_subjects(value))
                finding = _by_id(packet, "processing.data_subjects")
                self.assertEqual((finding.status, finding.severity), ("MISSING", "MEDIUM"))
                self.assertEqual(finding.citation, "GDPR Art. 28(3)")
                self.assertTrue(finding.remediation)
                self.assertEqual(packet.review_state, "NEEDS_REVIEW")
                opened = [f.rule_id for f in packet.findings if f.status in OPEN_STATUSES]
                self.assertEqual(opened, ["processing.data_subjects"])

    def test_the_cli_exits_1_without_categories(self):
        for label, value in (("omitted", DELETE), ("null", None), ("empty list", [])):
            with self.subTest(data_subjects=label), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "dpa.json"
                source.write_text(json.dumps(self.with_data_subjects(value)), encoding="utf-8")
                for fail_on in ((), ("--fail-on", "needs_review")):
                    code, stdout, stderr = run_cli("--input", source, "--quiet", *fail_on)
                    self.assertEqual((code, stdout, stderr), (1, "", ""))


# The rule, flag and citations decided for DPA-07, written out here rather than read from the code under test.
NOTICE_RULE = "subprocessor.change_notice_and_objection"
NOTICE_FLAG = "subprocessor_change_notice_and_objection"
AUTHORISATION_CITATION = "GDPR Art. 28(2) read with Art. 28(3)(d)"
FLOWDOWN_CITATION = "GDPR Art. 28(4) read with Art. 28(3)(d)"


class SubprocessorChangeNotice(unittest.TestCase):
    """Rule subprocessor.change_notice_and_objection. Under a general written authorisation, GDPR
    Art. 28(2), second sentence, has the processor inform the controller of any intended addition or
    replacement of other processors, giving the controller the opportunity to object, and Art.
    28(3)(d) has the contract stipulate that the processor respects the conditions of Art. 28(2) and
    (4). Fixture 01 records every other fact, so this rule alone decides whether it clears."""

    def authorised(self, authorisation, notice=DELETE):
        dpa = json.loads(json.dumps(EEA_ONLY))
        dpa["art28_clauses"]["subprocessor_authorization"] = authorisation
        if notice is not DELETE:
            dpa["art28_clauses"][NOTICE_FLAG] = notice
        return dpa

    def test_general_with_notice_and_objection_is_present(self):
        packet = build_packet(self.authorised("general", True))
        finding = _by_id(packet, NOTICE_RULE)
        self.assertEqual((finding.status, finding.severity), ("PRESENT", "HIGH"))
        self.assertEqual(finding.citation, AUTHORISATION_CITATION)
        self.assertEqual(finding.remediation, "")
        self.assertEqual(packet.review_state, "CLEARED_FOR_REVIEW")

    def test_general_without_notice_and_objection_is_missing_and_blocks(self):
        # Answer to question 4: an omitted flag reads like every other omitted clause flag, as not found.
        for label, notice in (("false", False), ("null", None), ("omitted", DELETE)):
            with self.subTest(flag=label):
                packet = build_packet(self.authorised("general", notice))
                finding = _by_id(packet, NOTICE_RULE)
                self.assertEqual((finding.status, finding.severity), ("MISSING", "HIGH"))
                self.assertEqual(finding.citation, AUTHORISATION_CITATION)
                self.assertTrue(finding.remediation)
                self.assertEqual(packet.review_state, "BLOCKED")
                opened = [f.rule_id for f in packet.findings if f.status in OPEN_STATUSES]
                self.assertEqual(opened, [NOTICE_RULE])
                self.assertEqual(_by_id(packet, "subprocessor.authorization").status, "PRESENT")

    def test_the_cli_exits_2_without_notice_and_objection(self):
        for label, notice in (("false", False), ("omitted", DELETE)):
            with self.subTest(flag=label), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "dpa.json"
                source.write_text(json.dumps(self.authorised("general", notice)), encoding="utf-8")
                for fail_on in ((), ("--fail-on", "blocked"), ("--fail-on", "needs_review")):
                    code, stdout, stderr = run_cli("--input", source, "--quiet", *fail_on)
                    self.assertEqual((code, stdout, stderr), (2, "", ""))

    def test_specific_or_no_authorisation_is_unaffected(self):
        for authorisation, status, state in (
            ("specific", "PRESENT", "CLEARED_FOR_REVIEW"),
            ("none", "MISSING", "BLOCKED"),
        ):
            for notice in (True, False, None, DELETE):
                with self.subTest(authorisation=authorisation, flag=notice):
                    packet = build_packet(self.authorised(authorisation, notice))
                    self.assertNotIn(NOTICE_RULE, {f.rule_id for f in packet.findings})
                    self.assertEqual(_by_id(packet, "subprocessor.authorization").status, status)
                    self.assertEqual(packet.review_state, state)

    def test_authorisation_and_flowdown_cite_art_28_3_d(self):
        packet = build_packet(EEA_ONLY)
        self.assertEqual(_by_id(packet, "subprocessor.authorization").citation, AUTHORISATION_CITATION)
        self.assertEqual(_by_id(packet, "subprocessor.flowdown").citation, FLOWDOWN_CITATION)

    def test_evidence_for_the_flag_attaches_to_the_finding(self):
        fixture = ROOT / "tests" / "fixtures" / "22-general-authorisation-with-notice.json"
        dpa = json.loads(fixture.read_text(encoding="utf-8"))
        evidence = build_packet(dpa).evidence[NOTICE_RULE]
        self.assertIn(f"art28_clauses.{NOTICE_FLAG}", [item["fact"] for item in evidence])

    def test_the_contract_takes_the_flag_as_true_or_false(self):
        for value in ("yes", "false", 1):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "dpa.json"
                source.write_text(json.dumps(self.authorised("general", value)), encoding="utf-8")
                code, stdout, stderr = run_cli("--input", source, "--quiet")
                self.assertEqual((code, stdout), (3, ""))
                self.assertIn(f"art28_clauses.{NOTICE_FLAG} must be true or false", stderr)


if __name__ == "__main__":
    unittest.main()
