"""SARIF 2.1.0 output, so GitHub code scanning (or any SARIF viewer) can show open findings
as alerts on the line of the DPA description that decided them.

Only open findings (MISSING or NEEDS_REVIEW) become results. HIGH maps to the SARIF level
"error", MEDIUM to "warning", LOW and INFO to "note". An input for which no review state was
decided (unreadable, or breaking the input contract) yields one "error" result per problem
under the rule input.invalid, so it cannot drop out of a code-scanning upload unnoticed.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePath
from typing import Any

from dpa_review.facts import key_lines, line_of, rule_facts
from dpa_review.register import Review
from dpa_review.review import OPEN_STATUSES

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/sebastianfoerste/dpa-and-data-transfer-review"
LEVELS = {"HIGH": "error", "MEDIUM": "warning", "LOW": "note", "INFO": "note"}
INPUT_RULE_ID = "input.invalid"
_INPUT_RULE = {
    "id": INPUT_RULE_ID,
    "name": INPUT_RULE_ID,
    "shortDescription": {
        "text": "The input cannot be read or breaks the input contract, so no review state was decided"
    },
    "helpUri": f"{INFORMATION_URI}/blob/main/docs/input-format.md",
    "defaultConfiguration": {"level": "error"},
}


def _uri(source: str) -> str:
    return PurePath(source).as_posix()


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _result(rule_id: str, level: str, message: str, uri: str, line: int, fingerprint: str) -> dict[str, Any]:
    return {
        "ruleId": rule_id,
        "level": level,
        "message": {"text": message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": uri},
                    "region": {"startLine": line},
                }
            }
        ],
        "partialFingerprints": {"dpaReviewFinding/v1": fingerprint},
    }


def sarif_log(reviews: list[Review], version: str) -> dict[str, Any]:
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for review in reviews:
        uri = _uri(review.source)
        if not review.packet:
            rules[INPUT_RULE_ID] = _INPUT_RULE
            for problem in review.errors:
                result = _result(
                    INPUT_RULE_ID,
                    "error",
                    f"{problem.message} No review state was decided for this input.",
                    uri,
                    problem.line or 1,
                    _fingerprint(uri, INPUT_RULE_ID, problem.message),
                )
                results.append(result)
            continue
        lines = key_lines(review.text) if review.text else {}
        for finding in review.packet.findings:
            if finding.status not in OPEN_STATUSES:
                continue
            if finding.rule_id not in rules:
                rules[finding.rule_id] = {
                    "id": finding.rule_id,
                    "name": finding.rule_id,
                    "shortDescription": {"text": finding.title},
                    "helpUri": f"{INFORMATION_URI}/blob/main/docs/rules.md",
                    "properties": {"citation": finding.citation},
                }
            facts = rule_facts(review.dpa or {}, finding.rule_id)
            line = line_of(lines, facts[0]) if facts and lines else 1
            message = f"{finding.title} [{finding.status}, {finding.severity}]: {finding.detail}"
            if finding.remediation:
                message += f" Remediation: {finding.remediation}"
            message += f" Citation: {finding.citation}."
            result = _result(
                finding.rule_id,
                LEVELS[finding.severity],
                message,
                uri,
                line,
                _fingerprint(uri, finding.rule_id),
            )
            result["properties"] = {
                "severity": finding.severity,
                "status": finding.status,
                "citation": finding.citation,
                "review_state": review.packet.review_state,
            }
            results.append(result)
    ordered_rules = [rules[rule_id] for rule_id in sorted(rules)]
    index = {rule["id"]: position for position, rule in enumerate(ordered_rules)}
    for result in results:
        result["ruleIndex"] = index[result["ruleId"]]
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "dpa-review",
                        "version": version,
                        "informationUri": INFORMATION_URI,
                        "rules": ordered_rules,
                    }
                },
                "results": results,
            }
        ],
    }
