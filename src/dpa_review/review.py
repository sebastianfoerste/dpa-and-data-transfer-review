"""Builds a review packet and an overall, visible review state from the findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dpa_review.checks import Finding, run_all_checks
from dpa_review.facts import evidence_for

DISCLAIMER = (
    "This is an automated first-pass review packet generated from a checklist of "
    "deterministic rules. It is not legal advice, does not create a lawyer-client "
    "relationship, and must be reviewed by a qualified lawyer before any decision. "
    "All data in the bundled example is synthetic."
)

# An open finding is anything that is not cleanly satisfied.
OPEN_STATUSES = {"MISSING", "NEEDS_REVIEW"}


@dataclass
class ReviewPacket:
    title: str
    review_state: str            # BLOCKED | NEEDS_REVIEW | CLEARED_FOR_REVIEW
    summary: dict[str, int]
    findings: list[Finding]
    # rule_id -> the clauses and quotes the input records for the facts that rule read.
    evidence: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "review_state": self.review_state,
            "summary": self.summary,
            "disclaimer": DISCLAIMER,
            "findings": [self._finding_dict(f) for f in self.findings],
        }

    def _finding_dict(self, finding: Finding) -> dict[str, Any]:
        data = finding.to_dict()
        if finding.rule_id in self.evidence:
            data["evidence"] = self.evidence[finding.rule_id]
        return data


def _summarise(findings: list[Finding]) -> dict[str, int]:
    summary = {
        "total": len(findings),
        "present": 0,
        "missing": 0,
        "needs_review": 0,
        "high_open": 0,
        "medium_open": 0,
    }
    for f in findings:
        if f.status == "PRESENT":
            summary["present"] += 1
        elif f.status == "MISSING":
            summary["missing"] += 1
        elif f.status == "NEEDS_REVIEW":
            summary["needs_review"] += 1
        if f.status in OPEN_STATUSES:
            if f.severity == "HIGH":
                summary["high_open"] += 1
            elif f.severity == "MEDIUM":
                summary["medium_open"] += 1
    return summary


def _decide_state(summary: dict[str, int]) -> str:
    # Any open HIGH finding blocks the packet from leaving review. Any other open finding
    # (MISSING or NEEDS_REVIEW, whatever its severity) needs a lawyer's judgement, as
    # docs/rules.md promises; only a packet with no open finding is cleared for review.
    if summary["high_open"] > 0:
        return "BLOCKED"
    if summary["missing"] + summary["needs_review"] > 0:
        return "NEEDS_REVIEW"
    return "CLEARED_FOR_REVIEW"


def build_packet(dpa: dict) -> ReviewPacket:
    findings = run_all_checks(dpa)
    # Deterministic ordering: open items first, by severity, then rule id.
    findings.sort(
        key=lambda f: (
            0 if f.status in OPEN_STATUSES else 1,
            -{"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}[f.severity],
            f.rule_id,
        )
    )
    summary = _summarise(findings)
    state = _decide_state(summary)
    title = dpa.get("agreement", "Data Processing Agreement") + " review packet"
    evidence = {f.rule_id: found for f in findings if (found := evidence_for(dpa, f.rule_id))}
    return ReviewPacket(title=title, review_state=state, summary=summary, findings=findings, evidence=evidence)


_STATE_BANNER = {
    "BLOCKED": "BLOCKED: open high-severity findings must be resolved before this DPA can be relied on.",
    "NEEDS_REVIEW": "NEEDS REVIEW: open items require a lawyer's judgement.",
    "CLEARED_FOR_REVIEW": "CLEARED FOR REVIEW: no open findings; lawyer sign-off still required.",
}

_STATUS_MARK = {"PRESENT": "[ok]", "MISSING": "[missing]", "NEEDS_REVIEW": "[review]"}


def _cell(text: str) -> str:
    """Input text made safe for one Markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def _source(packet: ReviewPacket, finding: Finding) -> str:
    """The recorded clause and quote for a finding, as one table cell."""
    parts = []
    for item in packet.evidence.get(finding.rule_id, []):
        clause, quote = item.get("clause"), item.get("quote")
        text = f'{clause}: "{quote}"' if clause and quote else clause or f'"{quote}"'
        parts.append(_cell(text))
    return "<br>".join(parts) or "not recorded"


def render_markdown(packet: ReviewPacket) -> str:
    s = packet.summary
    lines: list[str] = []
    lines.append(f"# {packet.title}")
    lines.append("")
    lines.append(f"**Review state: {packet.review_state}**")
    lines.append("")
    lines.append(f"> {_STATE_BANNER[packet.review_state]}")
    lines.append("")
    lines.append(
        f"Checks: {s['total']}, present {s['present']}, "
        f"missing {s['missing']}, needs-review {s['needs_review']}, "
        f"open high {s['high_open']}, open medium {s['medium_open']}"
    )
    # The source column appears only when the input records evidence (clause and quote).
    sourced = bool(packet.evidence)
    if sourced:
        lines.append("")
        lines.append(
            f"Evidence: a clause or quote from the DPA is recorded for {len(packet.evidence)} of "
            f"{s['total']} checks."
        )
    lines.append("")

    open_findings = [f for f in packet.findings if f.status in OPEN_STATUSES]
    if open_findings:
        lines.append("## Open findings")
        lines.append("")
        lines.append("| Severity | Status | Finding | Citation | Remediation |" + (" Source in the DPA |" if sourced else ""))
        lines.append("| --- | --- | --- | --- | --- |" + (" --- |" if sourced else ""))
        for f in open_findings:
            lines.append(
                f"| {f.severity} | {_STATUS_MARK[f.status]} | {f.title} | {f.citation} | {f.remediation or 'n/a'} |"
                + (f" {_source(packet, f)} |" if sourced else "")
            )
        lines.append("")

    lines.append("## Full checklist")
    lines.append("")
    lines.append("| Severity | Status | Finding | Citation |" + (" Source in the DPA |" if sourced else ""))
    lines.append("| --- | --- | --- | --- |" + (" --- |" if sourced else ""))
    for f in packet.findings:
        lines.append(
            f"| {f.severity} | {_STATUS_MARK[f.status]} | {f.title} | {f.citation} |"
            + (f" {_source(packet, f)} |" if sourced else "")
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_{DISCLAIMER}_")
    lines.append("")
    return "\n".join(lines)
