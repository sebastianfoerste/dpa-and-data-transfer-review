"""The adequacy reference data and the Chapter V bases beyond the SCCs, written from the source texts.

Every expected value below was read on EUR-Lex on 2026-11-10: the GDPR (CELEX 32016R0679), Art. 40(3),
42(2), 45(1), 45(9) and 46; the operative part of each adequacy decision, its date and its Official
Journal reference; the EUR-Lex record of each decision's status and amendments; and the General Court's
judgment in Latombe v Commission (T-553/23, CELEX 62023TJ0553) with the appeal EUR-Lex records against it.
"""

import json
import unittest
from pathlib import Path

from dpa_review.checks import (
    ADEQUACY,
    ADEQUACY_VERIFIED_ON,
    DPF_ADEQUACY,
    DPF_STATUS_NOTE,
    SAFEGUARDS,
    TRANSFER_MECHANISMS,
    assess_transfer,
    relies_on_art46_safeguard,
)
from dpa_review.contract import json_schema, violations
from dpa_review.facts import rule_facts
from dpa_review.review import OPEN_STATUSES, build_packet
from dpa_review.transfer_graph import build_transfer_evidence_graph

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "data" / "sample_dpa.json").read_text(encoding="utf-8"))

# Code: (act, date of adoption, Official Journal, adopted under Directive 95/46/EC).
DECISIONS = {
    "AD": ("Commission Decision 2010/625/EU", "19 October 2010", "OJ L 277, 21.10.2010, p. 27", True),
    "AR": ("Commission Decision 2003/490/EC", "30 June 2003", "OJ L 168, 5.7.2003, p. 19", True),
    "BR": ("Commission Implementing Decision (EU) 2026/179", "26 January 2026", "OJ L, 2026/179, 28.1.2026", False),
    "CA": ("Commission Decision 2002/2/EC", "20 December 2001", "OJ L 2, 4.1.2002, p. 13", True),
    "CH": ("Commission Decision 2000/518/EC", "26 July 2000", "OJ L 215, 25.8.2000, p. 1", True),
    "FO": ("Commission Decision 2010/146/EU", "5 March 2010", "OJ L 58, 9.3.2010, p. 17", True),
    "GB": ("Commission Implementing Decision (EU) 2021/1772", "28 June 2021", "OJ L 360, 11.10.2021, p. 1", False),
    "GG": ("Commission Decision 2003/821/EC", "21 November 2003", "OJ L 308, 25.11.2003, p. 27", True),
    "IL": ("Commission Decision 2011/61/EU", "31 January 2011", "OJ L 27, 1.2.2011, p. 39", True),
    "IM": ("Commission Decision 2004/411/EC", "28 April 2004", "OJ L 151, 30.4.2004, p. 48", True),
    "JE": ("Commission Decision 2008/393/EC", "8 May 2008", "OJ L 138, 28.5.2008, p. 21", True),
    "JP": ("Commission Implementing Decision (EU) 2019/419", "23 January 2019", "OJ L 76, 19.3.2019, p. 1", False),
    "KR": ("Commission Implementing Decision (EU) 2022/254", "17 December 2021", "OJ L 44, 24.2.2022, p. 1", False),
    "NZ": ("Commission Implementing Decision 2013/65/EU", "19 December 2012", "OJ L 28, 30.1.2013, p. 12", True),
    "UY": ("Commission Implementing Decision 2012/484/EU", "21 August 2012", "OJ L 227, 23.8.2012, p. 11", True),
}

