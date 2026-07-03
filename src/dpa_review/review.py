"""Builds a review packet and an overall, visible review state from the findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dpa_review.checks import Finding, run_all_checks

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "review_state": self.review_state,
            "summary": self.summary,
            "disclaimer": DISCLAIMER,
            "findings": [f.to_dict() for f in self.findings],
        }


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
    # Any open HIGH finding blocks the packet from leaving review.
    if summary["high_open"] > 0:
        return "BLOCKED"
    if summary["medium_open"] > 0 or summary["needs_review"] > 0:
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
    return ReviewPacket(title=title, review_state=state, summary=summary, findings=findings)


_STATE_BANNER = {
    "BLOCKED": "BLOCKED: open high-severity findings must be resolved before this DPA can be relied on.",
    "NEEDS_REVIEW": "NEEDS REVIEW: open items require a lawyer's judgement.",
    "CLEARED_FOR_REVIEW": "CLEARED FOR REVIEW: no open high or medium findings; lawyer sign-off still required.",
}

_STATUS_MARK = {"PRESENT": "[ok]", "MISSING": "[missing]", "NEEDS_REVIEW": "[review]"}


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
    lines.append("")

    open_findings = [f for f in packet.findings if f.status in OPEN_STATUSES]
    if open_findings:
        lines.append("## Open findings")
        lines.append("")
        lines.append("| Severity | Status | Finding | Citation | Remediation |")
        lines.append("| --- | --- | --- | --- | --- |")
        for f in open_findings:
            lines.append(
                f"| {f.severity} | {_STATUS_MARK[f.status]} | {f.title} | {f.citation} | {f.remediation or 'n/a'} |"
            )
        lines.append("")

    lines.append("## Full checklist")
    lines.append("")
    lines.append("| Severity | Status | Finding | Citation |")
    lines.append("| --- | --- | --- | --- |")
    for f in packet.findings:
        lines.append(f"| {f.severity} | {_STATUS_MARK[f.status]} | {f.title} | {f.citation} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_{DISCLAIMER}_")
    lines.append("")
    return "\n".join(lines)
