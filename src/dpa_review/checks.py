"""Deterministic DPA and international data-transfer checks.

Each rule maps a single, observable feature of a Data Processing Agreement (DPA)
to a citation, a severity, and a plain-language finding. The rules are intentionally
boring: they do not interpret, they check whether a required, citeable element is
present, missing, or needs human review. This is a review packet, never legal advice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Callable

# --- Reference data (kept small, explicit, and citeable) ---------------------

# EEA member states (data transfers within the EEA are not "third country" transfers).
EEA = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES",
    "SE", "IS", "LI", "NO",
}

# Third countries with a European Commission adequacy decision (Art. 45).
# Illustrative and synthetic-data oriented; verify against the current list in practice.
ADEQUACY = {"AD", "AR", "CA", "FO", "GG", "IL", "IM", "JP", "JE", "NZ", "CH", "GB", "UY", "KR"}

VALID_TRANSFER_MECHANISMS = {"adequacy", "sccs", "bcr", "derogation_art49", "dpf"}

SEVERITY_ORDER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}


@dataclass
class Finding:
    rule_id: str
    title: str
    citation: str
    severity: str           # HIGH | MEDIUM | LOW | INFO
    status: str             # PRESENT | MISSING | NEEDS_REVIEW
    detail: str
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get(d: dict, path: str, default=None):
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


# --- Article 28(3) mandatory processor clauses -------------------------------

_ART28_CLAUSES: list[tuple[str, str, str]] = [
    # (json key, citation, human title)
    ("process_on_documented_instructions", "GDPR Art. 28(3)(a)", "Processing only on documented instructions"),
    ("confidentiality_commitment", "GDPR Art. 28(3)(b)", "Confidentiality commitment for authorised persons"),
    ("security_measures_art32", "GDPR Art. 28(3)(c) / Art. 32", "Security of processing (technical & organisational measures)"),
    ("assist_data_subject_requests", "GDPR Art. 28(3)(e)", "Assistance with data-subject rights requests"),
    ("assist_security_breach", "GDPR Art. 28(3)(f)", "Assistance with security, breach, DPIA obligations"),
    ("delete_or_return_on_termination", "GDPR Art. 28(3)(g)", "Deletion or return of data on termination"),
    ("audit_and_inspection_rights", "GDPR Art. 28(3)(h)", "Audit and inspection rights"),
]


def check_art28_core(dpa: dict) -> list[Finding]:
    findings: list[Finding] = []
    clauses = dpa.get("art28_clauses", {})
    for key, citation, title in _ART28_CLAUSES:
        present = bool(clauses.get(key, False))
        findings.append(
            Finding(
                rule_id=f"art28.{key}",
                title=title,
                citation=citation,
                severity="HIGH",
                status="PRESENT" if present else "MISSING",
                detail=(
                    f"Clause '{title}' is present in the DPA."
                    if present
                    else f"Mandatory Art. 28(3) clause '{title}' was not found."
                ),
                remediation=(
                    "" if present else f"Add an explicit clause satisfying {citation}."
                ),
            )
        )
    return findings


# --- Processing description (Art. 28(3) opening / Art. 30) --------------------

# Strings that record a processing description as absent or unknown instead of stating it. A
# description that is one of them (trimmed, in any case) or a blank string states nothing: the
# input contract refuses it with exit 3, and the rules below read it as not stated, never as
# PRESENT. Only these whole values are caught; any other wording is read as a description.
ABSENCE_MARKERS = ("false", "no", "none", "n/a", "unknown", "not specified", "tbd")
# _any_case copies every character other than a letter unescaped into the pattern.
assert all(re.fullmatch("[a-z/ ]+", marker) for marker in ABSENCE_MARKERS), "escape the new marker"


def _any_case(word: str) -> str:
    # "no" -> "[Nn][Oo]": case-insensitive without a regex flag, which a JSON Schema pattern cannot carry.
    return "".join(f"[{ch.upper()}{ch.lower()}]" if ch.isalpha() else ch for ch in word)


# A blank string, or one absence marker with any whitespace around it. schema/dpa.schema.json
# refuses description strings with the same pattern, so the schema and the CLI agree.
# The trailing \s* sits inside the optional group, so two whitespace runs never meet: with
# r"^\s*(?:...)?\s*$" a long run of whitespace followed by text backtracked in quadratic time.
ABSENCE_MARKER_PATTERN = (
    r"^\s*(?:(?:" + "|".join(_any_case(marker) for marker in ABSENCE_MARKERS) + r")\s*)?$"
)
_ABSENCE_MARKER = re.compile(ABSENCE_MARKER_PATTERN)


def is_absence_marker(value: str) -> bool:
    """True for a blank string or an absence marker such as " N/A ", which states no description."""
    return _ABSENCE_MARKER.search(value) is not None


def _description_stated(value: Any) -> bool:
    if isinstance(value, str):
        return not is_absence_marker(value)
    return bool(value)


def check_processing_description(dpa: dict) -> list[Finding]:
    required = {
        "subject_matter": "subject matter of the processing",
        "duration": "duration of the processing",
        "nature_and_purpose": "nature and purpose of the processing",
    }
    findings: list[Finding] = []
    for key, label in required.items():
        present = _description_stated(_get(dpa, f"processing.{key}", False))
        findings.append(
            Finding(
                rule_id=f"processing.{key}",
                title=f"Processing description: {label}",
                citation="GDPR Art. 28(3)",
                severity="MEDIUM",
                status="PRESENT" if present else "MISSING",
                detail=(
                    f"The DPA specifies the {label}."
                    if present
                    else f"The DPA does not clearly specify the {label}."
                ),
                remediation="" if present else f"State the {label} in the processing schedule.",
            )
        )
    data_types = _get(dpa, "processing.data_types", []) or []
    findings.append(
        Finding(
            rule_id="processing.data_types",
            title="Processing description: categories of personal data",
            citation="GDPR Art. 28(3)",
            severity="MEDIUM",
            status="PRESENT" if data_types else "MISSING",
            detail=(
                f"Categories of personal data are listed: {', '.join(data_types)}."
                if data_types
                else "No categories of personal data are listed."
            ),
            remediation="" if data_types else "List the categories of personal data processed.",
        )
    )
    data_subjects = _get(dpa, "processing.data_subjects", []) or []
    findings.append(
        Finding(
            rule_id="processing.data_subjects",
            title="Processing description: categories of data subjects",
            citation="GDPR Art. 28(3)",
            severity="MEDIUM",
            status="PRESENT" if data_subjects else "MISSING",
            detail=(
                f"Categories of data subjects are listed: {', '.join(data_subjects)}."
                if data_subjects
                else "No categories of data subjects are listed."
            ),
            remediation=(
                "" if data_subjects else "List the categories of data subjects whose personal data is processed."
            ),
        )
    )
    return findings


# --- Sub-processor authorisation and flow-down (Art. 28(2) and 28(4)) --------

def check_subprocessors(dpa: dict) -> list[Finding]:
    findings: list[Finding] = []
    auth = _get(dpa, "art28_clauses.subprocessor_authorization", "none")
    findings.append(
        Finding(
            rule_id="subprocessor.authorization",
            title="Sub-processor authorisation",
            citation="GDPR Art. 28(2)",
            severity="HIGH",
            status="PRESENT" if auth in {"specific", "general"} else "MISSING",
            detail=(
                f"Sub-processor authorisation is '{auth}'."
                if auth in {"specific", "general"}
                else "No prior written sub-processor authorisation mechanism found."
            ),
            remediation=(
                "" if auth in {"specific", "general"}
                else "Add specific or general written authorisation with a change-notice right."
            ),
        )
    )
    flowdown = bool(_get(dpa, "art28_clauses.subprocessor_flowdown", False))
    findings.append(
        Finding(
            rule_id="subprocessor.flowdown",
            title="Sub-processor flow-down of data-protection obligations",
            citation="GDPR Art. 28(4)",
            severity="HIGH",
            status="PRESENT" if flowdown else "MISSING",
            detail=(
                "The DPA imposes the same data-protection obligations on sub-processors."
                if flowdown
                else "The DPA does not flow the same data-protection obligations down to sub-processors."
            ),
            remediation=(
                "" if flowdown
                else "Add a clause imposing materially equivalent obligations on every sub-processor (Art. 28(4))."
            ),
        )
    )
    return findings


# --- Breach notification (Art. 33) -------------------------------------------

def check_breach_notification(dpa: dict) -> list[Finding]:
    processor_notifies = bool(_get(dpa, "breach_notification.processor_notifies_controller", False))
    timing = (_get(dpa, "breach_notification.timing", "") or "").lower()
    acceptable_timing = "undue delay" in timing or "without delay" in timing
    status = "PRESENT" if (processor_notifies and acceptable_timing) else (
        "NEEDS_REVIEW" if processor_notifies else "MISSING"
    )
    return [
        Finding(
            rule_id="breach.processor_notifies",
            title="Personal-data breach notification to controller",
            citation="GDPR Art. 33(2)",
            severity="HIGH",
            status=status,
            detail=(
                f"Processor notifies controller; timing recorded as '{timing or 'unspecified'}'."
                if processor_notifies
                else "No processor-to-controller breach-notification obligation found."
            ),
            remediation=(
                "" if status == "PRESENT"
                else "State that the processor notifies the controller without undue delay after becoming aware."
            ),
        )
    ]


# --- Chapter V international transfers (Art. 44-49) ---------------------------

SUBPROCESSOR_TRANSFER = "transfer.subprocessor."


def subprocessor_rule_id(name: Any) -> str:
    """The rule id of the transfer check for the sub-processor with this name.

    The name is case-folded, and each run of characters other than letters and digits becomes one
    underscore, with none at either end: "Support Tools, LLC" gives
    transfer.subprocessor.support_tools_llc. The check, the fact mapping (facts.py) and the
    transfer graph all take the id from here, so a finding, its evidence and its graph edge name
    the same rule. Without its underscores the id ends in the key the input contract compares
    names by (contract._name_key), so two names the contract accepts together never share an id.
    """
    words = "".join(ch if ch.isalnum() else " " for ch in str(name).casefold()).split()
    return SUBPROCESSOR_TRANSFER + "_".join(words)


def assess_transfer(country: str, mechanism: str | None) -> tuple[str, str, str]:
    """Return (status, severity, detail) for a single destination country."""
    country = (country or "").upper()
    mech = (mechanism or "none").lower()
    if country in EEA:
        return ("PRESENT", "INFO", f"{country} is within the EEA; no Chapter V transfer mechanism required.")
    if country in ADEQUACY and mech in {"none", "adequacy"}:
        return ("PRESENT", "LOW", f"{country} benefits from an adequacy decision (Art. 45).")
    if mech in {"sccs", "bcr", "dpf", "derogation_art49"}:
        label = {
            "sccs": "Standard Contractual Clauses (Art. 46(2)(c))",
            "bcr": "Binding Corporate Rules (Art. 47)",
            "dpf": "an approved certification / framework (Art. 46)",
            "derogation_art49": "an Art. 49 derogation",
        }[mech]
        sev = "MEDIUM" if mech == "derogation_art49" else "LOW"
        return ("NEEDS_REVIEW", sev, f"Transfer to {country} relies on {label}; confirm validity and a transfer impact assessment.")
    return (
        "MISSING",
        "HIGH",
        f"Transfer to {country} has no valid Chapter V mechanism (no adequacy, SCCs, BCR, or Art. 49 derogation).",
    )


def check_transfers(dpa: dict) -> list[Finding]:
    findings: list[Finding] = []
    destinations = _get(dpa, "transfers.destinations", []) or []
    mechanisms = _get(dpa, "transfers.mechanisms", {}) or {}

    for country in destinations:
        status, severity, detail = assess_transfer(country, mechanisms.get(country))
        findings.append(
            Finding(
                rule_id=f"transfer.{str(country).lower()}",
                title=f"International transfer to {country}",
                citation="GDPR Art. 44-46",
                severity=severity,
                status=status,
                detail=detail,
                remediation=(
                    "" if status == "PRESENT"
                    else f"Document a valid Art. 46 safeguard for {country} (or an Art. 49 derogation) and record the basis."
                ),
            )
        )

    # Sub-processor located in a third country is itself a transfer.
    for sp in _get(dpa, "subprocessors", []) or []:
        country = (sp.get("country") or "").upper()
        if country and country not in EEA:
            status, severity, detail = assess_transfer(country, sp.get("transfer_mechanism"))
            findings.append(
                Finding(
                    rule_id=subprocessor_rule_id(sp.get("name", "unknown")),
                    title=f"Sub-processor transfer: {sp.get('name', 'unknown')} ({country})",
                    citation="GDPR Art. 28(4) / Art. 44-46",
                    severity=severity,
                    status=status,
                    detail=f"{sp.get('name', 'unknown')} processes data in {country}. {detail}",
                    remediation=(
                        "" if status == "PRESENT"
                        else f"Confirm the transfer mechanism covering {sp.get('name', 'unknown')} in {country}."
                    ),
                )
            )

    # Transfer impact assessment (Schrems II): required where Art. 46 tools are relied on.
    relies_on_safeguards = any(
        (mechanisms.get(c, "none") or "none").lower() in {"sccs", "bcr"} for c in destinations
    ) or any(
        (sp.get("transfer_mechanism") or "none").lower() in {"sccs", "bcr"}
        for sp in (_get(dpa, "subprocessors", []) or [])
    )
    if relies_on_safeguards:
        tia = bool(_get(dpa, "transfers.transfer_impact_assessment", False))
        findings.append(
            Finding(
                rule_id="transfer.impact_assessment",
                title="Transfer impact assessment (Schrems II)",
                citation="GDPR Art. 46 (CJEU C-311/18)",
                severity="MEDIUM",
                status="PRESENT" if tia else "NEEDS_REVIEW",
                detail=(
                    "A transfer impact assessment is recorded for safeguard-based transfers."
                    if tia
                    else "Safeguard-based transfers are present but no transfer impact assessment is recorded."
                ),
                remediation="" if tia else "Document a transfer impact assessment for each Art. 46-based transfer.",
            )
        )
    return findings


# --- CCPA service-provider basics (secondary, US) ----------------------------

def check_ccpa(dpa: dict) -> list[Finding]:
    sp_terms = bool(_get(dpa, "ccpa.service_provider_terms", False))
    return [
        Finding(
            rule_id="ccpa.service_provider_terms",
            title="CCPA/CPRA service-provider terms",
            citation="CCPA §1798.140(ag); CPRA §1798.100(d)",
            severity="LOW",
            status="PRESENT" if sp_terms else "NEEDS_REVIEW",
            detail=(
                "Service-provider / contractor terms restricting sale and retention are present."
                if sp_terms
                else "No CCPA/CPRA service-provider terms detected; review if US personal information is in scope."
            ),
            remediation="" if sp_terms else "Add CCPA/CPRA service-provider language if California personal information is processed.",
        )
    ]


ALL_CHECKS: list[Callable[[dict], list[Finding]]] = [
    check_processing_description,
    check_art28_core,
    check_subprocessors,
    check_breach_notification,
    check_transfers,
    check_ccpa,
]


def run_all_checks(dpa: dict) -> list[Finding]:
    findings: list[Finding] = []
    for check in ALL_CHECKS:
        findings.extend(check(dpa))
    return findings
