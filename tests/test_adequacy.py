"""The adequacy table and its scope conditions, tested against cases written from the Official Journal
snapshots before the rule code (tests/adequacy_cases.json) and against the snapshots themselves."""

import copy
import json
import re
import unittest
from datetime import date
from html.parser import HTMLParser

from dpa_review.checks import (
    ADEQUACY,
    DPF_ADEQUACY,
    EEA,
    INTERNATIONAL_ORGANISATIONS,
    SAFEGUARDS,
    TABLE_AS_OF,
    InvalidInputError,
    assess_transfer,
    check_transfers,
    relies_on_art46_safeguard,
    table_age,
)
from dpa_review.contract import json_schema, violations
from dpa_review.facts import rule_facts
from dpa_review.review import build_packet
from dpa_review.transfer_graph import build_transfer_evidence_graph
from tests.helpers import ROOT

CASES = json.loads((ROOT / "tests" / "adequacy_cases.json").read_text(encoding="utf-8"))["cases"]
MANIFEST = json.loads((ROOT / "sources" / "manifest.json").read_text(encoding="utf-8"))
SOURCE_FILES = {item["celex"]: ROOT / item["file"] for item in MANIFEST["sources"]}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


_TEXT_CACHE: dict[str, str] = {}


def snapshot_text(celex: str) -> str:
    """The text of a snapshot, without markup and with whitespace collapsed."""
    if celex not in _TEXT_CACHE:
        parser = _Text()
        parser.feed(SOURCE_FILES[celex].read_text(encoding="utf-8"))
        _TEXT_CACHE[celex] = _normalise(" ".join(parser.parts))
    return _TEXT_CACHE[celex]


class AdequacyCasesQuoteTheirSources(unittest.TestCase):
    def test_every_case_quotes_its_snapshot(self) -> None:
        for case in CASES:
            with self.subTest(case=case["id"]):
                source = case["source"]
                self.assertIn(source["celex"], SOURCE_FILES)
                self.assertIn(_normalise(source["quote"]), snapshot_text(source["celex"]))

    def test_case_ids_are_unique(self) -> None:
        ids = [case["id"] for case in CASES]
        self.assertEqual(len(ids), len(set(ids)))


def _dpa(fragment: dict) -> dict:
    """The smallest valid input with a case's fragment added to it."""
    dpa = {
        "processing": {},
        "art28_clauses": {},
        "breach_notification": {},
        "subprocessors": [],
        "transfers": {"destinations": []},
    }
    for key, value in copy.deepcopy(fragment).items():
        if isinstance(value, dict) and isinstance(dpa.get(key), dict):
            dpa[key].update(value)
        else:
            dpa[key] = value
    return dpa


def _case_finding(case: dict):
    dpa = _dpa(case["input"])
    expected = case["expected"]
    destinations = dpa["transfers"]["destinations"]
    rule = expected.get("rule") or f"transfer.{destinations[0].lower()}"
    findings = {finding.rule_id: finding for finding in check_transfers(dpa)}
    return dpa, findings, findings[rule]


# Every act a finding can rely on as an adequacy decision, to check a case that expects none.
_DECISION_ACTS = [decision.act for decision in (*ADEQUACY.values(), DPF_ADEQUACY)]


