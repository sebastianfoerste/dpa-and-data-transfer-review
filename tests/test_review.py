"""Deterministic tests. Pure stdlib unittest so `make test` needs no dependencies."""

import json
import unittest
from pathlib import Path

from dpa_review.review import build_packet, render_markdown
from dpa_review.checks import InvalidInputError, assess_transfer

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "data" / "sample_dpa.json").read_text(encoding="utf-8"))


# An importer listed on the DPF List with a certification that covers non-HR data.
DPF_LISTED = {"dpf_certified": True, "dpf_covers_non_hr_data": True}


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
        status, sev, detail = assess_transfer("US", "sccs")
        self.assertEqual(status, "NEEDS_REVIEW")
        self.assertEqual(sev, "LOW")
        self.assertIn("Art. 46(2)(c); Commission Implementing Decision (EU) 2021/914", detail)
        self.assertIn("EDPB Recommendations 01/2020", detail)


class DataPrivacyFrameworkAssessment(unittest.TestCase):
    """EU-US DPF: Art. 45 adequacy decision (EU) 2023/1795, limited to listed US organisations."""

    def test_dpf_is_an_art45_adequacy_basis_not_art46(self):
        status, sev, detail = assess_transfer("US", "dpf", **DPF_LISTED, includes_hr_data=False)
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
        status, sev, _ = assess_transfer("IN", "dpf", **DPF_LISTED, includes_hr_data=False)
        self.assertEqual(status, "MISSING")
        self.assertEqual(sev, "HIGH")

    def test_dpf_hr_data_needs_hr_certification(self):
        status, sev, detail = assess_transfer("US", "dpf", **DPF_LISTED, includes_hr_data=True)
        self.assertEqual(status, "MISSING")
        self.assertEqual(sev, "HIGH")
        self.assertIn("HR data", detail)

    def test_dpf_hr_data_with_hr_certification_is_covered(self):
        status, sev, _ = assess_transfer(
            "US", "dpf", **DPF_LISTED, dpf_covers_hr_data=True, includes_hr_data=True
        )
        self.assertEqual(status, "PRESENT")
        self.assertEqual(sev, "LOW")

    def test_dpf_with_unknown_hr_scope_needs_review(self):
        status, sev, detail = assess_transfer("US", "dpf", **DPF_LISTED)
        self.assertEqual(status, "NEEDS_REVIEW")
        self.assertEqual(sev, "MEDIUM")
        self.assertIn("HR data", detail)

    def test_hr_only_certification_does_not_cover_non_hr_data(self):
        status, sev, detail = assess_transfer(
            "US",
            "dpf",
            dpf_certified=True,
            dpf_covers_hr_data=True,
            includes_hr_data=False,
            includes_non_hr_data=True,
        )
        self.assertEqual((status, sev), ("MISSING", "HIGH"))
        self.assertIn("non-HR data", detail)

    def test_hr_only_certification_with_unknown_non_hr_scope_needs_review(self):
        status, sev, detail = assess_transfer(
            "US", "dpf", dpf_certified=True, dpf_covers_hr_data=True, includes_hr_data=True
        )
        self.assertEqual((status, sev), ("NEEDS_REVIEW", "MEDIUM"))
        self.assertIn("non-HR data", detail)

    def test_hr_only_certification_covers_an_hr_only_transfer(self):
        status, sev, _ = assess_transfer(
            "US",
            "dpf",
            dpf_certified=True,
            dpf_covers_hr_data=True,
            includes_hr_data=True,
            includes_non_hr_data=False,
        )
        self.assertEqual((status, sev), ("PRESENT", "LOW"))

    def _dpf_dpa(self, certified, includes_hr_data=False, covers_hr_data=None):
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["art28_clauses"]["subprocessor_flowdown"] = True  # isolate the transfer findings
        if includes_hr_data is not None:
            dpa["processing"]["includes_hr_data"] = includes_hr_data
        dpa["transfers"]["mechanisms"]["US"] = "dpf"
        dpa["transfers"]["dpf_certified"] = {"US": certified}
        dpa["transfers"]["dpf_covers_non_hr_data"] = {"US": True}
        support_tools = dpa["subprocessors"][1]
        support_tools["transfer_mechanism"] = "dpf"
        support_tools["dpf_certified"] = certified
        support_tools["dpf_covers_non_hr_data"] = True
        if covers_hr_data is not None:
            dpa["transfers"]["dpf_covers_hr_data"] = {"US": covers_hr_data}
            support_tools["dpf_covers_hr_data"] = covers_hr_data
        return dpa

    US_TRANSFERS = ("transfer.us", "transfer.subprocessor.support_tools_llc")

    def test_certified_dpf_transfers_need_no_transfer_impact_assessment(self):
        packet = build_packet(self._dpf_dpa(certified=True))
        for rule_id in self.US_TRANSFERS:
            finding = _by_id(packet, rule_id)
            self.assertEqual(finding.status, "PRESENT")
            self.assertIn("Art. 44-45", finding.citation)
            self.assertIn("Commission Implementing Decision (EU) 2023/1795", finding.citation)
        self.assertNotIn("transfer.impact_assessment", {f.rule_id for f in packet.findings})
        self.assertEqual(packet.review_state, "CLEARED_FOR_REVIEW")

    def test_uncertified_dpf_transfers_block_the_packet(self):
        packet = build_packet(self._dpf_dpa(certified=False))
        for rule_id in self.US_TRANSFERS:
            finding = _by_id(packet, rule_id)
            self.assertEqual(finding.status, "MISSING")
            self.assertEqual(finding.severity, "HIGH")
        self.assertIn("Data Privacy Framework List", _by_id(packet, "transfer.us").remediation)
        self.assertEqual(packet.review_state, "BLOCKED")

    def test_hr_data_with_hr_certification_clears_the_packet(self):
        packet = build_packet(self._dpf_dpa(certified=True, includes_hr_data=True, covers_hr_data=True))
        for rule_id in self.US_TRANSFERS:
            self.assertEqual(_by_id(packet, rule_id).status, "PRESENT")
        self.assertEqual(packet.review_state, "CLEARED_FOR_REVIEW")

    def test_hr_data_without_hr_certification_blocks_the_packet(self):
        packet = build_packet(self._dpf_dpa(certified=True, includes_hr_data=True, covers_hr_data=False))
        for rule_id in self.US_TRANSFERS:
            finding = _by_id(packet, rule_id)
            self.assertEqual((finding.status, finding.severity), ("MISSING", "HIGH"))
            self.assertIn("HR data", finding.detail)
        self.assertEqual(packet.review_state, "BLOCKED")

    def test_omitted_hr_scope_sends_the_packet_to_review(self):
        packet = build_packet(self._dpf_dpa(certified=True, includes_hr_data=None))
        for rule_id in self.US_TRANSFERS:
            finding = _by_id(packet, rule_id)
            self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "MEDIUM"))
        self.assertEqual(packet.review_state, "NEEDS_REVIEW")


