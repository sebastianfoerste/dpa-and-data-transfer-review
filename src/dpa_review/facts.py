"""Where each finding comes from in the input: the facts a rule reads, the evidence the input
records for them, and the line each fact is on.

The rules in checks.py read facts by key. This module maps a finding back to those keys, so
the packet can print the clause and quote recorded under `evidence` next to the finding, and
SARIF output can point at the line of the JSON file that decided it. tests/test_facts.py
checks that every rule maps to at least one fact the input contract defines.
"""

from __future__ import annotations

import bisect
import json
import re
from typing import Any

from dpa_review.checks import subprocessor_rule_id
from dpa_review.contract import KeyPath, format_path, parse_fact_path

_ART28_FLAGS = "art28."
_SUBPROCESSOR_TRANSFER = "transfer.subprocessor."
# Facts a transfer rule reads per destination, keyed by country under `transfers`: the mechanism,
# and the facts that only the named mechanism reads.
_PER_COUNTRY = (
    ("mechanisms", None),
    ("dpf_certified", "dpf"),
    ("dpf_covers_hr_data", "dpf"),
    ("dpf_covers_non_hr_data", "dpf"),
    ("occasional_and_not_repetitive", "derogation_art49"),
)
# Whether each type of data is transferred: read for a dpf transfer, whose certification must cover it.
_DATA_TRANSFERRED = (("processing", "includes_hr_data"), ("processing", "includes_non_hr_data"))


def _subprocessor_rule_id(entry: dict, index: int) -> str:
    # The same name and derivation checks.check_transfers uses for transfer.subprocessor.<name>.
    name = entry.get("name")
    return subprocessor_rule_id(name if isinstance(name, str) and name else f"Sub-processor {index + 1}")


def _data_transferred(dpa: dict, mechanism: Any) -> list[KeyPath]:
    """The recorded types of data transferred, which a dpf transfer reads."""
    if not isinstance(mechanism, str) or mechanism.lower() != "dpf":
        return []
    processing = dpa.get("processing")
    if not isinstance(processing, dict):
        return []
    return [path for path in _DATA_TRANSFERRED if path[1] in processing]


def rule_facts(dpa: dict, rule_id: str) -> list[KeyPath]:
    """The input paths the rule with this id reads, in the order the rule reads them."""
    if rule_id.startswith(_ART28_FLAGS):
        return [("art28_clauses", rule_id[len(_ART28_FLAGS):])]
    if rule_id.startswith("processing."):
        return [("processing", rule_id.split(".", 1)[1])]
    if rule_id == "subprocessor.authorization":
        return [("art28_clauses", "subprocessor_authorization")]
    if rule_id == "subprocessor.flowdown":
        return [("art28_clauses", "subprocessor_flowdown")]
    if rule_id == "breach.processor_notifies":
        return [
            ("breach_notification", "processor_notifies_controller"),
            ("breach_notification", "timing"),
        ]
    if rule_id == "transfer.impact_assessment":
        return [("transfers", "transfer_impact_assessment")]
    if rule_id.startswith("ccpa."):
        return [("ccpa", rule_id.split(".", 1)[1])]
    if rule_id.startswith(_SUBPROCESSOR_TRANSFER):
        entries = dpa.get("subprocessors") or []
        matched: list[KeyPath] = []
        for index, entry in enumerate(entries):
            if isinstance(entry, dict) and _subprocessor_rule_id(entry, index) == rule_id:
                matched.append(("subprocessors", index))
                matched += _data_transferred(dpa, entry.get("transfer_mechanism"))
        return matched
    if rule_id.startswith("transfer."):
        code = rule_id.split(".", 1)[1]
        transfers = dpa.get("transfers") or {}
        destinations = transfers.get("destinations") or []
        facts: list[KeyPath] = [
            ("transfers", "destinations", index)
            for index, country in enumerate(destinations)
            if str(country).lower() == code
        ]
        mechanism = None
        for name, read_for in _PER_COUNTRY:
            recorded = transfers.get(name)
            if not isinstance(recorded, dict):
                continue
            # A dpf_* or derogation fact recorded beside another mechanism is not read by the rule,
            # so it is not this finding's evidence.
            if read_for and (not isinstance(mechanism, str) or mechanism.lower() != read_for):
                continue
            for key, value in recorded.items():
                if key.lower() == code:
                    facts.append(("transfers", name, key))
                    if name == "mechanisms":
                        mechanism = value
        return facts + _data_transferred(dpa, mechanism)
    return []


def _related(evidence_path: KeyPath, fact: KeyPath) -> bool:
    """Evidence applies to a fact it names, to a part of that fact, or to a section holding it."""
    shorter = min(len(evidence_path), len(fact))
    return evidence_path[:shorter] == fact[:shorter]


def evidence_for(dpa: dict, rule_id: str) -> list[dict[str, str]]:
    """The evidence entries the input records for the facts this rule reads, in input order."""
    evidence = dpa.get("evidence")
    if not isinstance(evidence, dict):
        return []
    facts = rule_facts(dpa, rule_id)
    found = []
    for key, item in evidence.items():
        path = parse_fact_path(key)
        if path is None or not isinstance(item, dict):
            continue
        if any(_related(path, fact) for fact in facts):
            entry = {"fact": format_path(path)}
            entry.update({name: item[name] for name in ("clause", "quote") if isinstance(item.get(name), str)})
            found.append(entry)
    return found


# --- Line numbers ------------------------------------------------------------

_WHITESPACE = re.compile(r"[ \t\n\r]*")


def key_lines(text: str) -> dict[KeyPath, int]:
    """The 1-based line of every key and list item in a JSON document that json.loads accepts.

    The path () is the document itself. A repeated key keeps the line of its first occurrence.
    """
    newlines = [match.start() for match in re.finditer("\n", text)]
    decoder = json.JSONDecoder()
    lines: dict[KeyPath, int] = {}

    def line(offset: int) -> int:
        return bisect.bisect_left(newlines, offset) + 1

    def skip(index: int) -> int:
        return _WHITESPACE.match(text, index).end()

    def value(index: int, path: KeyPath) -> int:
        index = skip(index)
        lines.setdefault(path, line(index))
        char = text[index]
        if char == "{":
            index = skip(index + 1)
            if text[index] == "}":
                return index + 1
            while True:
                key_start = skip(index)
                key, index = json.decoder.scanstring(text, key_start + 1)
                lines.setdefault(path + (key,), line(key_start))
                index = skip(index) + 1  # the colon
                index = value(index, path + (key,))
                index = skip(index)
                if text[index] == "}":
                    return index + 1
                index += 1  # the comma
        if char == "[":
            index = skip(index + 1)
            if text[index] == "]":
                return index + 1
            position = 0
            while True:
                index = skip(value(index, path + (position,)))
                if text[index] == "]":
                    return index + 1
                index += 1
                position += 1
        return decoder.raw_decode(text, index)[1]

    value(0, ())
    return lines


def line_of(lines: dict[KeyPath, int], path: KeyPath) -> int:
    """The line of `path`, or of its nearest ancestor the input records."""
    while path and path not in lines:
        path = path[:-1]
    return lines.get(path, 1)
