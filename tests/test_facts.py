"""Findings map back to the input: the facts each rule reads, their evidence and their lines."""

import json
import unittest

from dpa_review.checks import SUBPROCESSOR_TRANSFER_PREFIX, run_all_checks, subprocessor_rule_id
from dpa_review.contract import CONTRACT, violations
from dpa_review.facts import evidence_for, key_lines, line_of, rule_facts
from dpa_review.review import build_packet, render_markdown
from tests.helpers import FIXTURES, ROOT, SAMPLE_PATH, load

SAMPLE = load(SAMPLE_PATH)


class RuleFacts(unittest.TestCase):
    def test_every_rule_reads_facts_the_contract_defines(self):
        fixtures = [load(p) for p in sorted(FIXTURES.glob("*.json")) if p.name != "expected.json"]
        inputs = [SAMPLE] + [dpa for dpa in fixtures if not violations(dpa)]
        seen = set()
        for dpa in inputs:
            for finding in run_all_checks(dpa):
                facts = rule_facts(dpa, finding.rule_id)
                self.assertTrue(facts, f"{finding.rule_id} maps to no input fact")
                for path in facts:
                    spec = CONTRACT[path[0]]
                    if len(path) > 1 and spec.kind == "section":
                        self.assertIn(path[1], spec.fields, finding.rule_id)
                seen.add(finding.rule_id.split(".")[0])
        self.assertEqual(seen, {"processing", "art28", "subprocessor", "breach", "transfer", "ccpa"})

    def test_transfer_rules_point_at_their_destination_and_entry(self):
        self.assertEqual(
            rule_facts(SAMPLE, "transfer.us"),
            [("transfers", "destinations", 1), ("transfers", "mechanisms", "US")],
        )
        self.assertEqual(rule_facts(SAMPLE, "transfer.subprocessor.support_tools_llc"), [("subprocessors", 1)])

    def test_subprocessor_rule_ids_survive_punctuation(self):
        # The rules and the fact mapping derive the id the same way, so the line and the
        # evidence of a punctuated name are still found.
        dpa = load(SAMPLE_PATH)
        dpa["subprocessors"][1]["name"] = "Support Tools, LLC."
        (finding,) = [f for f in run_all_checks(dpa) if f.rule_id.startswith(SUBPROCESSOR_TRANSFER_PREFIX) and "(US)" in f.title]
        self.assertEqual(finding.rule_id, subprocessor_rule_id("Support Tools, LLC."))
        self.assertEqual(rule_facts(dpa, finding.rule_id), [("subprocessors", 1)])


class EvidenceInThePacket(unittest.TestCase):
    def setUp(self):
        self.dpa = load(FIXTURES / "01-eea-only.json")
        self.packet = build_packet(self.dpa)

    def test_evidence_attaches_to_the_findings_that_read_the_fact(self):
        self.assertEqual(set(self.packet.evidence), {"subprocessor.flowdown", "breach.processor_notifies"})
        self.assertEqual(self.packet.evidence["subprocessor.flowdown"][0]["clause"], "§ 7.2")

    def test_section_evidence_covers_the_facts_inside_it(self):
        dpa = load(SAMPLE_PATH)
        dpa["evidence"] = {"subprocessors[1]": {"clause": "Annex 3"}, "transfers": {"clause": "§ 11"}}
        self.assertEqual(evidence_for(dpa, "transfer.subprocessor.support_tools_llc")[0]["fact"], "subprocessors[1]")
        self.assertEqual(evidence_for(dpa, "transfer.us")[0]["clause"], "§ 11")
        self.assertEqual(evidence_for(dpa, "subprocessor.flowdown"), [])

    def test_markdown_shows_the_source_next_to_each_finding(self):
        markdown = render_markdown(self.packet)
        self.assertIn("| Source in the DPA |", markdown)
        self.assertIn('§ 7.2: "The Processor shall impose the same data protection obligations', markdown)
        self.assertIn("Evidence: a clause or quote from the DPA is recorded for 2 of", markdown)
        self.assertIn("| not recorded |", markdown)

    def test_json_findings_carry_evidence_only_when_recorded(self):
        findings = {f["rule_id"]: f for f in self.packet.to_dict()["findings"]}
        self.assertEqual(findings["breach.processor_notifies"]["evidence"][0]["clause"], "§ 9.1")
        self.assertNotIn("evidence", findings["ccpa.service_provider_terms"])

    def test_pipes_in_quotes_cannot_break_the_table(self):
        self.dpa["evidence"]["breach_notification.timing"]["quote"] = "a | b\nc"
        self.assertIn('"a \\| b c"', render_markdown(build_packet(self.dpa)))

    def test_packet_without_evidence_is_unchanged(self):
        committed = (ROOT / "examples" / "review-packet.md").read_text(encoding="utf-8")
        self.assertEqual(render_markdown(build_packet(SAMPLE)), committed)
        self.assertNotIn("evidence", json.dumps(build_packet(SAMPLE).to_dict()["findings"]))


class Lines(unittest.TestCase):
    def test_lines_of_keys_and_list_items(self):
        text = '{\n  "a": {\n    "b": [\n      1,\n      {"c": "x"}\n    ]\n  },\n  "d": []\n}\n'
        lines = key_lines(text)
        self.assertEqual(lines[()], 1)
        self.assertEqual(lines[("a",)], 2)
        self.assertEqual(lines[("a", "b")], 3)
        self.assertEqual(lines[("a", "b", 0)], 4)
        self.assertEqual(lines[("a", "b", 1, "c")], 5)
        self.assertEqual(lines[("d",)], 8)
        self.assertEqual(line_of(lines, ("a", "missing", "deeper")), 2)
        self.assertEqual(line_of(lines, ("nowhere",)), 1)

    def test_lines_in_the_sample(self):
        text = SAMPLE_PATH.read_text(encoding="utf-8")
        lines = key_lines(text)
        numbered = text.splitlines()
        self.assertIn('"subprocessor_flowdown"', numbered[lines[("art28_clauses", "subprocessor_flowdown")] - 1])
        self.assertIn("Support Tools LLC", numbered[lines[("subprocessors", 1)] - 1])


if __name__ == "__main__":
    unittest.main()
