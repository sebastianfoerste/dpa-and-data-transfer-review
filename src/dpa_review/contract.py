"""The input contract: every key a DPA description may contain, its JSON type, and which keys
are required.

The rules read the input with defaults, so an absent key reads as "not recorded". That is
right for a clause the DPA lacks, and wrong for a key that is absent because it was misspelt:
a "transfer" section instead of "transfers" used to read as "no direct transfers", and a DPA
with an unchecked US transfer could come out CLEARED_FOR_REVIEW with exit 0. The CLI therefore
checks every input against this contract before any rule runs, and refuses one that breaks it
with exit 3:

* an unknown key, at any level, is refused, with the closest known key as a suggestion;
* a required section or key that is missing or null is refused;
* a value of the wrong JSON type is refused, so the string "false" in a flag is not read as present;
* a processing description that is blank or only an absence marker, such as "not specified" or
  "false" in any case, is refused, so it is not read as a stated description;
* a few cross-field rules that JSON Schema cannot express are checked as well.

`json_schema()` writes the same contract out as JSON Schema (schema/dpa.schema.json, regenerated
with `make docs`) for editors, agents and CI validators; the tests keep the two identical.
The contract is hand-written and standard library only, like the rest of the package.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Union

from dpa_review.checks import (
    ABSENCE_MARKER_PATTERN,
    ABSENCE_MARKERS,
    VALID_TRANSFER_MECHANISMS,
    is_absence_marker,
)

SCHEMA_ID = (
    "https://raw.githubusercontent.com/sebastianfoerste/dpa-and-data-transfer-review/"
    "main/schema/dpa.schema.json"
)

# Every Chapter V basis the transfer rules recognise, plus "none" for a recorded absence.
MECHANISMS = ("none", "adequacy", "sccs", "bcr", "dpf", "derogation_art49")
# GDPR Art. 28(2): prior specific or general written authorisation, or neither.
AUTHORISATIONS = ("specific", "general", "none")

COUNTRY_PATTERN = "^[A-Z]{2}$"
# Two-letter codes that look right but are not ISO 3166-1 alpha-2 country codes.
NOT_ISO_COUNTRIES = {
    "UK": '"GB" (the ISO code for the United Kingdom)',
    "EL": '"GR" (the ISO code for Greece)',
    "EU": "the code of the member state where the data is processed, e.g. \"DE\"",
}
FACT_PATH_PATTERN = r"^[A-Za-z0-9_]+(\[[0-9]+\])?(\.[A-Za-z0-9_]+(\[[0-9]+\])?)*$"
_COUNTRY = re.compile(COUNTRY_PATTERN)
_FACT_PATH = re.compile(FACT_PATH_PATTERN)
_FACT_PATH_PART = re.compile(r"([A-Za-z0-9_]+)((?:\[[0-9]+\])?)")
_PLAIN_KEY = re.compile(r"\$?[A-Za-z0-9_]+")  # printed as is in a path; other keys are quoted

# A path into the input: object keys and list indexes, e.g. ("subprocessors", 1, "country").
KeyPath = tuple[Union[str, int], ...]


@dataclass
class Field:
    """One key of the contract.

    kind is one of: flag (a JSON boolean), text (a string), name (a non-empty string),
    description (a boolean, or a string that is neither blank nor an absence marker such as
    "n/a"), country (a two-letter code), choice (one of
    `options`), labels (a list of non-empty strings), countries (a list of country codes),
    section (an object with `fields`), entries (a list of objects with `fields`),
    by_country (an object keyed by country code, each value a `value`), evidence (the
    evidence map). An optional key may also be null, which reads as not recorded, unless
    `nullable` is False.
    """

    kind: str
    description: str
    required: bool = False
    nullable: bool = True  # False where the engine cannot read null as "not recorded"
    hint: str = ""  # how to record "none", shown when a required key is missing
    fields: dict[str, Field] = field(default_factory=dict)
    options: tuple[str, ...] = ()
    value: Field | None = None
    example: str = ""


def _flag(description: str) -> Field:
    return Field("flag", description)


_ART28 = "true when the DPA contains the clause; false, null or omitted when it was not found."
_MARKERS = ", ".join(f'"{marker}"' for marker in ABSENCE_MARKERS[:-1]) + f' or "{ABSENCE_MARKERS[-1]}"'
_DESCRIPTION = (
    "false, null or omitted when it is not stated. A blank string, or " + _MARKERS + " in any case, "
    "is refused."
)

CONTRACT: dict[str, Field] = {
    "$schema": Field(
        "text",
        "The URL or path of schema/dpa.schema.json, so an editor can check and complete the file as you "
        "type. No rule reads it.",
        nullable=False,
    ),
    "agreement": Field("text", "Name of the agreement, used as the packet title. No rule reads it.", nullable=False),
    "controller": Field("text", "Name of the controller. Labels the transfer evidence graph; no rule reads it.", nullable=False),
    "processor": Field("text", "Name of the processor. Labels the transfer evidence graph; no rule reads it.", nullable=False),
    "roles_defined": _flag("Whether the DPA defines the controller and processor roles. Recorded only: no rule reads it."),
    "processing": Field(
        "section",
        "The processing details GDPR Art. 28(3) requires the DPA to set out. Read by the processing.* rules.",
        required=True,
        hint='add "processing": {} and record what the DPA states about the processing',
        fields={
            "subject_matter": Field(
                "description",
                "The subject matter of the processing is stated: true, or a short description; "
                + _DESCRIPTION
                + " Rule processing.subject_matter.",
            ),
            "duration": Field(
                "description",
                "The duration of the processing is stated: true, or a short description; "
                + _DESCRIPTION
                + " Rule processing.duration.",
            ),
            "nature_and_purpose": Field(
                "description",
                "The nature and purpose of the processing are stated: true, or a short description; "
                + _DESCRIPTION
                + " Rule processing.nature_and_purpose.",
            ),
            "data_types": Field(
                "labels",
                "The types of personal data processed. Rule processing.data_types: an empty or omitted "
                "list is MISSING.",
                example='["account data"]',
            ),
            "data_subjects": Field(
                "labels",
                "The categories of data subjects. Rule processing.data_subjects: an empty or omitted "
                "list is MISSING.",
                example='["customer end users"]',
            ),
        },
    ),
    "art28_clauses": Field(
        "section",
        "The processor clauses GDPR Art. 28(2)-(4) require. Each flag is " + _ART28,
        required=True,
        hint='add "art28_clauses": {} and record each clause the DPA contains as true',
        fields={
            "process_on_documented_instructions": _flag(
                "Art. 28(3)(a): the processor processes only on documented instructions. "
                "Rule art28.process_on_documented_instructions."
            ),
            "confidentiality_commitment": _flag(
                "Art. 28(3)(b): persons authorised to process are bound to confidentiality. "
                "Rule art28.confidentiality_commitment."
            ),
            "security_measures_art32": _flag(
                "Art. 28(3)(c): the processor takes the security measures of Art. 32. "
                "Rule art28.security_measures_art32."
            ),
            "subprocessor_authorization": Field(
                "choice",
                'Art. 28(2): "specific" (prior specific written authorisation), "general" (general '
                'written authorisation) or "none". Rule subprocessor.authorization: "none", null or '
                'omitted is MISSING. "general" also runs rule subprocessor.change_notice_and_objection.',
                options=AUTHORISATIONS,
            ),
            "subprocessor_change_notice_and_objection": _flag(
                "Art. 28(2), second sentence, read with Art. 28(3)(d): under general written authorisation, "
                "the processor informs the controller of any intended addition or replacement of a "
                "sub-processor, giving the controller the opportunity to object. Read only when "
                'subprocessor_authorization is "general" (rule subprocessor.change_notice_and_objection).'
            ),
            "subprocessor_flowdown": _flag(
                "Art. 28(4): the same data-protection obligations are imposed on every sub-processor. "
                "Rule subprocessor.flowdown."
            ),
            "assist_data_subject_requests": _flag(
                "Art. 28(3)(e): the processor assists with data-subject requests. "
                "Rule art28.assist_data_subject_requests."
            ),
            "assist_security_breach": _flag(
                "Art. 28(3)(f): the processor assists with security, breach and DPIA obligations "
                "(Art. 32-36). Rule art28.assist_security_breach."
            ),
            "delete_or_return_on_termination": _flag(
                "Art. 28(3)(g): the processor deletes or returns the data at the end of the services. "
                "Rule art28.delete_or_return_on_termination."
            ),
            "audit_and_inspection_rights": _flag(
                "Art. 28(3)(h): the processor allows and contributes to audits and inspections. "
                "Rule art28.audit_and_inspection_rights."
            ),
        },
    ),
    "breach_notification": Field(
        "section",
        "Breach-notification terms (GDPR Art. 33(2)). Read by rule breach.processor_notifies.",
        required=True,
        hint='add "breach_notification": {} and record the breach-notification terms',
        fields={
            "processor_notifies_controller": _flag(
                "The processor notifies the controller of a personal-data breach. Rule breach.processor_notifies."
            ),
            "timing": Field(
                "text",
                'The notice period as the DPA words it, e.g. "without undue delay". The rule passes only '
                'wording that contains "undue delay" or "without delay"; other wording goes to review.',
            ),
            "controller_notifies_authority_art33": _flag(
                "The controller's own notice to the supervisory authority is addressed. Recorded only: "
                "no rule reads it."
            ),
        },
    ),
    "subprocessors": Field(
        "entries",
        "Every sub-processor the DPA names or authorises. Each one outside the EEA is checked as a "
        "transfer (rule transfer.subprocessor.<name>). Record [] when there are none.",
        required=True,
        hint='record "subprocessors": [] if the DPA names and authorises no sub-processor',
        fields={
            "name": Field(
                "name",
                "The sub-processor's name. Names must differ, ignoring case, spaces and punctuation, "
                "because rule ids are derived from them.",
                required=True,
                hint="give every sub-processor a name",
            ),
            "country": Field(
                "country",
                'Upper-case ISO 3166-1 alpha-2 code of the country where it processes the data, e.g. "US" '
                '(the United Kingdom is "GB", Greece is "GR").',
                required=True,
                hint='record where it processes the data as a two-letter country code, e.g. "US"',
            ),
            "purpose": Field(
                "text", "What the sub-processor does. Labels the graph; no rule reads it.", nullable=False
            ),
            "transfer_mechanism": Field(
                "choice",
                "The Chapter V basis for a sub-processor outside the EEA. Null or omitted reads as none.",
                options=MECHANISMS,
            ),
        },
    ),
    "transfers": Field(
        "section",
        "Transfers of personal data that the processor makes directly to other countries.",
        required=True,
        hint='record "transfers": {"destinations": []} if the processor makes no direct transfer',
        fields={
            "destinations": Field(
                "countries",
                "Upper-case ISO 3166-1 alpha-2 codes of every country the processor transfers personal data "
                "to directly; each is checked (rule transfer.<country>). Record [] when there are none.",
                required=True,
                hint='record "destinations": [] if the processor makes no direct transfer',
            ),
            "mechanisms": Field(
                "by_country",
                "The Chapter V basis per destination, keyed by a country that destinations lists. "
                "A destination without an entry reads as none.",
                value=Field("choice", "The Chapter V basis for this destination.", options=MECHANISMS),
                example='{"US": "sccs"}',
            ),
            "transfer_impact_assessment": _flag(
                "A transfer impact assessment is recorded. Read only when SCCs or BCR are relied on "
                "(rule transfer.impact_assessment)."
            ),
        },
    ),
    "ccpa": Field(
        "section",
        "California CCPA/CPRA terms, a secondary lens. Omitted reads as not recorded, which goes to review.",
        fields={
            "service_provider_terms": _flag(
                "Service-provider terms restricting the sale and retention of personal information are "
                "present. Rule ccpa.service_provider_terms."
            ),
        },
    ),
    "evidence": Field(
        "evidence",
        "Where each recorded fact comes from in the DPA, keyed by the fact's path, e.g. "
        '{"art28_clauses.subprocessor_flowdown": {"clause": "§ 7.2", "quote": "..."}}. The packet '
        "prints it next to the findings that read the fact. A key must name a fact this input records.",
    ),
}

_EVIDENCE_ITEM = {
    "clause": "Where the fact is in the DPA, e.g. \"§ 7.2\" or \"Annex 3\".",
    "quote": "The DPA's own words, quoted verbatim.",
}

assert set(MECHANISMS) == VALID_TRANSFER_MECHANISMS | {"none"}, "contract and rules disagree on mechanisms"


# --- Paths -------------------------------------------------------------------


def format_path(path: KeyPath) -> str:
    """A path as people write it: art28_clauses.subprocessor_flowdown, subprocessors[1].country."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        elif _PLAIN_KEY.fullmatch(part):
            text += f".{part}" if text else part
        else:
            text += f"[{json.dumps(part, ensure_ascii=False)}]"
    return text