# The words of each decision's own scope limit (Article 1, and Article 2 for Israel).
SCOPE_WORDS = {
    "BR": ["controllers and processors in Brazil subject to the General Data Protection Law (LGPD)"],
    "CA": ["recipients subject to the Personal Information Protection and Electronic Documents Act"],
    "FO": ["recipients subject to the Act on Processing of Personal Data (the Faeroese Act)"],
    "IL": [
        "automated international transfers of personal data",
        "further automated processing in Israel",
        "the State of Israel as defined in accordance with international law",
    ],
    "JP": [
        "personal information handling business operators in Japan subject to the Act on the Protection of "
        "Personal Information as complemented by the Supplementary Rules",
        "press organisations, persons engaged in professional writing, universities and other organisations or "
        "groups aimed at academic studies, religious bodies and political bodies",
    ],
    "KR": [
        "entities in the Republic of Korea subject to the Personal Information Protection Act as complemented "
        "by the additional safeguards",
        "religious organisations (missionary activities)",
        "political parties (nomination of candidates)",
        "subject to oversight by the Financial Services Commission for the processing of personal credit "
        "information under the Credit Information Act",
    ],
}
LIMITED = set(SCOPE_WORDS)
UNLIMITED = set(DECISIONS) - LIMITED
NEW_SAFEGUARDS = (
    "public_bodies_instrument",
    "sa_standard_clauses",
    "code_of_conduct",
    "certification",
    "authorised_clauses",
    "administrative_arrangement",
)
SCC_DECISION = "Commission Implementing Decision (EU) 2021/914"


def _clean_dpa(country, mechanism, tia=False):
    """The sample with its planted defects cured and one direct transfer, to `country` on `mechanism`."""
    dpa = json.loads(json.dumps(SAMPLE))
    dpa["art28_clauses"]["subprocessor_flowdown"] = True
    dpa["subprocessors"] = [{"name": "EU Hosting SARL", "country": "FR", "purpose": "hosting"}]
    dpa["transfers"] = {
        "destinations": [country],
        "mechanisms": {country: mechanism},
        "transfer_impact_assessment": tia,
    }
    return dpa


def _by_id(packet, rule_id):
    return next(f for f in packet.findings if f.rule_id == rule_id)


def _rule_ids(packet):
    return {f.rule_id for f in packet.findings}


class AdequacyReferenceData(unittest.TestCase):
    def test_the_list_is_the_verified_list(self):
        self.assertEqual(ADEQUACY_VERIFIED_ON, "2026-11-10")
        self.assertEqual(set(ADEQUACY), set(DECISIONS))

    def test_every_entry_matches_its_decision(self):
        for code, (act, adopted, oj, directive_era) in DECISIONS.items():
            with self.subTest(country=code):
                decision = ADEQUACY[code]
                self.assertEqual(decision.country, code)
                self.assertEqual((decision.act, decision.adopted, decision.oj), (act, adopted, oj))
                self.assertEqual(decision.directive_era, directive_era)
                self.assertEqual(decision.limited, code in LIMITED)

    def test_scope_limits_use_the_decisions_words(self):
        for code, phrases in SCOPE_WORDS.items():
            for phrase in phrases:
                with self.subTest(country=code, phrase=phrase):
                    self.assertIn(phrase, ADEQUACY[code].scope_limit)
        for code in UNLIMITED:
            with self.subTest(country=code):
                self.assertEqual(ADEQUACY[code].scope_limit, "")

    def test_brazil_is_on_the_list_under_decision_2026_179(self):
        brazil = ADEQUACY["BR"]
        self.assertEqual(brazil.celex, "32026D0179")
        self.assertEqual(
            brazil.scope_limit,
            "Its Article 1 covers only personal data transferred to controllers and processors in Brazil "
            "subject to the General Data Protection Law (LGPD).",
        )

    def test_the_uk_decision_as_amended_in_2025(self):
        # Implementing Decision (EU) 2025/2574 repealed Article 1(2) (the immigration-control exclusion)
        # and replaced Article 4: the decision now expires on 27 December 2031.
        uk = ADEQUACY["GB"]
        self.assertFalse(uk.limited)
        self.assertEqual(uk.expires, "27 December 2031")
        self.assertEqual(uk.amending_acts, ("Commission Implementing Decision (EU) 2025/2574",))
        self.assertIn("repealed its Article 1(2)", uk.amended)
        self.assertIn("Implementing Decision (EU) 2025/1226", uk.amended)

    def test_the_us_decision_is_reached_only_through_the_dpf(self):
        self.assertNotIn("US", ADEQUACY)
        self.assertEqual(DPF_ADEQUACY.act, "Commission Implementing Decision (EU) 2023/1795")
        self.assertEqual(DPF_ADEQUACY.adopted, "10 July 2023")
        self.assertEqual(DPF_ADEQUACY.oj, "OJ L 231, 20.9.2023, p. 118")
        self.assertIn("'Data Privacy Framework List'", DPF_ADEQUACY.scope_limit)


