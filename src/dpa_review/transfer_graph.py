"""Reviewer-facing evidence graph for processor and international-transfer chains."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from dpa_review.checks import EEA, subprocessor_rule_id
from dpa_review.review import OPEN_STATUSES, ReviewPacket, markdown_text, one_line

SCHEMA = "dpa-review.transfer-evidence-graph.v1"

# The graph status each packet review state allows at best, and the order of the graph statuses.
_GRAPH_STATUS_FOR_PACKET = {
    "BLOCKED": "BLOCKED",
    "NEEDS_REVIEW": "NEEDS_REVIEW",
    "CLEARED_FOR_REVIEW": "READY_FOR_LAWYER_REVIEW",
}
_GRAPH_STATUS_RANK = {"READY_FOR_LAWYER_REVIEW": 0, "NEEDS_REVIEW": 1, "BLOCKED": 2}


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _node_id(kind: str, label: str) -> str:
    return f"{kind}:{hashlib.sha256(label.encode('utf-8')).hexdigest()[:12]}"


def _finding(packet: ReviewPacket, rule_id: str):
    return next((finding for finding in packet.findings if finding.rule_id == rule_id), None)


def _edge_status(packet: ReviewPacket, control_refs: list[str]) -> str:
    """The status of an edge from the packet findings its controls name.

    A control the packet has no finding for is no evidence that the link passes, so the edge goes
    to review: the graph fails closed when its rule ids and the packet's ever drift apart.
    """
    findings = [_finding(packet, rule_id) for rule_id in control_refs]
    open_findings = [finding for finding in findings if finding is not None and finding.status in OPEN_STATUSES]
    if any(finding.severity == "HIGH" for finding in open_findings):
        return "block"
    if open_findings or any(finding is None for finding in findings):
        return "review"
    return "pass"


def _citations(packet: ReviewPacket, control_refs: list[str]) -> list[str]:
    return sorted(
        {finding.citation for rule_id in control_refs if (finding := _finding(packet, rule_id)) is not None}
    )


def build_transfer_evidence_graph(
    dpa: dict[str, Any],
    packet: ReviewPacket,
) -> dict[str, Any]:
    """Build a graph that exposes the weakest contractual or transfer-control link."""

    controller = str(dpa.get("controller", "Controller"))
    processor = str(dpa.get("processor", "Processor"))
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(kind: str, label: str, **details: Any) -> str:
        node_id = _node_id(kind, label)
        nodes[node_id] = {
            "node_id": node_id,
            "kind": kind,
            "label": label,
            **details,
        }
        return node_id

    controller_id = add_node("party", controller, role="controller")
    processor_id = add_node("party", processor, role="processor")

    art28_controls = sorted(
        finding.rule_id
        for finding in packet.findings
        if finding.rule_id.startswith(("processing.", "art28.", "breach."))
    )
    edges.append(
        {
            "edge_id": "controller-to-processor",
            "source": controller_id,
            "target": processor_id,
            "relationship": "appoints_processor",
            "status": _edge_status(packet, art28_controls),
            "control_refs": art28_controls,
            "citation_refs": _citations(packet, art28_controls),
        }
    )

    # Each edge names the controls the packet decides it by. checks.check_transfers raises the
    # transfer impact assessment finding whenever a recorded mechanism is SCCs or BCR.
    transfer_impact = "transfer.impact_assessment"
    represented_destinations: set[str] = set()
    for index, subprocessor in enumerate(dpa.get("subprocessors", []) or []):
        name = str(subprocessor.get("name", f"Sub-processor {index + 1}"))
        country = str(subprocessor.get("country", "")).upper()
        represented_destinations.add(country)
        subprocessor_id = add_node(
            "party",
            name,
            role="subprocessor",
            purpose=str(subprocessor.get("purpose", "")),
        )
        # A sub-processor outside the EEA is a transfer, which the packet checks under this id. One
        # inside the EEA is not, so the packet raises no transfer finding for it and its edges name
        # no transfer control.
        transfer_controls = (
            [subprocessor_rule_id(subprocessor.get("name", "unknown"))] if country not in EEA else []
        )
        appointment_controls = ["subprocessor.authorization", "subprocessor.flowdown", *transfer_controls]
        edges.append(
            {
                "edge_id": f"processor-to-subprocessor-{index + 1}",
                "source": processor_id,
                "target": subprocessor_id,
                "relationship": "appoints_subprocessor",
                "status": _edge_status(packet, appointment_controls),
                "control_refs": appointment_controls,
                "citation_refs": _citations(packet, appointment_controls),
            }
        )
        if country:
            mechanism = str(
                subprocessor.get("transfer_mechanism", "none")
            ).lower()
            location_controls = list(transfer_controls)
            if transfer_controls and mechanism in {"sccs", "bcr"}:
                location_controls.append(transfer_impact)
            jurisdiction_id = add_node(
                "jurisdiction",
                country,
                eea=country in EEA,
            )
            edges.append(
                {
                    "edge_id": f"subprocessor-{index + 1}-to-{country.lower()}",
                    "source": subprocessor_id,
                    "target": jurisdiction_id,
                    "relationship": "processes_in",
                    "status": _edge_status(packet, location_controls),
                    "control_refs": location_controls,
                    "citation_refs": _citations(packet, location_controls),
                    "mechanism": mechanism,
                }
            )

    mechanisms = dpa.get("transfers", {}).get("mechanisms", {}) or {}
    for country_value in dpa.get("transfers", {}).get("destinations", []) or []:
        country = str(country_value).upper()
        jurisdiction_id = add_node("jurisdiction", country, eea=country in EEA)
        mechanism = str(mechanisms.get(country, "none")).lower()
        direct_controls = [f"transfer.{country.lower()}"]
        if mechanism in {"sccs", "bcr"}:
            direct_controls.append(transfer_impact)
        edges.append(
            {
                "edge_id": f"processor-direct-to-{country.lower()}",
                "source": processor_id,
                "target": jurisdiction_id,
                "relationship": "direct_transfer_to",
                "status": _edge_status(packet, direct_controls),
                "control_refs": direct_controls,
                "citation_refs": _citations(packet, direct_controls),
                "mechanism": mechanism,
                "also_used_by_subprocessor": country in represented_destinations,
            }
        )

    ordered_nodes = sorted(nodes.values(), key=lambda node: node["node_id"])
    ordered_edges = sorted(edges, key=lambda edge: edge["edge_id"])
    weakest_links = [
        {
            "edge_id": edge["edge_id"],
            "status": edge["status"],
            "relationship": edge["relationship"],
            "control_refs": edge["control_refs"],
        }
        for edge in ordered_edges
        if edge["status"] != "pass"
    ]
    affected_edges_by_control: dict[str, list[str]] = {}
    for edge in ordered_edges:
        for control_ref in edge["control_refs"]:
            affected_edges_by_control.setdefault(control_ref, []).append(edge["edge_id"])
    reviewer_roles = {
        "transfer": "Privacy Counsel",
        "subprocessor": "Privacy Counsel",
        "art28": "Commercial Counsel",
        "processing": "Commercial Counsel",
        "breach": "Privacy Counsel",
    }
    remediation_queue = []
    for finding in packet.findings:
        affected_edges = sorted(affected_edges_by_control.get(finding.rule_id, []))
        if finding.status not in OPEN_STATUSES or not affected_edges:
            continue
        prefix = finding.rule_id.split(".", 1)[0]
        remediation_queue.append(
            {
                "control_ref": finding.rule_id,
                "severity": finding.severity,
                "status": finding.status,
                "citation": finding.citation,
                "affected_edges": affected_edges,
                "reviewer_role": reviewer_roles.get(prefix, "Qualified Lawyer"),
                "required_evidence": finding.remediation or finding.detail,
                "decision_state": "open",
            }
        )
    remediation_queue.sort(
        key=lambda item: (
            -{"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}[item["severity"]],
            item["control_ref"],
        )
    )
    edge_status = (
        "BLOCKED"
        if any(edge["status"] == "block" for edge in ordered_edges)
        else "NEEDS_REVIEW"
        if any(edge["status"] == "review" for edge in ordered_edges)
        else "READY_FOR_LAWYER_REVIEW"
    )
    # Never better than the packet: an open finding no edge carries, such as the sub-processor
    # authorisation of a DPA that names no sub-processor, still holds the graph at the packet's state.
    status = max(
        edge_status,
        _GRAPH_STATUS_FOR_PACKET.get(packet.review_state, "BLOCKED"),
        key=_GRAPH_STATUS_RANK.__getitem__,
    )
    payload = {
        "schema": SCHEMA,
        "review_state": packet.review_state,
        "graph_status": status,
        "summary": {
            "nodes": len(ordered_nodes),
            "edges": len(ordered_edges),
            "blocked_edges": sum(edge["status"] == "block" for edge in ordered_edges),
            "review_edges": sum(edge["status"] == "review" for edge in ordered_edges),
            "pass_edges": sum(edge["status"] == "pass" for edge in ordered_edges),
            "open_remediation_items": len(remediation_queue),
        },
        "nodes": ordered_nodes,
        "edges": ordered_edges,
        "weakest_links": weakest_links,
        "remediation_queue": remediation_queue,
        "source_dpa_sha256": _canonical_sha256(dpa),
        "review_gate": (
            "The graph is a deterministic reviewer aid. It does not validate a "
            "transfer mechanism, approve a sub-processor, or execute a transfer."
        ),
        "external_actions_allowed": False,
    }
    return {**payload, "graph_sha256": _canonical_sha256(payload)}


def _mermaid_label(value: str) -> str:
    """A node label inside a quoted Mermaid string: one line, so it cannot add a node, an edge or
    a closing fence; no backticks, which would start a Markdown string; quotes and angle brackets
    as Mermaid entity codes."""
    text = one_line(str(value).replace("`", ""))
    return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def render_transfer_evidence_graph(graph: dict[str, Any]) -> str:
    lines = [
        "# DPA Transfer Chain Evidence Graph",
        "",
        f"**Graph status: {graph['graph_status']}**",
        "",
        f"- Review packet state: `{graph['review_state']}`",
        f"- Blocked edges: {graph['summary']['blocked_edges']}",
        f"- Review edges: {graph['summary']['review_edges']}",
        f"- Graph SHA-256: `{graph['graph_sha256']}`",
        "- External actions: disabled",
        "",
        "## Transfer chain",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    mermaid_ids = {
        node["node_id"]: f"N{index}"
        for index, node in enumerate(graph["nodes"], start=1)
    }
    for node in graph["nodes"]:
        lines.append(
            f'  {mermaid_ids[node["node_id"]]}["{_mermaid_label(node["label"])}"]'
        )
    for edge in graph["edges"]:
        lines.append(
            f'  {mermaid_ids[edge["source"]]} -->|"{edge["relationship"]}: '
            f'{edge["status"]}"| {mermaid_ids[edge["target"]]}'
        )
    lines.extend(
        [
            "```",
            "",
            "## Weakest links",
            "",
            "| Edge | Status | Relationship | Controls |",
            "| --- | --- | --- | --- |",
        ]
    )
    for link in graph["weakest_links"]:
        lines.append(
            f"| {link['edge_id']} | {link['status']} | {link['relationship']} "
            f"| {', '.join(markdown_text(ref) for ref in link['control_refs'])} |"
        )
    if not graph["weakest_links"]:
        lines.append("| none | pass | n/a | n/a |")
    lines.extend(
        [
            "",
            "## Control remediation queue",
            "",
            "| Control | Severity | Affected edges | Reviewer | Required evidence |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for item in graph["remediation_queue"]:
        lines.append(
            f"| {markdown_text(item['control_ref'])} | {item['severity']} "
            f"| {len(item['affected_edges'])} | {item['reviewer_role']} "
            f"| {markdown_text(item['required_evidence'])} |"
        )
    if not graph["remediation_queue"]:
        lines.append("| none | n/a | 0 | n/a | none |")
    lines.extend(["", "## Review gate", "", graph["review_gate"], ""])
    return "\n".join(lines)