class AdequateDestinationWithOtherMechanism(unittest.TestCase):
    """A destination with its own adequacy decision is not worse off for a recorded mechanism."""

    def test_derogation_to_an_adequate_country_goes_to_review_not_block(self):
        status, sev, detail = assess_transfer("GB", "derogation_art49")
        self.assertEqual((status, sev), ("NEEDS_REVIEW", "LOW"))
        self.assertIn("adequacy decision (Art. 45)", detail)
        self.assertIn("Art. 49(1)", detail)

    def test_dpf_to_an_adequate_country_goes_to_review_not_block(self):
        status, sev, detail = assess_transfer(
            "CH", "dpf", dpf_certified=True, dpf_covers_non_hr_data=True, includes_hr_data=False
        )
        self.assertEqual((status, sev), ("NEEDS_REVIEW", "LOW"))
        self.assertIn("United States", detail)

    def test_packet_points_back_to_the_adequacy_decision(self):
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["transfers"]["destinations"].append("GB")
        dpa["transfers"]["mechanisms"]["GB"] = "derogation_art49"
        finding = _by_id(build_packet(dpa), "transfer.gb")
        self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "LOW"))
        self.assertEqual(finding.citation, "GDPR Art. 44-45")
        self.assertIn("Art. 45 adequacy decision for GB", finding.remediation)


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