class AdequacyCasesGiveTheirExpectedFindings(unittest.TestCase):
    def test_every_case_input_meets_the_input_contract(self) -> None:
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertEqual(violations(_dpa(case["input"])), [])

    def test_every_case(self) -> None:
        for case in CASES:
            with self.subTest(case=case["id"]):
                _, findings, finding = _case_finding(case)
                expected = case["expected"]
                self.assertEqual((finding.status, finding.severity), (expected["status"], expected["severity"]), finding.detail)
                if expected["cites"] is None:
                    for act in _DECISION_ACTS:
                        self.assertNotIn(act, finding.citation)
                else:
                    self.assertIn(expected["cites"], finding.citation)
                if "detail_contains" in expected:
                    self.assertIn(expected["detail_contains"], finding.detail)
                self.assertEqual(
                    "transfer.impact_assessment" in findings, expected.get("impact_assessment_finding", False)
                )
                self.assertEqual(finding.remediation == "", finding.status == "PRESENT")

    def test_a_case_with_an_interpretation_says_so_where_it_decides(self) -> None:
        # The interpretation that decides a covered or not-covered importer is printed with the finding.
        for case_id in (
            "canada-private-commercial-organisation",
            "canada-public-body",
            "japan-public-body",
            "uruguay-no-automation-condition",
            "faroe-islands-no-recipient-input",
            "brazil-on-adoption-day",
            "us-dpf-on-adoption-day",
            "united-kingdom-on-expiry-day",
            "united-kingdom-day-after-expiry",
            "israel-automated-transfer",
        ):
            with self.subTest(case=case_id):
                case = next(item for item in CASES if item["id"] == case_id)
                self.assertIn("interpretation", case)
                self.assertIn("Interpretation:", _case_finding(case)[2].detail)


class UnknownNeverYieldsAdequacy(unittest.TestCase):
    def test_no_recorded_fact_never_clears_a_decision_with_conditions(self) -> None:
        for code, decision in ADEQUACY.items():
            if not decision.conditions:
                continue
            for mechanism in ("adequacy", "none", "dpf", "derogation_art49"):
                with self.subTest(country=code, mechanism=mechanism):
                    status, severity, _ = assess_transfer(code, mechanism)
                    self.assertNotEqual(status, "PRESENT")
                    self.assertEqual(severity, "HIGH")

    def test_an_unrecognised_value_reads_as_unknown(self) -> None:
        status, severity, detail = assess_transfer("CA", "adequacy", recipient={"recipient_type": "corporation"})
        self.assertEqual((status, severity), ("NEEDS_REVIEW", "HIGH"))
        self.assertIn('recorded: recipient_type "corporation"', detail)
        status, severity, _ = assess_transfer("IL", "adequacy", recipient={"automated_processing": "yes"})
        self.assertEqual((status, severity), ("NEEDS_REVIEW", "HIGH"))

    def test_a_recipient_fact_of_another_type_is_refused_without_the_contract(self) -> None:
        # build_packet without validate: a number is neither a recorded word nor a boolean, so it is refused.
        for fragment in (
            {"transfers": {"destinations": ["CA"], "recipient_type": {"CA": 1}}},
            {"subprocessors": [{"name": "Example Support Ltd", "country": "IL", "automated_processing": [True]}]},
        ):
            with self.subTest(fragment=fragment):
                with self.assertRaises(InvalidInputError):
                    check_transfers(_dpa(fragment))

    def test_a_fact_the_decision_does_not_read_changes_nothing(self) -> None:
        for code in ("CH", "GB", "BR", "UY", "EPO"):
            for facts in ({"recipient_type": "public_body"}, {"scope_carve_out": "applies"}, {"automated_processing": False}):
                with self.subTest(country=code, facts=facts):
                    self.assertEqual(assess_transfer(code, "adequacy", recipient=facts), assess_transfer(code, "adequacy"))
        base = assess_transfer("KR", "adequacy", recipient={"scope_carve_out": "none"})
        noisy = assess_transfer("KR", "adequacy", recipient={"scope_carve_out": "none", "recipient_type": "public_body"})
        self.assertEqual(base, noisy)

    def test_a_failed_condition_decides_even_when_another_is_unknown(self) -> None:
        status, severity, detail = assess_transfer("JP", "adequacy", recipient={"scope_carve_out": "applies"})
        self.assertEqual((status, severity), ("MISSING", "HIGH"))
        self.assertIn("Art. 1(2)", detail)
        self.assertNotIn("recipient_type not recorded", detail)