def parse_fact_path(text: str) -> KeyPath | None:
    """The path a fact-path string names, or None when it is not one."""
    if not _FACT_PATH.fullmatch(text):
        return None
    path: list[str | int] = []
    for part in text.split("."):
        key, index = _FACT_PATH_PART.fullmatch(part).groups()
        path.append(key)
        if index:
            path.append(int(index[1:-1]))
    return tuple(path)


def _resolve(document: Any, path: KeyPath) -> tuple[bool, Any]:
    current = document
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return False, None
        elif not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def fact_paths(dpa: dict) -> list[str]:
    """Every fact path present in the input, outside the evidence map, in document order."""
    found: list[str] = []

    def walk(value: Any, path: KeyPath) -> None:
        if path:
            found.append(format_path(path))
        if isinstance(value, dict):
            for key, item in value.items():
                if path or key != "evidence":
                    walk(item, path + (key,))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, path + (index,))

    walk(dpa, ())
    return found


# --- Validation --------------------------------------------------------------


@dataclass
class Violation:
    """One way the input breaks the contract, located by the path it concerns."""

    path: KeyPath
    message: str


class ContractError(ValueError):
    """The input breaks the contract, so no review state can be decided for it."""

    def __init__(self, violations: list[Violation]):
        self.violations = violations
        super().__init__("; ".join(violation.message for violation in violations))