class Art49DerogationAssessment(unittest.TestCase):
    """EDPB Guidelines 2/2018: derogations are interpreted restrictively, not for systematic transfers."""

    def test_derogation_for_systematic_transfer_is_treated_like_a_missing_basis(self):
        derogation = assess_transfer("IN", "derogation_art49")
        no_mechanism = assess_transfer("IN", "none")
        self.assertEqual(derogation[:2], ("MISSING", "HIGH"))
        self.assertEqual(derogation[:2], no_mechanism[:2])
        self.assertIn("EDPB Guidelines 2/2018", derogation[2])
        self.assertIn("section 1", derogation[2])
        self.assertIn("can basically be deemed systematic and repeated", derogation[2])
        self.assertIn("this tool treats such a derogation as a missing basis", derogation[2])

    def test_derogation_for_occasional_transfer_needs_review(self):
        status, sev, detail = assess_transfer("IN", "derogation_art49", occasional_and_not_repetitive=True)
        self.assertEqual(status, "NEEDS_REVIEW")
        self.assertEqual(sev, "MEDIUM")
        self.assertIn("restrictively", detail)

    def _derogation_dpa(self, occasional):
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["art28_clauses"]["subprocessor_flowdown"] = True  # isolate the transfer findings
        dpa["transfers"]["mechanisms"]["US"] = "derogation_art49"
        dpa["subprocessors"][1]["transfer_mechanism"] = "derogation_art49"
        if occasional:
            dpa["transfers"]["occasional_and_not_repetitive"] = {"US": True}
            dpa["subprocessors"][1]["occasional_and_not_repetitive"] = True
        return dpa

    def test_systematic_derogation_transfers_block_the_packet(self):
        packet = build_packet(self._derogation_dpa(occasional=False))
        for rule_id in ("transfer.us", "transfer.subprocessor.support_tools_llc"):
            finding = _by_id(packet, rule_id)
            self.assertEqual((finding.status, finding.severity), ("MISSING", "HIGH"))
            self.assertIn("Art. 44, 49; EDPB Guidelines 2/2018, section 1", finding.citation)
        remediation = _by_id(packet, "transfer.us").remediation
        self.assertIn("Art. 45", remediation)
        self.assertIn("Art. 46", remediation)
        self.assertIn("occasional and not repetitive", remediation)
        self.assertEqual(packet.review_state, "BLOCKED")

    def test_occasional_derogation_transfers_go_to_review_not_block(self):
        packet = build_packet(self._derogation_dpa(occasional=True))
        for rule_id in ("transfer.us", "transfer.subprocessor.support_tools_llc"):
            finding = _by_id(packet, rule_id)
            self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "MEDIUM"))
        self.assertIn("Art. 49(1)", _by_id(packet, "transfer.us").remediation)
        self.assertEqual(packet.review_state, "NEEDS_REVIEW")

    def test_missing_basis_no_longer_offers_a_derogation_as_the_cure(self):
        finding = _by_id(build_packet(SAMPLE), "transfer.us")
        self.assertEqual(finding.remediation, "Record an Art. 45 adequacy basis or an Art. 46 safeguard for US.")
        self.assertIn("has no recorded Chapter V basis", finding.detail)
        self.assertIn("Data Privacy Framework", finding.detail)