class UnmodelledLimitsAreStated(unittest.TestCase):
    # Regression: a covered finding stated neither the employment-data limit of the Canadian recital 5 the
    # condition rests on, nor the territorial limit of Article 2 of the Israeli decision, as not modelled.
    def test_canada_states_the_employment_data_limit_it_does_not_model(self) -> None:
        detail = assess_transfer("CA", "adequacy", recipient={"recipient_type": "private_commercial"})[2]
        self.assertIn("does not cover employment data used for non-commercial purposes", detail)
        self.assertIn(
            "Similarly it does not cover employment data used for non-commercial purposes other than that relating "
            "to employees in the federally regulated private sector",
            snapshot_text("32002D0002"),
        )

    def test_israel_states_the_territorial_limit_it_does_not_model(self) -> None:
        status, _, detail = assess_transfer("IL", "adequacy", recipient={"automated_processing": True})
        self.assertEqual(status, "PRESENT")
        self.assertIn("Interpretation: the input records no fact for the limit of Article 2", detail)
        self.assertIn(
            "This Decision concerns only the adequacy of protection provided in the State of Israel, as defined in "
            "accordance with international law",
            snapshot_text("32011D0061"),
        )


class ReviewDate(unittest.TestCase):
    def test_no_review_date_reads_the_table_as_it_stands(self) -> None:
        self.assertEqual(assess_transfer("GB", "adequacy")[:2], ("PRESENT", "LOW"))

    def test_a_date_and_a_string_give_the_same_finding(self) -> None:
        self.assertEqual(
            assess_transfer("GB", "adequacy", review_date="2031-12-28"),
            assess_transfer("GB", "adequacy", review_date=date(2031, 12, 28)),
        )

    def test_a_malformed_review_date_is_refused(self) -> None:
        for value in ("2031-13-01", "20261114", "2026-11-14T00:00:00", 20261114):
            with self.subTest(value=value):
                with self.assertRaises(InvalidInputError):
                    assess_transfer("GB", "adequacy", review_date=value)
                dpa = _dpa({"review_date": value, "transfers": {"destinations": ["GB"]}})
                self.assertTrue(violations(dpa))
                with self.assertRaises(InvalidInputError):
                    check_transfers(dpa)

    def test_a_review_date_before_an_amendment_is_a_review_state_for_every_mechanism(self) -> None:
        for mechanism in ("adequacy", "none", "dpf", "derogation_art49", *SAFEGUARDS):
            with self.subTest(mechanism=mechanism):
                status, severity, detail = assess_transfer("GB", mechanism, review_date="2025-12-18")
                self.assertEqual(status, "NEEDS_REVIEW")
                self.assertEqual(severity, "MEDIUM" if mechanism in SAFEGUARDS else "HIGH")
                self.assertIn("Commission Implementing Decision (EU) 2025/2574 of 19 December 2025", detail)

    def test_an_earlier_version_names_every_later_amendment(self) -> None:
        # Regression: a date before 2025/1226 named only that act, which moved the expiry, and not 2025/2574,
        # which repealed the immigration exclusion that decided whether the earlier version covered a transfer.
        detail = assess_transfer("GB", "adequacy", review_date="2023-01-01")[2]
        first = detail.index("Commission Implementing Decision (EU) 2025/1226 of 24 June 2025")
        second = detail.index("Commission Implementing Decision (EU) 2025/2574 of 19 December 2025")
        self.assertLess(first, second)
        self.assertIn("repealed its Article 1(2)", detail)
        between = assess_transfer("GB", "adequacy", review_date="2025-06-24")[2]
        self.assertNotIn("2025/1226 of 24 June 2025, which", between)
        self.assertIn("2025/2574 of 19 December 2025, which", between)

    def test_the_table_note_starts_the_day_after_the_table_date_for_every_decision(self) -> None:
        # Regression: the DPF findings (dpf, and a safeguard recorded for a US importer) left the note out.
        dpf = dict(
            dpf_certified=True, dpf_covers_non_hr_data=True, includes_hr_data=False, includes_non_hr_data=True
        )
        note = f"The adequacy table was last checked on {TABLE_AS_OF}"
        day_after = date.fromordinal(date.fromisoformat(TABLE_AS_OF).toordinal() + 1)
        for country, mechanism, facts in (
            ("CH", "adequacy", {}),
            ("US", "dpf", dpf),
            ("US", "sccs", {"impact_assessment_recorded": True}),
        ):
            with self.subTest(country=country, mechanism=mechanism):
                on_table_date = assess_transfer(country, mechanism, review_date=TABLE_AS_OF, **facts)
                after = assess_transfer(country, mechanism, review_date=day_after, **facts)
                self.assertNotIn(note, on_table_date[2])
                self.assertIn(note, after[2])
                self.assertEqual(on_table_date[:2], after[:2])

    def test_a_decision_that_did_not_apply_counts_as_no_decision_for_a_safeguard(self) -> None:
        self.assertTrue(relies_on_art46_safeguard("BR", "sccs", review_date=date(2026, 1, 25)))
        self.assertFalse(relies_on_art46_safeguard("BR", "sccs", review_date=date(2026, 1, 26)))
        self.assertTrue(relies_on_art46_safeguard("US", "bcr", review_date=date(2023, 7, 9)))