def _suggest(word: str, candidates: list[str]) -> str:
    lowered = {candidate.lower(): candidate for candidate in candidates}
    if word.lower() in lowered:
        return f"; did you mean {lowered[word.lower()]!r}?"
    close = difflib.get_close_matches(word.lower(), list(lowered), n=1, cutoff=0.6)
    return f"; did you mean {lowered[close[0]]!r}?" if close else ""


def _check_fields(obj: dict, fields: dict[str, Field], path: KeyPath, out: list[Violation]) -> None:
    for key in obj:
        if key not in fields:
            where = format_path(path + (key,))
            suggestion = _suggest(key, list(fields))
            if suggestion:
                suggestion = suggestion.replace("'", "'" + (format_path(path) + "." if path else ""), 1)
            out.append(Violation(path + (key,), f"unknown key {where!r}{suggestion}"))
    for key, spec in fields.items():
        where = path + (key,)
        if key not in obj:
            if spec.required:
                out.append(Violation(where, f"missing required key {format_path(where)!r}: {spec.hint}."))
            continue
        _check(obj[key], spec, where, out)


def _check(value: Any, spec: Field, path: KeyPath, out: list[Violation]) -> None:
    where = format_path(path)

    def refuse(expected: str) -> None:
        out.append(Violation(path, f"{where} must be {expected}, got {value!r}."))

    if value is None:
        if spec.required:
            out.append(Violation(path, f"{where} is required and cannot be null: {spec.hint}."))
        elif not spec.nullable:
            out.append(Violation(path, f"{where} cannot be null; omit it if the DPA does not state it."))
        return
    kind = spec.kind
    if kind == "flag":
        if not isinstance(value, bool):
            refuse("true or false")
    elif kind == "text":
        if not isinstance(value, str):
            refuse("a string")
    elif kind == "name":
        if not isinstance(value, str) or not value.strip():
            refuse("a non-empty string")
    elif kind == "description":
        if not isinstance(value, (bool, str)):
            refuse("a description (a string) or true/false")
        elif isinstance(value, str) and is_absence_marker(value):
            # Read as text, "not specified" would make the rule PRESENT and could clear the packet.
            out.append(
                Violation(
                    path,
                    f"{where} must be a description (a string) or true/false, got {value!r}, which is blank "
                    f"or an absence marker ({', '.join(ABSENCE_MARKERS)}) and states nothing; record false "
                    "when the DPA does not state it.",
                )
            )
    elif kind == "country":
        _check_country(value, path, out)
    elif kind == "choice":
        if not isinstance(value, str) or value not in spec.options:
            suggestion = _suggest(value, list(spec.options)) if isinstance(value, str) else ""
            out.append(
                Violation(path, f"{where} must be one of {', '.join(spec.options)}; got {value!r}{suggestion}")
            )
    elif kind == "labels":
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            refuse(f"a list of non-empty strings, such as {spec.example}; it")
    elif kind == "countries":
        if not isinstance(value, list):
            refuse('a list of non-empty strings (two-letter country codes such as ["US"]); it')
            return
        for index, item in enumerate(value):
            _check_country(item, path + (index,), out)
    elif kind == "section":
        if not isinstance(value, dict):
            refuse("an object")
            return
        _check_fields(value, spec.fields, path, out)
    elif kind == "entries":
        if not isinstance(value, list):
            refuse("a list of objects")
            return
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                item_path = path + (index,)
                out.append(
                    Violation(item_path, f"{where} must be a list of objects, got {item!r} at {format_path(item_path)}.")
                )
                continue
            _check_fields(item, spec.fields, path + (index,), out)
    elif kind == "by_country":
        if not isinstance(value, dict):
            refuse(f"an object keyed by country code, such as {spec.example}; it")
            return
        for key, item in value.items():
            problem = _country_problem(key)
            if problem:
                out.append(Violation(path + (key,), f"{where} is keyed by country code: the key {key!r} {problem}."))
            _check(item, spec.value, path + (key,), out)
    elif kind == "evidence":
        if not isinstance(value, dict):
            refuse('an object keyed by fact path, such as {"art28_clauses.subprocessor_flowdown": {...}}; it')
            return
        for key, item in value.items():
            item_path = path + (key,)
            item_where = format_path(item_path)
            if not isinstance(item, dict):
                out.append(Violation(item_path, f'{item_where} must be an object such as {{"clause": "§ 7.2"}}, got {item!r}.'))
                continue
            for name in item:
                if name not in _EVIDENCE_ITEM:
                    out.append(
                        Violation(item_path + (name,), f"unknown key {name!r} in {item_where}{_suggest(name, list(_EVIDENCE_ITEM))}")
                    )
            if not any(name in item for name in _EVIDENCE_ITEM):
                out.append(Violation(item_path, f"{item_where} must give a clause, a quote, or both."))
            for name in _EVIDENCE_ITEM:
                text = item.get(name)
                if name in item and (not isinstance(text, str) or not text.strip()):
                    out.append(
                        Violation(
                            item_path + (name,),
                            f"{format_path(item_path + (name,))} must be a non-empty string, got {text!r}.",
                        )
                    )
    else:  # pragma: no cover - a contract entry with an unknown kind is a programming error
        raise AssertionError(f"unknown contract kind {kind!r}")


