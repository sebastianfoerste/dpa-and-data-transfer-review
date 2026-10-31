import json
import unittest

from dpa_review.checks import SUBPROCESSOR_TRANSFER_PREFIX
from dpa_review.contract import violations
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
