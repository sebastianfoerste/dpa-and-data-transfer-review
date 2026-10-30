import json
import unittest
from pathlib import Path

from dpa_review.review import build_packet
from dpa_review.transfer_graph import (
    build_transfer_evidence_graph,
    render_transfer_evidence_graph,
)
from tests.helpers import FIXTURES, load

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "data" / "sample_dpa.json").read_text(encoding="utf-8"))
EXPECTED = load(FIXTURES / "expected.json")

# The graph status a packet review state allows at best: the graph is never better than the packet.
GRAPH_RANK = {"READY_FOR_LAWYER_REVIEW": 0, "NEEDS_REVIEW": 1, "BLOCKED": 2}
PACKET_RANK = {"CLEARED_FOR_REVIEW": 0, "NEEDS_REVIEW": 1, "BLOCKED": 2}

# Sub-processor names with punctuation or a non-ASCII letter, and the rule id the packet gives the
# transfer check for each. The graph used to derive a different id for them, so it found no finding,
# drew the edge as "pass" and left the open transfer rule out of the remediation queue.
PUNCTUATED_NAMES = {
    "Support Tools, LLC": "transfer.subprocessor.support_tools_llc",
    "Support-Tools LLC": "transfer.subprocessor.support_tools_llc",
    "Example K.K.": "transfer.subprocessor.example_k_k",
    "Müller Support GmbH": "transfer.subprocessor.müller_support_gmbh",
}


def copy(dpa: dict) -> dict:
    return json.loads(json.dumps(dpa))


def renamed_sample(name: str, cured: bool = False) -> dict:
    """The sample with "Support Tools LLC" (US, no transfer mechanism) renamed. Cured, every other
    open finding of the sample is resolved, so the sub-processor transfer is the only one left."""
    dpa = copy(SAMPLE)
    dpa["subprocessors"][1]["name"] = name
    if cured:
        dpa["art28_clauses"]["subprocessor_flowdown"] = True
        dpa["transfers"]["mechanisms"]["US"] = "sccs"
        dpa["transfers"]["transfer_impact_assessment"] = True
    return dpa


def edge(graph: dict, edge_id: str) -> dict:
    return next(item for item in graph["edges"] if item["edge_id"] == edge_id)


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