class TableIntegrity(unittest.TestCase):
    def test_every_entry_cites_a_snapshotted_decision(self) -> None:
        for decision in (*ADEQUACY.values(), DPF_ADEQUACY):
            with self.subTest(decision=decision.country):
                self.assertIn(decision.celex, SOURCE_FILES)
                for amendment in decision.amendments:
                    self.assertIn(amendment.celex, SOURCE_FILES)

    def test_number_date_and_journal_reference_match_the_snapshot(self) -> None:
        oj_by_celex = {item["celex"]: item["oj_reference"] for item in MANIFEST["sources"]}
        acts = [(d.act, d.adopted, d.oj, d.celex) for d in (*ADEQUACY.values(), DPF_ADEQUACY)]
        acts += [(a.act, a.adopted, None, a.celex) for d in ADEQUACY.values() for a in d.amendments]
        for act, adopted, oj, celex in acts:
            with self.subTest(act=act):
                text = snapshot_text(celex)
                number = re.search(r"\d{4}/\d+(/E[CU])?", act).group(0)
                self.assertIn(number, text)
                self.assertIn(f"of {adopted}", text)
                if oj is not None:
                    self.assertEqual(oj, oj_by_celex[celex])

    def test_operative_provisions_and_start_dates_match_the_snapshot(self) -> None:
        for decision in ADEQUACY.values():
            with self.subTest(decision=decision.country):
                text = snapshot_text(decision.celex)
                operative = text[text.index("HAS ADOPTED THIS DECISION") :]
                self.assertTrue(operative.startswith("HAS ADOPTED THIS DECISION: Article 1 "))
                # "Art. 1(1)" where Article 1 is set out in numbered paragraphs.
                numbered = operative.startswith("HAS ADOPTED THIS DECISION: Article 1 1. ")
                self.assertEqual(decision.provision == "Art. 1(1)", numbered and decision.country not in {"JP", "KR"})
                if decision.applies_from:
                    self.assertIn(
                        f"{decision.applies_from_source} This Decision shall apply from {decision.applies_from}.", text
                    )
                else:
                    self.assertNotIn("shall apply from", operative)
                    self.assertNotIn("shall enter into force", operative)
                    self.assertIn(f"Done at Brussels, {decision.adopted}", text)

    def test_the_uk_expiry_is_the_one_the_last_amendment_sets(self) -> None:
        uk = ADEQUACY["GB"]
        self.assertIn(f"This Decision shall expire on {uk.expires}", snapshot_text(uk.amendments[-1].celex))
        self.assertEqual([a.celex for a in uk.amendments], ["32025D1226", "32025D2574"])

    def test_the_european_patent_organisation_is_an_international_organisation(self) -> None:
        self.assertEqual(INTERNATIONAL_ORGANISATIONS, {"EPO"})
        self.assertNotIn("EPO", EEA)
        self.assertIn("The Organisation has its seat in Munich", snapshot_text("32025D1382"))