class AdequacyFindings(unittest.TestCase):
    """A destination on the list is PRESENT; the finding names the decision and any scope limit."""

    def test_every_listed_country_is_covered_by_its_decision(self):
        for code, (act, adopted, _, directive_era) in DECISIONS.items():
            for mechanism in ("adequacy", "none"):
                with self.subTest(country=code, mechanism=mechanism):
                    status, severity, detail = assess_transfer(code, mechanism)
                    self.assertEqual((status, severity), ("PRESENT", "LOW"))
                    self.assertIn(f"Art. 45(1); {act} of {adopted}", detail)
                    self.assertEqual("in force under Art. 45(9)" in detail, directive_era)
                    self.assertEqual("Confirm that the importer is within it." in detail, code in LIMITED)

    def test_brazil_recorded_as_adequacy_is_covered(self):
        # Brazil used to be off the list, so this transfer was MISSING (HIGH) and the packet BLOCKED.
        packet = build_packet(_clean_dpa("BR", "adequacy"))
        finding = _by_id(packet, "transfer.br")
        self.assertEqual((finding.status, finding.severity), ("PRESENT", "LOW"))
        self.assertEqual(finding.citation, "GDPR Art. 44, 45(1); Commission Implementing Decision (EU) 2026/179")
        self.assertIn("26 January 2026", finding.detail)
        self.assertIn("General Data Protection Law (LGPD)", finding.detail)
        self.assertEqual(packet.review_state, "CLEARED_FOR_REVIEW")

    def test_a_directive_era_decision_cites_article_45_9(self):
        self.assertEqual(
            _by_id(build_packet(_clean_dpa("CA", "adequacy")), "transfer.ca").citation,
            "GDPR Art. 44, 45(1), 45(9); Commission Decision 2002/2/EC",
        )

    def test_the_uk_citation_names_the_amending_decision(self):
        finding = _by_id(build_packet(_clean_dpa("GB", "adequacy")), "transfer.gb")
        self.assertEqual(
            finding.citation,
            "GDPR Art. 44, 45(1); Commission Implementing Decision (EU) 2021/1772; "
            "Commission Implementing Decision (EU) 2025/2574",
        )
        self.assertIn("which expires on 27 December 2031", finding.detail)

    def test_adequacy_for_a_country_off_the_list_still_blocks(self):
        # The list is verified and dated, so adequacy recorded for a country off it is a missing basis.
        status, severity, detail = assess_transfer("IN", "adequacy")
        self.assertEqual((status, severity), ("MISSING", "HIGH"))
        self.assertIn("checked against the decisions on EUR-Lex on 2026-11-10", detail)
        remediation = _by_id(build_packet(_clean_dpa("IN", "adequacy")), "transfer.in").remediation
        self.assertIn("checked against EUR-Lex on 2026-11-10", remediation)


