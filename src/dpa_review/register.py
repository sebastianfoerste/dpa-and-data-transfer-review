"""Review a register of DPAs: one packet per input, and a summary of the whole register.

A register is a directory of DPA descriptions, e.g. one JSON file per vendor kept in Git. The
summary counts the review states, lists every DPA, ranks the open rules by how many DPAs they
affect, and lists the inputs that break the input contract. Its exit code is the worst one.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from dpa_review.checks import SEVERITY_ORDER
from dpa_review.review import DISCLAIMER, OPEN_STATUSES, ReviewPacket

SCHEMA = "dpa-review.register-summary.v1"
STATES = ("BLOCKED", "NEEDS_REVIEW", "CLEARED_FOR_REVIEW")  # worst first


@dataclass(frozen=True)
class Problem:
    """One reason no review state was decided for an input."""

    message: str
    line: int | None = None  # the input line it concerns; set for input-contract violations

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}" if self.line is not None else self.message


@dataclass
class Review:
    """The outcome for one input: a packet, or the reasons no review state was decided."""

    source: str  # the input path as given on the command line
    text: str = ""  # the input as read, for line numbers
    dpa: dict | None = None  # set once the input parses as a JSON object
    packet: ReviewPacket | None = None
    graph: dict | None = None  # the transfer evidence graph, built with the packet
    errors: list[Problem] = field(default_factory=list)


def worst_state(reviews: list[Review]) -> str | None:
    states = {review.packet.review_state for review in reviews if review.packet}
    return next((state for state in STATES if state in states), None)


def summary(reviews: list[Review], exit_code: int) -> dict[str, Any]:
    reviewed = [review for review in reviews if review.packet]
    counts = Counter(review.packet.review_state for review in reviewed)
    open_rules: dict[str, dict[str, Any]] = {}
    for review in reviewed:
        for finding in review.packet.findings:
            if finding.status not in OPEN_STATUSES:
                continue
            entry = open_rules.setdefault(
                finding.rule_id,
                {
                    "rule_id": finding.rule_id,
                    "severity": finding.severity,
                    "citation": finding.citation,
                    "dpas": [],
                },
            )
            if SEVERITY_ORDER[finding.severity] > SEVERITY_ORDER[entry["severity"]]:
                entry["severity"] = finding.severity
            entry["dpas"].append(review.source)
    ranked = sorted(
        open_rules.values(),
        key=lambda rule: (-len(rule["dpas"]), -SEVERITY_ORDER[rule["severity"]], rule["rule_id"]),
    )
    return {
        "schema": SCHEMA,
        "worst_review_state": worst_state(reviews),
        "exit_code": exit_code,
        "counts": {
            "dpas": len(reviews),
            **{state.lower(): counts.get(state, 0) for state in STATES},
            "invalid_input": len(reviews) - len(reviewed),
        },
        "dpas": [
            {
                "source": review.source,
                "title": review.packet.title,
                "review_state": review.packet.review_state,
                "high_open": review.packet.summary["high_open"],
                "medium_open": review.packet.summary["medium_open"],
                "open_findings": review.packet.summary["missing"] + review.packet.summary["needs_review"],
            }
            for review in reviewed
        ],
        "open_rules": [{**rule, "dpa_count": len(rule["dpas"])} for rule in ranked],
        "invalid_inputs": [
            {"source": review.source, "errors": [str(error) for error in review.errors]}
            for review in reviews
            if not review.packet
        ],
        "disclaimer": DISCLAIMER,
    }


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def render_summary(data: dict[str, Any]) -> str:
    counts = data["counts"]
    worst = data["worst_review_state"] or "none decided"
    lines = [
        "# DPA register review summary",
        "",
        f"**Worst review state: {worst}** (exit code {data['exit_code']})",
        "",
        f"DPAs: {counts['dpas']}, blocked {counts['blocked']}, needs-review {counts['needs_review']}, "
        f"cleared for review {counts['cleared_for_review']}, invalid input {counts['invalid_input']}",
        "",
    ]
    if data["dpas"]:
        lines += [
            "## DPAs",
            "",
            "| Review state | DPA | Input | Open high | Open medium | Open findings |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        ]
        order = {state: index for index, state in enumerate(STATES)}
        for dpa in sorted(data["dpas"], key=lambda item: (order[item["review_state"]], item["source"])):
            lines.append(
                f"| {dpa['review_state']} | {_cell(dpa['title'])} | {_cell(dpa['source'])} "
                f"| {dpa['high_open']} | {dpa['medium_open']} | {dpa['open_findings']} |"
            )
        lines.append("")
    if data["open_rules"]:
        lines += [
            "## Most common open rules",
            "",
            "| Rule | Severity | Citation | DPAs |",
            "| --- | --- | --- | ---: |",
        ]
        for rule in data["open_rules"]:
            lines.append(f"| {rule['rule_id']} | {rule['severity']} | {rule['citation']} | {rule['dpa_count']} |")
        lines.append("")
    if data["invalid_inputs"]:
        lines += [
            "## Inputs that break the input contract",
            "",
            "No review state was decided for these inputs. Fix them and run the review again.",
            "",
            "| Input | Problems |",
            "| --- | --- |",
        ]
        for item in data["invalid_inputs"]:
            lines.append(f"| {_cell(item['source'])} | {'<br>'.join(_cell(error) for error in item['errors'])} |")
        lines.append("")
    lines += ["---", "", f"_{data['disclaimer']}_", ""]
    return "\n".join(lines)
