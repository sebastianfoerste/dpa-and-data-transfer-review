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


def _open_high(packet):
    """{rule id: status} of the packet's open HIGH findings."""
    return {f.rule_id: f.status for f in packet.findings if f.status in OPEN_STATUSES and f.severity == "HIGH"}


def _support_tools(dpa):
    return next(sp for sp in dpa["subprocessors"] if sp["name"] == "Support Tools LLC")


def _record_tia(dpa):
    dpa["transfers"]["transfer_impact_assessment"] = True


def _changed(*changes):
    """The packet for a copy of the sample with each change applied."""
    dpa = json.loads(json.dumps(SAMPLE))
    for change in changes:
        change(dpa)
    return build_packet(dpa)


# The input changes README.md ("What the demo produces") names as moving the sample to NEEDS_REVIEW,
# written out here rather than read from the README.
CURE_CHANGES = {
    "flow-down clause": lambda dpa: dpa["art28_clauses"].update(subprocessor_flowdown=True),
    "notice and objection": lambda dpa: dpa["art28_clauses"].update(
        subprocessor_change_notice_and_objection=True
    ),
    "SCCs for the direct US transfer": lambda dpa: dpa["transfers"]["mechanisms"].update(US="sccs"),
    "SCCs for Support Tools LLC": lambda dpa: _support_tools(dpa).update(transfer_mechanism="sccs"),
}
SUPPORT_TOOLS_RULE = "transfer.subprocessor.support_tools_llc"
SCCS_WITHOUT_TIA = ROOT / "tests" / "fixtures" / "04-sccs-without-tia.json"


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
    """README.md, "What the demo produces": the four input changes in CURE_CHANGES move the sample from
    BLOCKED to NEEDS_REVIEW, each of them is needed, and the three fixes the README used to name leave
    it BLOCKED."""

    def test_fixing_defects_clears_high_findings(self):
        packet = _changed(*CURE_CHANGES.values(), _record_tia)
        self.assertEqual((packet.summary["high_open"], packet.summary["medium_open"]), (0, 0))
        self.assertEqual(packet.review_state, "NEEDS_REVIEW")
        # The two US transfers on SCCs stay open as LOW review items, so the sample cannot clear.
        for rule_id in ("transfer.us", SUPPORT_TOOLS_RULE):
            with self.subTest(rule_id=rule_id):
                finding = _by_id(packet, rule_id)
                self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "LOW"))
        self.assertEqual(_by_id(packet, "transfer.impact_assessment").status, "PRESENT")

    def test_without_a_recorded_tia_the_cure_leaves_a_medium_review_item(self):
        packet = _changed(*CURE_CHANGES.values())
        self.assertEqual(packet.summary["high_open"], 0)
        self.assertEqual(packet.review_state, "NEEDS_REVIEW")
        finding = _by_id(packet, "transfer.impact_assessment")
        self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "MEDIUM"))

    def test_each_of_the_four_changes_is_needed(self):
        for left_out in CURE_CHANGES:
            with self.subTest(left_out=left_out):
                rest = [change for name, change in CURE_CHANGES.items() if name != left_out]
                packet = _changed(*rest, _record_tia)
                self.assertEqual(packet.summary["high_open"], 1)
                self.assertEqual(packet.review_state, "BLOCKED")

    def test_the_three_fixes_the_old_readme_named_leave_the_sample_blocked(self):
        # The README used to say that a flow-down clause, an Art. 46 mechanism for the US transfer and a
        # recorded transfer impact assessment move the sample to NEEDS_REVIEW.
        packet = _changed(
            CURE_CHANGES["flow-down clause"], CURE_CHANGES["SCCs for the direct US transfer"], _record_tia
        )
        self.assertEqual(packet.review_state, "BLOCKED")
        self.assertEqual(_open_high(packet), {NOTICE_RULE: "MISSING", SUPPORT_TOOLS_RULE: "MISSING"})


class TransferImpactAssessmentGate(unittest.TestCase):
    """README.md, "AI SaaS legal-team use case": the sample raises no transfer impact assessment finding,
    and a missing assessment is a MEDIUM review item. It makes a packet NEEDS_REVIEW, never BLOCKED, so
    it fails a gate only from --fail-on needs_review (the CLI default, not the Action's)."""

    def test_the_sample_raises_no_tia_finding(self):
        packet = build_packet(SAMPLE)
        self.assertNotIn("transfer.impact_assessment", {f.rule_id for f in packet.findings})
        self.assertEqual(
            _open_high(packet),
            {
                "subprocessor.flowdown": "MISSING",
                NOTICE_RULE: "MISSING",
                "transfer.us": "MISSING",
                SUPPORT_TOOLS_RULE: "MISSING",
            },
        )

    def test_a_missing_tia_is_a_medium_review_item(self):
        packet = build_packet(json.loads(SCCS_WITHOUT_TIA.read_text(encoding="utf-8")))
        finding = _by_id(packet, "transfer.impact_assessment")
        self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "MEDIUM"))
        self.assertEqual(packet.review_state, "NEEDS_REVIEW")

    def test_the_cli_fails_on_a_missing_tia_only_from_needs_review(self):
        for fail_on, expected in (((), 1), (("--fail-on", "needs_review"), 1), (("--fail-on", "blocked"), 0)):
            with self.subTest(fail_on=fail_on):
                self.assertEqual(run_cli("--input", SCCS_WITHOUT_TIA, "--quiet", *fail_on), (expected, "", ""))


class ReadmeDemo(unittest.TestCase):
    def test_the_readme_quotes_the_committed_sample_packet(self):
        # The block under "What the demo produces" is the start of examples/review-packet.md, which
        # tests/test_github_action.py holds equal to what the CLI writes for the sample.
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quoted = readme.split("## What the demo produces", 1)[1].split("```\n", 2)[1].splitlines()
        packet = (ROOT / "examples" / "review-packet.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("**Review state: BLOCKED**", quoted)
        self.assertEqual(quoted, packet[: len(quoted)])


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