class SafeguardForAnAdequateDestination(unittest.TestCase):
    """Art. 45(1) and 46(1): a safeguard is the basis only in the absence of an adequacy decision."""

    def test_a_decision_without_a_scope_limit_covers_the_transfer(self):
        for code in sorted(UNLIMITED):
            for mechanism in SAFEGUARDS:
                with self.subTest(country=code, mechanism=mechanism):
                    status, severity, detail = assess_transfer(code, mechanism)
                    self.assertEqual((status, severity), ("PRESENT", "LOW"))
                    self.assertIn("sets no limit on the recipients or the purposes it covers", detail)
                    self.assertIn("needs no Art. 46 safeguard and no transfer impact assessment", detail)
                    self.assertIn("may still serve other purposes", detail)

    def test_no_transfer_impact_assessment_is_asked_for_and_the_packet_clears(self):
        packet = build_packet(_clean_dpa("CH", "sccs"))
        finding = _by_id(packet, "transfer.ch")
        self.assertEqual(finding.status, "PRESENT")
        self.assertEqual(finding.citation, "GDPR Art. 44, 45(1), 45(9); Commission Decision 2000/518/EC")
        self.assertNotIn("transfer.impact_assessment", _rule_ids(packet))
        self.assertEqual(packet.review_state, "CLEARED_FOR_REVIEW")
        self.assertFalse(relies_on_art46_safeguard("CH", "sccs"))

    def test_a_scope_limited_decision_asks_whether_the_importer_is_covered(self):
        for code in sorted(LIMITED):
            for mechanism in SAFEGUARDS:
                with self.subTest(country=code, mechanism=mechanism):
                    status, severity, detail = assess_transfer(code, mechanism)
                    self.assertEqual((status, severity), ("NEEDS_REVIEW", "MEDIUM"))
                    self.assertIn(ADEQUACY[code].scope_limit, detail)
                    self.assertIn("does not record whether the importer is within the decision's scope", detail)
                    self.assertIn(f"If it is not, the transfer relies on {SAFEGUARDS[mechanism].short}", detail)
                    self.assertIn("The input records no transfer impact assessment.", detail)

    def test_a_recorded_assessment_lowers_the_scope_question_to_low(self):
        status, severity, detail = assess_transfer("JP", "sccs", impact_assessment_recorded=True)
        self.assertEqual((status, severity), ("NEEDS_REVIEW", "LOW"))
        self.assertIn("A transfer impact assessment is recorded.", detail)

    def test_the_scope_question_replaces_the_generic_assessment_finding(self):
        packet = build_packet(_clean_dpa("JP", "sccs"))
        finding = _by_id(packet, "transfer.jp")
        self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "MEDIUM"))
        self.assertEqual(
            finding.citation,
            "GDPR Art. 44, 45(1), 46(2)(c); Commission Implementing Decision (EU) 2019/419; "
            f"{SCC_DECISION}; EDPB Recommendations 01/2020",
        )
        self.assertEqual(
            finding.remediation,
            "Confirm whether the importer in JP is within the scope of Article 1 of Commission Implementing "
            "Decision (EU) 2019/419. If it is, record the mechanism as adequacy; if not, confirm that the SCCs "
            f"of {SCC_DECISION} cover the transfer to JP, with a transfer impact assessment and any "
            "supplementary measures (EDPB Recommendations 01/2020).",
        )
        self.assertNotIn("transfer.impact_assessment", _rule_ids(packet))
        self.assertEqual(packet.review_state, "NEEDS_REVIEW")
        cured = build_packet(_clean_dpa("JP", "sccs", tia=True))
        self.assertEqual(_by_id(cured, "transfer.jp").severity, "LOW")
        self.assertEqual(cured.review_state, "NEEDS_REVIEW")

    def test_a_directive_era_decision_with_a_scope_limit_cites_both_bases(self):
        finding = _by_id(build_packet(_clean_dpa("CA", "bcr")), "transfer.ca")
        self.assertEqual(
            finding.citation,
            "GDPR Art. 44, 45(1), 45(9), 46(2)(b), 47; Commission Decision 2002/2/EC; EDPB Recommendations 01/2020",
        )

    def test_a_sub_processor_gets_the_same_question_by_name(self):
        dpa = _clean_dpa("JP", "adequacy")
        dpa["subprocessors"].append(
            {"name": "Maple Support Inc", "country": "CA", "purpose": "support", "transfer_mechanism": "sccs"}
        )
        packet = build_packet(dpa)
        finding = _by_id(packet, "transfer.subprocessor.maple_support_inc")
        self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "MEDIUM"))
        self.assertEqual(
            finding.citation,
            "GDPR Art. 28(4) / Art. 44, 45(1), 45(9), 46(2)(c); Commission Decision 2002/2/EC; "
            f"{SCC_DECISION}; EDPB Recommendations 01/2020",
        )
        self.assertTrue(finding.remediation.startswith("Confirm whether Maple Support Inc is within the scope"))
        self.assertIn("the transfer to Maple Support Inc in CA", finding.remediation)
        self.assertNotIn("transfer.impact_assessment", _rule_ids(packet))

    def test_the_scope_question_reads_the_recorded_assessment(self):
        dpa = _clean_dpa("JP", "sccs", tia=True)
        dpa["subprocessors"].append({"name": "Maple Support Inc", "country": "CA", "transfer_mechanism": "sccs"})
        self.assertIn(("transfers", "transfer_impact_assessment"), rule_facts(dpa, "transfer.jp"))
        self.assertIn(
            ("transfers", "transfer_impact_assessment"),
            rule_facts(dpa, "transfer.subprocessor.maple_support_inc"),
        )
        for country, mechanism in (("CH", "sccs"), ("JP", "adequacy"), ("IN", "sccs")):
            with self.subTest(country=country, mechanism=mechanism):
                other = _clean_dpa(country, mechanism, tia=True)
                self.assertNotIn(
                    ("transfers", "transfer_impact_assessment"), rule_facts(other, f"transfer.{country.lower()}")
                )

    def test_the_graph_shows_the_scope_question_without_the_assessment(self):
        dpa = _clean_dpa("KR", "sccs")
        packet = build_packet(dpa)
        edges = {edge["edge_id"]: edge for edge in build_transfer_evidence_graph(dpa, packet)["edges"]}
        edge = edges["processor-direct-to-kr"]
        self.assertEqual(edge["status"], "review")
        self.assertEqual(edge["control_refs"], ["transfer.kr"])

    def test_the_us_safeguard_path_still_needs_the_assessment_and_points_to_the_dpf(self):
        packet = build_packet(_clean_dpa("US", "sccs"))
        finding = _by_id(packet, "transfer.us")
        self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "LOW"))
        self.assertIn("covers only organisations on the Data Privacy Framework List", finding.detail)
        self.assertIn("record the mechanism as dpf", finding.detail)
        self.assertEqual(_by_id(packet, "transfer.impact_assessment").status, "NEEDS_REVIEW")


