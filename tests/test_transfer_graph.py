import json
import unittest

from dpa_review import checks, contract, facts, transfer_graph
from dpa_review.checks import SUBPROCESSOR_TRANSFER_PREFIX, subprocessor_rule_id
from dpa_review.contract import violations
from dpa_review.facts import rule_facts
from dpa_review.review import OPEN_STATUSES, build_packet
from dpa_review.transfer_graph import (
    build_transfer_evidence_graph,
    render_transfer_evidence_graph,
)
from tests.helpers import FIXTURES, SAMPLE_PATH, load

SAMPLE = load(SAMPLE_PATH)


class TransferEvidenceGraphTests(unittest.TestCase):
    def test_graph_surfaces_the_seeded_us_weakest_links(self):
        graph = build_transfer_evidence_graph(SAMPLE, build_packet(SAMPLE))

        self.assertEqual(graph["schema"], "dpa-review.transfer-evidence-graph.v1")
        self.assertEqual(graph["graph_status"], "BLOCKED")
        self.assertGreater(graph["summary"]["blocked_edges"], 0)
        self.assertTrue(
            any(
                "transfer.us" in link["control_refs"]
                for link in graph["weakest_links"]
            )
        )
        self.assertFalse(graph["external_actions_allowed"])
        self.assertEqual(len(graph["graph_sha256"]), 64)
        self.assertEqual(graph["summary"]["open_remediation_items"], 3)
        self.assertEqual(
            {item["control_ref"] for item in graph["remediation_queue"]},
            {
                "subprocessor.flowdown",
                "transfer.subprocessor.support_tools_llc",
                "transfer.us",
            },
        )
        self.assertTrue(
            all(item["affected_edges"] for item in graph["remediation_queue"])
        )

    def test_cured_transfer_chain_removes_blocked_edges(self):
        cured = json.loads(json.dumps(SAMPLE))
        cured["art28_clauses"]["subprocessor_flowdown"] = True
        cured["transfers"]["mechanisms"]["US"] = "sccs"
        cured["transfers"]["transfer_impact_assessment"] = True
        cured["subprocessors"][1]["transfer_mechanism"] = "sccs"

        graph = build_transfer_evidence_graph(cured, build_packet(cured))

        self.assertEqual(graph["summary"]["blocked_edges"], 0)
        self.assertEqual(graph["graph_status"], "NEEDS_REVIEW")

    def test_graph_reads_mechanisms_keyed_in_any_case(self):
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["transfers"]["mechanisms"] = {"fr": "none", "us": "sccs", "jp": "adequacy"}
        graph = build_transfer_evidence_graph(dpa, build_packet(dpa))
        edge = next(e for e in graph["edges"] if e["edge_id"] == "processor-direct-to-us")
        self.assertEqual(edge["mechanism"], "sccs")
        self.assertIn("transfer.impact_assessment", edge["control_refs"])

    def test_graph_finds_the_transfer_finding_of_a_name_with_punctuation(self):
        # The packet and the graph used to derive different rule ids from "Support Tools, LLC",
        # so the graph showed the blocked US sub-processor transfer as a passing edge.
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["subprocessors"][1]["name"] = "Support Tools, LLC"
        packet = build_packet(dpa)
        graph = build_transfer_evidence_graph(dpa, packet)
        edge = next(e for e in graph["edges"] if e["edge_id"] == "subprocessor-2-to-us")
        self.assertEqual(edge["status"], "block")
        self.assertIn(edge["control_refs"][0], {f.rule_id for f in packet.findings})

    def test_each_sub_processor_edge_carries_its_own_status(self):
        # Names that differ only in a non-ASCII letter used to share a rule id, so the edge of the
        # sub-processor on SCCs was reported as blocked with the other one's MISSING finding.
        for first, second in (("Müller Inc", "Möller Inc"), ("百度", "腾讯")):
            with self.subTest(names=(first, second)):
                dpa = json.loads(json.dumps(SAMPLE))
                dpa["transfers"]["transfer_impact_assessment"] = True
                dpa["subprocessors"] = [
                    {"name": first, "country": "CN", "transfer_mechanism": "sccs"},
                    {"name": second, "country": "CN"},
                ]
                packet = build_packet(dpa)
                graph = build_transfer_evidence_graph(dpa, packet)
                edges = {e["edge_id"]: e for e in graph["edges"]}
                on_sccs, without_basis = edges["subprocessor-1-to-cn"], edges["subprocessor-2-to-cn"]
                self.assertEqual(on_sccs["status"], "review")
                self.assertEqual(without_basis["status"], "block")
                self.assertNotEqual(on_sccs["control_refs"][0], without_basis["control_refs"][0])
                statuses = {f.rule_id: f.status for f in packet.findings}
                self.assertEqual(statuses[on_sccs["control_refs"][0]], "NEEDS_REVIEW")
                self.assertEqual(statuses[without_basis["control_refs"][0]], "MISSING")

    def test_rules_facts_and_graph_share_one_rule_id_that_keeps_names_outside_ascii_distinct(self):
        # checks.subprocessor_rule_id is the one derivation, and it keeps letters of every script.
        # The contract, the fact mapping and the graph import that function, and for names that
        # differ only outside ASCII the rules emit distinct, non-empty ids, which the fact mapping
        # and the graph resolve to the matching entry. The identity check shows only that the
        # modules import the helper; the punctuated pair is what fails when one of them derives
        # the id its own way (without punctuation, the old derivations give the same ids).
        for module in (contract, facts, transfer_graph):
            with self.subTest(module=module.__name__):
                self.assertIs(module.subprocessor_rule_id, checks.subprocessor_rule_id)
        for names in (
            ("Müller Inc", "Möller Inc"),
            ("Müller, Inc.", "Möller Inc"),
            ("百度", "腾讯"),
            ("Альфа Сервис", "Бета Сервис"),
        ):
            with self.subTest(names=names):
                dpa = json.loads(json.dumps(SAMPLE))
                dpa["subprocessors"] = [
                    {"name": names[0], "country": "CN", "transfer_mechanism": "sccs"},
                    {"name": names[1], "country": "CN"},
                ]
                self.assertEqual(violations(dpa), [])
                expected = [subprocessor_rule_id(name) for name in names]
                self.assertNotEqual(expected[0], expected[1])
                self.assertNotIn(SUBPROCESSOR_TRANSFER_PREFIX, expected)
                packet = build_packet(dpa)
                emitted = sorted(f.rule_id for f in packet.findings if f.rule_id.startswith(SUBPROCESSOR_TRANSFER_PREFIX))
                self.assertEqual(emitted, sorted(expected))
                edges = {edge["edge_id"]: edge for edge in build_transfer_evidence_graph(dpa, packet)["edges"]}
                for index, rule_id in enumerate(expected):
                    self.assertEqual(rule_facts(dpa, rule_id), [("subprocessors", index)])
                    self.assertEqual(edges[f"subprocessor-{index + 1}-to-cn"]["control_refs"][0], rule_id)
                    self.assertIn(rule_id, edges[f"processor-to-subprocessor-{index + 1}"]["control_refs"])

    def test_assessment_attaches_only_to_transfers_outside_the_eea(self):
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["transfers"]["mechanisms"]["FR"] = "sccs"
        dpa["transfers"]["mechanisms"]["US"] = "sccs"
        dpa["subprocessors"][0]["transfer_mechanism"] = "sccs"
        graph = build_transfer_evidence_graph(dpa, build_packet(dpa))
        controls = {edge["edge_id"]: edge["control_refs"] for edge in graph["edges"]}
        self.assertIn("transfer.impact_assessment", controls["processor-direct-to-us"])
        self.assertNotIn("transfer.impact_assessment", controls["processor-direct-to-fr"])
        self.assertNotIn("transfer.impact_assessment", controls["subprocessor-1-to-fr"])

    def test_null_subprocessor_country_adds_no_jurisdiction(self):
        # The packet reads a null country as no country; the graph used to add a node "NONE".
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["subprocessors"][1]["country"] = None
        graph = build_transfer_evidence_graph(dpa, build_packet(dpa))
        self.assertNotIn("NONE", {node["label"] for node in graph["nodes"]})
        self.assertNotIn("subprocessor-2-to-none", {edge["edge_id"] for edge in graph["edges"]})

    def test_null_values_read_as_omitted(self):
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["controller"] = None
        dpa["subprocessors"][0]["purpose"] = None
        dpa["subprocessors"][1]["transfer_mechanism"] = None
        graph = build_transfer_evidence_graph(dpa, build_packet(dpa))
        labels = {node["label"] for node in graph["nodes"]}
        self.assertIn("Controller", labels)
        self.assertNotIn("None", labels)
        hosting = next(node for node in graph["nodes"] if node["label"] == "EU Hosting SARL")
        self.assertEqual(hosting["purpose"], "")
        edge = next(e for e in graph["edges"] if e["edge_id"] == "subprocessor-2-to-us")
        self.assertEqual(edge["mechanism"], "none")

    def test_null_transfers_section_builds_a_graph(self):
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["transfers"] = None
        graph = build_transfer_evidence_graph(dpa, build_packet(dpa))
        self.assertFalse(
            any(e["relationship"] == "direct_transfer_to" for e in graph["edges"])
        )

    def test_punctuated_subprocessor_name_keeps_the_transfer_finding(self):
        # The graph must look up the rule id the rules emit, whatever the name contains. It used
        # to derive its own, so "Support Tools, LLC." lost its finding and the US edge passed.
        dpa = json.loads(json.dumps(SAMPLE))
        dpa["subprocessors"][1]["name"] = "Support Tools, LLC."
        packet = build_packet(dpa)
        (finding,) = [f for f in packet.findings if f.rule_id.startswith(SUBPROCESSOR_TRANSFER_PREFIX) and "(US)" in f.title]
        self.assertEqual((finding.status, finding.severity), ("MISSING", "HIGH"))

        graph = build_transfer_evidence_graph(dpa, packet)
        edges = {edge["edge_id"]: edge for edge in graph["edges"]}
        self.assertEqual(edges["subprocessor-2-to-us"]["status"], "block")
        self.assertEqual(edges["subprocessor-2-to-us"]["control_refs"], [finding.rule_id])
        self.assertEqual(edges["processor-to-subprocessor-2"]["status"], "block")
        self.assertIn(finding.rule_id, edges["processor-to-subprocessor-2"]["control_refs"])
        self.assertIn(finding.rule_id, {item["control_ref"] for item in graph["remediation_queue"]})
        self.assertEqual(graph["graph_status"], "BLOCKED")

    def test_every_subprocessor_finding_reaches_the_graph(self):
        # Across the sample and every conforming fixture, each sub-processor transfer finding
        # controls at least one edge, and each open one is queued for remediation.
        fixtures = [load(path) for path in sorted(FIXTURES.glob("*.json")) if path.name != "expected.json"]
        for dpa in [SAMPLE, *fixtures]:
            if violations(dpa):
                continue
            packet = build_packet(dpa)
            graph = build_transfer_evidence_graph(dpa, packet)
            controlled = {ref for edge in graph["edges"] for ref in edge["control_refs"]}
            queued = {item["control_ref"] for item in graph["remediation_queue"]}
            for finding in packet.findings:
                if not finding.rule_id.startswith(SUBPROCESSOR_TRANSFER_PREFIX):
                    continue
                with self.subTest(agreement=dpa.get("agreement"), rule=finding.rule_id):
                    self.assertIn(finding.rule_id, controlled)
                    if finding.status in OPEN_STATUSES:
                        self.assertIn(finding.rule_id, queued)

    def test_graph_is_deterministic_and_renders_mermaid(self):
        first = build_transfer_evidence_graph(SAMPLE, build_packet(SAMPLE))
        second = build_transfer_evidence_graph(SAMPLE, build_packet(SAMPLE))

        self.assertEqual(first, second)
        markdown = render_transfer_evidence_graph(first)
        self.assertIn("```mermaid", markdown)
        self.assertIn("Weakest links", markdown)
        self.assertIn("Control remediation queue", markdown)
        self.assertIn("External actions: disabled", markdown)


if __name__ == "__main__":
    unittest.main()