class DataSubjectCategories(unittest.TestCase):
    """Art. 28(3) first subparagraph: the contract sets out the categories of data subjects."""

    def test_data_types_use_the_statutory_wording(self):
        # Art. 28(3) speaks of "the type of personal data and categories of data subjects".
        finding = _by_id(build_packet(SAMPLE), "processing.data_types")
        self.assertEqual(finding.title, "Processing description: type of personal data")
        self.assertEqual(finding.status, "PRESENT")

    def test_listed_categories_of_data_subjects_are_present(self):
        finding = _by_id(build_packet(SAMPLE), "processing.data_subjects")
        self.assertEqual(finding.status, "PRESENT")
        self.assertEqual(finding.citation, "GDPR Art. 28(3)")
        self.assertIn("customer end users", finding.detail)

    def test_missing_categories_of_data_subjects_are_flagged(self):
        for missing in (None, []):
            dpa = json.loads(json.dumps(SAMPLE))
            if missing is None:
                del dpa["processing"]["data_subjects"]
            else:
                dpa["processing"]["data_subjects"] = missing
            finding = _by_id(build_packet(dpa), "processing.data_subjects")
            self.assertEqual(finding.status, "MISSING")
            self.assertEqual(finding.severity, "MEDIUM")
            self.assertTrue(finding.remediation)


class RecordedFlagShape(unittest.TestCase):
    """Recorded yes/no facts must be JSON booleans; a wrong shape is refused, not guessed."""

    def _dpa(self):
        return json.loads(json.dumps(SAMPLE))

    def test_per_country_flag_given_as_a_scalar_is_refused(self):
        dpa = self._dpa()
        dpa["transfers"]["dpf_certified"] = True
        with self.assertRaisesRegex(InvalidInputError, "transfers.dpf_certified must be an object"):
            build_packet(dpa)

    def test_string_instead_of_boolean_is_refused(self):
        dpa = self._dpa()
        dpa["processing"]["includes_hr_data"] = "false"
        with self.assertRaisesRegex(InvalidInputError, "processing.includes_hr_data must be true or false"):
            build_packet(dpa)

    def test_country_keyed_value_must_be_boolean(self):
        dpa = self._dpa()
        dpa["transfers"]["occasional_and_not_repetitive"] = {"US": "yes"}
        with self.assertRaisesRegex(InvalidInputError, "occasional_and_not_repetitive.US"):
            build_packet(dpa)

    def test_subprocessor_flag_must_be_boolean(self):
        dpa = self._dpa()
        dpa["subprocessors"][1]["dpf_certified"] = 1
        with self.assertRaisesRegex(InvalidInputError, r"subprocessors\[1\].dpf_certified"):
            build_packet(dpa)


class CuredPacket(unittest.TestCase):
    def test_fixing_defects_clears_high_findings(self):
        cured = json.loads(json.dumps(SAMPLE))
        cured["art28_clauses"]["subprocessor_flowdown"] = True
        cured["transfers"]["mechanisms"]["US"] = "sccs"
        cured["transfers"]["transfer_impact_assessment"] = True
        cured["subprocessors"][1]["transfer_mechanism"] = "sccs"
        packet = build_packet(cured)
        self.assertEqual(packet.summary["high_open"], 0)
        # The SCC transfers still need a lawyer's review, so the packet is not cleared.
        self.assertEqual(packet.review_state, "NEEDS_REVIEW")

    def test_scc_findings_cite_the_scc_decision_and_supplementary_measures(self):
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["transfers"]["mechanisms"]["US"] = "sccs"
        packet = build_packet(dpa)
        transfer = _by_id(packet, "transfer.us")
        self.assertEqual(transfer.citation, "GDPR Art. 44-46; Commission Implementing Decision (EU) 2021/914")
        self.assertIn("SCCs of Commission Implementing Decision (EU) 2021/914", transfer.remediation)
        tia = _by_id(packet, "transfer.impact_assessment")
        self.assertEqual(tia.status, "NEEDS_REVIEW")
        self.assertEqual(tia.citation, "GDPR Art. 46 (CJEU C-311/18); EDPB Recommendations 01/2020")
        self.assertIn("version 2.0, adopted 18 June 2021", tia.remediation)


if __name__ == "__main__":
    unittest.main()
