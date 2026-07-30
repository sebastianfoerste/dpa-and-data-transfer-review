import json
import unittest
from pathlib import Path

from dpa_review.review import build_packet
from dpa_review.transfer_graph import (
    build_transfer_evidence_graph,
    render_transfer_evidence_graph,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "data" / "sample_dpa.json").read_text(encoding="utf-8"))


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