class DataPrivacyFrameworkStatus(unittest.TestCase):
    """The DPF finding asks the reviewer to re-check the decision's status, citing what EUR-Lex records."""

    def test_the_note_cites_the_judgment_and_the_appeal(self):
        self.assertIn("Latombe v Commission, T-553/23, judgment of 3 September 2025", DPF_STATUS_NOTE)
        self.assertIn("dismissed an action for its annulment", DPF_STATUS_NOTE)
        self.assertIn("Case C-703/25 P, brought on 31 October 2025", DPF_STATUS_NOTE)
        self.assertIn("no judgment on it as of 2026-11-10", DPF_STATUS_NOTE)

    def test_findings_that_rely_on_the_dpf_carry_the_note(self):
        cases = {
            "present": dict(dpf_certified=True, dpf_covers_non_hr_data=True, includes_hr_data=False),
            "hr scope unknown": dict(dpf_certified=True, dpf_covers_non_hr_data=True),
            "no data recorded": dict(dpf_certified=True, includes_hr_data=False, includes_non_hr_data=False),
        }
        for name, facts in cases.items():
            with self.subTest(case=name):
                self.assertIn(DPF_STATUS_NOTE, assess_transfer("US", "dpf", **facts)[2])
        # An uncertified importer has no DPF basis to re-check.
        self.assertNotIn(DPF_STATUS_NOTE, assess_transfer("US", "dpf")[2])