def _country_problem(value: Any) -> str:
    """Why `value` is not a country code the rules can match, or "" when it is one."""
    if not isinstance(value, str) or not re.fullmatch("[A-Za-z]{2}", value):
        return 'is not a two-letter ISO 3166-1 alpha-2 code such as "US"'
    if value in NOT_ISO_COUNTRIES:
        return f"is not an ISO 3166-1 alpha-2 country code; use {NOT_ISO_COUNTRIES[value]}"
    if not _COUNTRY.fullmatch(value):
        # The rules compare codes exactly, so "us" would not find the "US" mechanism.
        return f"must be upper case: use {value.upper()!r}"
    return ""


def _check_country(value: Any, path: KeyPath, out: list[Violation]) -> None:
    problem = _country_problem(value)
    if problem:
        out.append(Violation(path, f"{format_path(path)} {problem}, got {value!r}."))


def _name_key(name: str) -> str:
    # Coarser than checks.subprocessor_rule_id, whose id without its underscores ends in this key,
    # so two names that pass here never share a rule id.
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def _check_cross_field(dpa: dict, out: list[Violation]) -> None:
    transfers = dpa.get("transfers")
    if isinstance(transfers, dict):
        destinations = transfers.get("destinations")
        listed: dict[str, int] = {}
        if isinstance(destinations, list):
            for index, country in enumerate(destinations):
                if not isinstance(country, str):
                    continue
                if country in listed:
                    out.append(
                        Violation(
                            ("transfers", "destinations", index),
                            f"transfers.destinations lists {country} more than once.",
                        )
                    )
                listed.setdefault(country, index)
        mechanisms = transfers.get("mechanisms")
        # Checked only once every destination is a valid code, so one typo is reported once.
        if (
            isinstance(mechanisms, dict)
            and isinstance(destinations, list)
            and not any(_country_problem(country) for country in destinations)
        ):
            for key in mechanisms:
                if not _country_problem(key) and key not in listed:
                    out.append(
                        Violation(
                            ("transfers", "mechanisms", key),
                            f"transfers.mechanisms records {key}, which transfers.destinations does not list; "
                            f"add {key} to destinations, or record a sub-processor's mechanism on its own entry.",
                        )
                    )
    subprocessors = dpa.get("subprocessors")
    if isinstance(subprocessors, list):
        names: dict[str, int] = {}
        for index, entry in enumerate(subprocessors):
            name = entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name.strip():
                continue
            key = _name_key(name)
            if key in names:
                first = names[key]
                out.append(
                    Violation(
                        ("subprocessors", index, "name"),
                        f"subprocessors[{index}].name {name!r} repeats subprocessors[{first}].name "
                        f"{subprocessors[first]['name']!r} (names are compared without case, spaces and "
                        "punctuation); give each entry a distinct name, such as one that adds its country.",
                    )
                )
            else:
                names[key] = index
    evidence = dpa.get("evidence")
    if isinstance(evidence, dict):
        known: list[str] | None = None
        for key in evidence:
            parsed = parse_fact_path(key)
            where = ("evidence", key)
            if parsed is None:
                out.append(
                    Violation(
                        where,
                        f"evidence key {key!r} is not a fact path such as "
                        '"art28_clauses.subprocessor_flowdown" or "subprocessors[1].country".',
                    )
                )
            elif parsed[0] == "evidence" or not _resolve(dpa, parsed)[0]:
                if known is None:
                    known = fact_paths(dpa)
                out.append(
                    Violation(where, f"evidence key {key!r} names no fact this input records{_suggest(key, known)}")
                )