class TableAge(unittest.TestCase):
    def test_the_table_date_is_the_recheck_date_of_the_sources(self) -> None:
        self.assertEqual(TABLE_AS_OF, MANIFEST["recheck"]["date"])

    def test_age_is_counted_from_the_table_date(self) -> None:
        self.assertEqual(table_age(date(2026, 11, 14))["age_days"], 0)
        report = table_age(date(2026, 11, 21))
        self.assertEqual(report["age_days"], 7)
        self.assertEqual(report["decisions"], len(ADEQUACY) + 1)


class InputFactsGraphAndSchema(unittest.TestCase):
    def test_the_facts_a_condition_reads_are_the_findings_evidence(self) -> None:
        dpa = _dpa(
            {
                "review_date": "2026-11-14",
                "transfers": {
                    "destinations": ["CA", "CH"],
                    "mechanisms": {"CA": "adequacy", "CH": "adequacy"},
                    "recipient_type": {"CA": "private_commercial", "CH": "public_body"},
                },
            }
        )
        self.assertEqual(
            rule_facts(dpa, "transfer.ca"),
            [
                ("transfers", "destinations", 0),
                ("transfers", "mechanisms", "CA"),
                ("transfers", "recipient_type", "CA"),
                ("review_date",),
            ],
        )
        # Switzerland's decision has no condition, so a recorded recipient_type is not its evidence.
        self.assertNotIn(("transfers", "recipient_type", "CH"), rule_facts(dpa, "transfer.ch"))
        no_decision = _dpa({"review_date": "2026-11-14", "transfers": {"destinations": ["IN"]}})
        self.assertNotIn(("review_date",), rule_facts(no_decision, "transfer.in"))

    def test_the_graph_draws_the_european_patent_organisation_as_an_organisation(self) -> None:
        dpa = _dpa({"transfers": {"destinations": ["EPO"], "mechanisms": {"EPO": "adequacy"}}})
        graph = build_transfer_evidence_graph(dpa, build_packet(dpa))
        node = next(node for node in graph["nodes"] if node["label"] == "EPO")
        self.assertEqual((node["kind"], node["eea"]), ("international_organisation", False))
        edge = next(edge for edge in graph["edges"] if edge["edge_id"] == "processor-direct-to-epo")
        self.assertEqual(edge["status"], "pass")

    def test_the_graph_adds_the_assessment_where_a_decision_did_not_apply(self) -> None:
        dpa = _dpa({"review_date": "2031-12-28", "transfers": {"destinations": ["GB"], "mechanisms": {"GB": "sccs"}}})
        graph = build_transfer_evidence_graph(dpa, build_packet(dpa))
        edge = next(edge for edge in graph["edges"] if edge["edge_id"] == "processor-direct-to-gb")
        self.assertEqual(edge["control_refs"], ["transfer.gb", "transfer.impact_assessment"])

    def test_the_schema_accepts_the_european_patent_organisation_only_as_a_destination(self) -> None:
        schema = json_schema()
        transfers = schema["properties"]["transfers"]["properties"]
        self.assertEqual(transfers["destinations"]["items"]["pattern"], "^([A-Z]{2}|EPO)$")
        self.assertEqual(transfers["recipient_type"]["propertyNames"]["pattern"], "^([A-Z]{2}|EPO)$")
        entry = schema["properties"]["subprocessors"]["items"]["properties"]
        self.assertEqual(entry["country"]["pattern"], "^[A-Z]{2}$")
        self.assertEqual(schema["properties"]["review_date"]["format"], "date")
        sub_processor = _dpa({"subprocessors": [{"name": "Example Office", "country": "EPO"}]})
        self.assertTrue(violations(sub_processor))
        self.assertTrue(violations(_dpa({"transfers": {"destinations": ["epo"]}})))


if __name__ == "__main__":
    unittest.main()