class GraphNeverBetterThanThePacket(unittest.TestCase):
    """The graph fails closed: an edge whose expected finding is missing goes to review, and the
    graph status is never better than the packet's review state."""

    def test_punctuated_and_non_ascii_names_block_the_transfer_edge(self):
        for name, rule_id in PUNCTUATED_NAMES.items():
            with self.subTest(name=name):
                dpa = renamed_sample(name)
                packet = build_packet(dpa)
                graph = build_transfer_evidence_graph(dpa, packet)
                transfer = next(f for f in packet.findings if f.title.startswith(f"Sub-processor transfer: {name}"))
                self.assertEqual((transfer.rule_id, transfer.status, transfer.severity), (rule_id, "MISSING", "HIGH"))
                location = edge(graph, "subprocessor-2-to-us")
                self.assertEqual((location["status"], location["control_refs"]), ("block", [rule_id]))
                self.assertIn(rule_id, edge(graph, "processor-to-subprocessor-2")["control_refs"])
                queued = {item["control_ref"]: item["affected_edges"] for item in graph["remediation_queue"]}
                self.assertEqual(queued.get(rule_id), ["processor-to-subprocessor-2", "subprocessor-2-to-us"])
                self.assertEqual(graph["graph_status"], "BLOCKED")

    def test_a_punctuated_name_keeps_the_cured_chain_blocked(self):
        # The only open finding is the comma-named sub-processor's US transfer: the packet is
        # BLOCKED, and the graph used to show NEEDS_REVIEW with no blocked edge.
        dpa = renamed_sample("Support Tools, LLC", cured=True)
        packet = build_packet(dpa)
        graph = build_transfer_evidence_graph(dpa, packet)
        self.assertEqual(packet.review_state, "BLOCKED")
        self.assertEqual(graph["graph_status"], "BLOCKED")
        self.assertEqual(graph["summary"]["blocked_edges"], 2)
        self.assertEqual(
            [item["control_ref"] for item in graph["remediation_queue"]],
            ["transfer.subprocessor.support_tools_llc", "transfer.us"],
        )
        markdown = render_transfer_evidence_graph(graph)
        self.assertIn("**Graph status: BLOCKED**", markdown)
        self.assertIn("| subprocessor-2-to-us | block | processes_in |", markdown)

    def test_no_subprocessors_and_no_authorisation_blocks_the_graph(self):
        dpa = load(FIXTURES / "01-eea-only.json")
        dpa["subprocessors"] = []
        dpa["art28_clauses"]["subprocessor_authorization"] = "none"
        del dpa["evidence"]["subprocessors[0]"]
        packet = build_packet(dpa)
        graph = build_transfer_evidence_graph(dpa, packet)
        self.assertEqual(packet.review_state, "BLOCKED")
        self.assertEqual(graph["graph_status"], "BLOCKED")
        self.assertIn("**Graph status: BLOCKED**", render_transfer_evidence_graph(graph))

    def test_ccpa_omitted_puts_the_graph_in_review(self):
        dpa = load(FIXTURES / "01-eea-only.json")
        del dpa["ccpa"]
        packet = build_packet(dpa)
        graph = build_transfer_evidence_graph(dpa, packet)
        self.assertEqual(packet.review_state, "NEEDS_REVIEW")
        self.assertEqual(graph["graph_status"], "NEEDS_REVIEW")

    def test_an_edge_whose_expected_finding_is_absent_goes_to_review(self):
        # Fixture 02 is CLEARED_FOR_REVIEW. Without the findings for its UK sub-processor and its
        # direct transfer to Japan, nothing shows that those links pass.
        dpa = load(FIXTURES / "02-adequacy-only.json")
        packet = build_packet(dpa)
        removed = {"transfer.subprocessor.example_support_ltd", "transfer.jp"}
        self.assertTrue(removed <= {f.rule_id for f in packet.findings})
        packet.findings = [f for f in packet.findings if f.rule_id not in removed]
        graph = build_transfer_evidence_graph(dpa, packet)
        self.assertEqual(edge(graph, "subprocessor-2-to-gb")["status"], "review")
        self.assertEqual(edge(graph, "processor-to-subprocessor-2")["status"], "review")
        self.assertEqual(edge(graph, "processor-direct-to-jp")["status"], "review")
        self.assertEqual(edge(graph, "processor-direct-to-ch")["status"], "pass")
        self.assertEqual(graph["graph_status"], "NEEDS_REVIEW")

    def test_an_eea_location_passes_without_a_transfer_control(self):
        # The packet raises no transfer finding for a sub-processor inside the EEA, so the edge names
        # no transfer rule; it used to name transfer.subprocessor.eu_hosting_sarl, which no finding has.
        graph = build_transfer_evidence_graph(SAMPLE, build_packet(SAMPLE))
        location = edge(graph, "subprocessor-1-to-fr")
        self.assertEqual((location["status"], location["control_refs"], location["citation_refs"]), ("pass", [], []))
        self.assertEqual(
            edge(graph, "processor-to-subprocessor-1")["control_refs"],
            ["subprocessor.authorization", "subprocessor.flowdown"],
        )

    def test_every_fixture(self):
        inputs = {"data/sample_dpa.json": SAMPLE}
        inputs.update({name: load(FIXTURES / name) for name, case in EXPECTED.items() if case["exit_code"] != 3})
        for name, dpa in inputs.items():
            with self.subTest(input=name):
                packet = build_packet(dpa)
                graph = build_transfer_evidence_graph(dpa, packet)
                rule_ids = {finding.rule_id for finding in packet.findings}
                eea = {node["node_id"]: node["eea"] for node in graph["nodes"] if node["kind"] == "jurisdiction"}
                for item in graph["edges"]:
                    self.assertTrue(set(item["control_refs"]) <= rule_ids, item)
                    if eea.get(item["target"]) is False:
                        self.assertTrue(item["control_refs"], item)
                self.assertGreaterEqual(GRAPH_RANK[graph["graph_status"]], PACKET_RANK[packet.review_state])
                self.assertEqual(graph["review_state"], packet.review_state)


if __name__ == "__main__":
    unittest.main()