def violations(dpa: Any) -> list[Violation]:
    """Every way `dpa` breaks the contract, in document order; empty when it conforms."""
    if not isinstance(dpa, dict):
        return [Violation((), f"the DPA input must be a JSON object, got {type(dpa).__name__}.")]
    out: list[Violation] = []
    _check_fields(dpa, CONTRACT, (), out)
    _check_cross_field(dpa, out)
    return out


def validate(dpa: Any) -> None:
    """Raise ContractError when `dpa` breaks the contract. The CLI calls this before any rule."""
    found = violations(dpa)
    if found:
        raise ContractError(found)


# --- JSON Schema -------------------------------------------------------------


def _types(spec: Field, *names: str) -> str | list[str]:
    names_list = list(names) if spec.required or not spec.nullable else [*names, "null"]
    return names_list[0] if len(names_list) == 1 else names_list


_COUNTRY_SCHEMA: dict[str, Any] = {"pattern": COUNTRY_PATTERN, "not": {"enum": sorted(NOT_ISO_COUNTRIES)}}


def _object(fields: dict[str, Field]) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "additionalProperties": False,
        "properties": {key: _schema(spec) for key, spec in fields.items()},
    }
    required = [key for key, spec in fields.items() if spec.required]
    if required:
        schema["required"] = required
    return schema