class OtherArticle46Safeguards(unittest.TestCase):
    """Art. 46(2)(a), (d), (e), (f) and 46(3)(a), (b): recorded, sent to review, never 'no safeguard'."""

    CITATIONS = {
        "public_bodies_instrument": "GDPR Art. 44, 46(2)(a)",
        "sa_standard_clauses": "GDPR Art. 44, 46(2)(d)",
        "code_of_conduct": "GDPR Art. 44, 46(2)(e), 40(3)",
        "certification": "GDPR Art. 44, 46(2)(f), 42(2)",
        "authorised_clauses": "GDPR Art. 44, 46(3)(a)",
        "administrative_arrangement": "GDPR Art. 44, 46(3)(b)",
    }
    CONFIRM = {
        "public_bodies_instrument": ["legally binding and enforceable instrument between public authorities or bodies"],
        "sa_standard_clauses": ["adopted the clauses and the Commission approved them", "Art. 93(2)"],
        "code_of_conduct": ["approved under Art. 40(5)", "general validity under Art. 40(9)", "(Art. 40(3))"],
        "certification": ["approved under Art. 42(5)", "(Art. 42(2))"],
        "authorised_clauses": ["authorised the clauses (Art. 46(3))", "Article 26(2) of Directive 95/46/EC", "(Art. 46(5))"],
        "administrative_arrangement": ["authorised the provisions (Art. 46(3))", "enforceable and effective data subject rights"],
    }

    def test_each_is_a_recognised_mechanism(self):
        self.assertEqual(set(NEW_SAFEGUARDS) | {"sccs", "bcr"}, set(SAFEGUARDS))
        for mechanism in NEW_SAFEGUARDS:
            with self.subTest(mechanism=mechanism):
                self.assertIn(mechanism, TRANSFER_MECHANISMS)
                self.assertTrue(relies_on_art46_safeguard("IN", mechanism))

    def test_each_goes_to_review_with_its_exact_citation(self):
        for mechanism in NEW_SAFEGUARDS:
            with self.subTest(mechanism=mechanism):
                packet = build_packet(_clean_dpa("IN", mechanism))
                finding = _by_id(packet, "transfer.in")
                self.assertEqual((finding.status, finding.severity), ("NEEDS_REVIEW", "LOW"))
                self.assertEqual(finding.citation, self.CITATIONS[mechanism])
                self.assertIn("The tool cannot verify", finding.detail)
                self.assertNotIn("no recorded Chapter V basis", finding.detail)
                self.assertNotIn("not a Chapter V basis this tool recognises", finding.detail)
                for phrase in self.CONFIRM[mechanism]:
                    self.assertIn(phrase, finding.detail)
                self.assertIn("transfer impact assessment", finding.remediation)
                self.assertEqual(packet.review_state, "NEEDS_REVIEW")

    def test_each_needs_a_transfer_impact_assessment_like_the_sccs(self):
        for mechanism in NEW_SAFEGUARDS:
            with self.subTest(mechanism=mechanism):
                tia = _by_id(build_packet(_clean_dpa("IN", mechanism)), "transfer.impact_assessment")
                self.assertEqual((tia.status, tia.severity), ("NEEDS_REVIEW", "MEDIUM"))
                recorded = _by_id(build_packet(_clean_dpa("IN", mechanism, tia=True)), "transfer.impact_assessment")
                self.assertEqual(recorded.status, "PRESENT")

    def test_a_sub_processor_can_rely_on_one(self):
        dpa = _clean_dpa("JP", "adequacy")
        dpa["subprocessors"].append(
            {"name": "Ledger Services Ltd", "country": "IN", "transfer_mechanism": "certification"}
        )
        packet = build_packet(dpa)
        finding = _by_id(packet, "transfer.subprocessor.ledger_services_ltd")
        self.assertEqual(finding.status, "NEEDS_REVIEW")
        self.assertEqual(finding.citation, "GDPR Art. 28(4) / Art. 44, 46(2)(f), 42(2)")
        self.assertIn("transfer.impact_assessment", {f.rule_id for f in packet.findings if f.status in OPEN_STATUSES})

    def test_the_input_contract_accepts_each(self):
        schema = json_schema()
        enum = schema["properties"]["transfers"]["properties"]["mechanisms"]["additionalProperties"]["enum"]
        entry_enum = schema["properties"]["subprocessors"]["items"]["properties"]["transfer_mechanism"]["enum"]
        for mechanism in NEW_SAFEGUARDS:
            with self.subTest(mechanism=mechanism):
                self.assertEqual(violations(_clean_dpa("IN", mechanism)), [])
                dpa = _clean_dpa("JP", "adequacy")
                dpa["subprocessors"].append({"name": "Importer Ltd", "country": "IN", "transfer_mechanism": mechanism})
                self.assertEqual(violations(dpa), [])
                self.assertIn(mechanism, enum)
                self.assertIn(mechanism, entry_enum)

    def test_a_misspelt_value_is_refused_with_a_suggestion(self):
        found = [violation.message for violation in violations(_clean_dpa("IN", "code_of_conduc"))]
        self.assertTrue(any(message.endswith("did you mean 'code_of_conduct'?") for message in found), found)


if __name__ == "__main__":
    unittest.main()