def _schema(spec: Field) -> dict[str, Any]:
    kind = spec.kind
    schema: dict[str, Any] = {"description": spec.description}
    if kind == "flag":
        schema["type"] = _types(spec, "boolean")
    elif kind == "text":
        schema["type"] = _types(spec, "string")
    elif kind == "name":
        schema.update(type=_types(spec, "string"), pattern=r"\S")
    elif kind == "description":
        schema["type"] = _types(spec, "boolean", "string")
        # "type": "string" inside "not" keeps true and false valid: the pattern refuses strings only.
        schema["not"] = {"type": "string", "pattern": ABSENCE_MARKER_PATTERN}
    elif kind == "country":
        schema.update(type=_types(spec, "string"), **_COUNTRY_SCHEMA)
    elif kind == "choice":
        nullable = spec.nullable and not spec.required
        schema.update(type=_types(spec, "string"), enum=[*spec.options] + ([None] if nullable else []))
    elif kind == "labels":
        schema.update(type=_types(spec, "array"), items={"type": "string", "pattern": r"\S"})
    elif kind == "countries":
        schema.update(
            type=_types(spec, "array"),
            items={"type": "string", **_COUNTRY_SCHEMA},
            uniqueItems=True,
        )
    elif kind == "section":
        schema.update(type=_types(spec, "object"), **_object(spec.fields))
    elif kind == "entries":
        schema.update(type=_types(spec, "array"), items={"type": "object", **_object(spec.fields)})
    elif kind == "by_country":
        schema.update(
            type=_types(spec, "object"),
            propertyNames=_COUNTRY_SCHEMA,
            additionalProperties=_schema(spec.value),
        )
    elif kind == "evidence":
        schema.update(
            type=_types(spec, "object"),
            propertyNames={"pattern": FACT_PATH_PATTERN},
            additionalProperties={
                "type": "object",
                "description": "The clause and quote that support one recorded fact.",
                "additionalProperties": False,
                "minProperties": 1,
                "properties": {
                    name: {"description": text, "type": "string", "pattern": r"\S"}
                    for name, text in _EVIDENCE_ITEM.items()
                },
            },
        )
    else:  # pragma: no cover - a contract entry with an unknown kind is a programming error
        raise AssertionError(f"unknown contract kind {kind!r}")
    return schema


def json_schema() -> dict[str, Any]:
    """The contract as a JSON Schema (draft 2020-12) document."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "dpa-review input: a structured description of one Data Processing Agreement",
        "description": (
            "Generated from src/dpa_review/contract.py by `make docs`; docs/input-format.md explains "
            "every key. The CLI enforces this schema and, beyond it, a few cross-field rules: every "
            "transfers.mechanisms key is a listed destination, "
            "sub-processor names are unique ignoring case, spaces and punctuation, and every evidence "
            "key names a fact the input records. Input that breaks any of them exits 3."
        ),
        "type": "object",
        **_object(CONTRACT),
    }


def schema_text() -> str:
    """schema/dpa.schema.json exactly as committed."""
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
