"""Deterministic DPA and international data-transfer checks.

Each rule maps a single, observable feature of a Data Processing Agreement (DPA)
to a citation, a severity, and a plain-language finding. The rules are intentionally
boring: they do not interpret, they check whether a required, citeable element is
present, missing, or needs human review. This is a review packet, never legal advice.
"""

from __future__ import annotations

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

# EU-US Data Privacy Framework (DPF): Commission Implementing Decision (EU) 2023/1795 of
# 10 July 2023, adopted under Art. 45(3). It is an adequacy decision, not an Art. 46
# safeguard. Its Article 1 limits the adequacy finding to organisations in the United
# States that are included in the "Data Privacy Framework List" maintained by the U.S.
# Department of Commerce. HR data from the employment context is covered only where the
# organisation's self-certification extends to it (DPF Principles, Annex I, Supplemental
# Principle 9 "Human Resources Data").
DPF_COUNTRY = "US"
DPF_DECISION = "Commission Implementing Decision (EU) 2023/1795"

# Art. 49 derogations: EDPB Guidelines 2/2018 on derogations of Article 49 under
# Regulation 2016/679 (adopted 25 May 2018) require the derogations to be interpreted
# restrictively, and treat a transfer that occurs regularly within a stable relationship
# between exporter and importer as systematic and repeated, so it is not occasional or
# not repetitive (see also the "not repetitive" condition in Art. 49(1), second
# subparagraph). Transfers under a DPA serve an ongoing processing relationship, so a
# derogation is treated like a missing basis unless the input records the transfer as
# occasional and not repetitive.
ART49_GUIDELINES = "EDPB Guidelines 2/2018"
ART49_GUIDELINES_TITLE = (
    "EDPB Guidelines 2/2018 on derogations of Article 49 under Regulation 2016/679 "
    "(adopted 25 May 2018)"
)

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

def check_processing_description(dpa: dict) -> list[Finding]:
    required = {
        "subject_matter": "subject matter of the processing",
        "duration": "duration of the processing",
        "nature_and_purpose": "nature and purpose of the processing",
    }
    findings: list[Finding] = []
    for key, label in required.items():
        present = bool(_get(dpa, f"processing.{key}", False))
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
            remediation="" if data_subjects else "List the categories of data subjects whose personal data is processed.",
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

def _assess_dpf(
    country: str,
    dpf_certified: bool,
    dpf_covers_hr_data: bool,
    includes_hr_data: bool | None,
) -> tuple[str, str, str]:
    """A DPF transfer relies on an Art. 45 adequacy decision limited to listed US organisations."""
    basis = f"the EU-US Data Privacy Framework adequacy decision (Art. 45; {DPF_DECISION})"
    if country != DPF_COUNTRY:
        return (
            "MISSING",
            "HIGH",
            (
                f"Transfer to {country} is recorded as relying on {basis}, which covers only "
                "organisations in the United States."
            ),
        )
    if not dpf_certified:
        return (
            "MISSING",
            "HIGH",
            (
                f"Transfer to {country} is recorded as relying on {basis}, but the importer is not "
                "recorded as actively certified on the Data Privacy Framework List; the decision "
                "covers only organisations on that list."
            ),
        )
    if not dpf_covers_hr_data and includes_hr_data is True:
        return (
            "MISSING",
            "HIGH",
            (
                f"Transfer to {country} relies on {basis}, and HR data is in scope, but the importer's "
                "DPF certification is not recorded as covering HR data."
            ),
        )
    if not dpf_covers_hr_data and includes_hr_data is None:
        return (
            "NEEDS_REVIEW",
            "MEDIUM",
            (
                f"Transfer to {country} relies on {basis}; the importer is recorded as certified on the "
                "Data Privacy Framework List, but not for HR data. Confirm whether HR data is transferred."
            ),
        )
    return (
        "PRESENT",
        "LOW",
        (
            f"Transfer to {country} relies on {basis}; the importer is recorded as actively certified "
            "on the Data Privacy Framework List. As an Art. 45 basis it needs no transfer impact "
            "assessment; re-check the listing before relying on it."
        ),
    )


def _assess_derogation(country: str, occasional_and_not_repetitive: bool) -> tuple[str, str, str]:
    """An Art. 49 derogation is an exception, not a basis for systematic or repeated transfers."""
    if occasional_and_not_repetitive:
        return (
            "NEEDS_REVIEW",
            "MEDIUM",
            (
                f"Transfer to {country} relies on an Art. 49 derogation and is recorded as occasional "
                "and not repetitive; confirm which Art. 49(1) derogation applies and that its "
                f"conditions are met. Derogations are interpreted restrictively ({ART49_GUIDELINES_TITLE})."
            ),
        )
    return (
        "MISSING",
        "HIGH",
        (
            f"Transfer to {country} relies on an Art. 49 derogation, but it is not recorded as "
            "occasional and not repetitive. Derogations are interpreted restrictively, and a transfer "
            "that occurs regularly within a stable relationship between exporter and importer is "
            f"systematic and repeated ({ART49_GUIDELINES_TITLE}). No Art. 45 or Art. 46 basis is "
            "recorded for this transfer."
        ),
    )


def assess_transfer(
    country: str,
    mechanism: str | None,
    *,
    dpf_certified: bool = False,
    dpf_covers_hr_data: bool = False,
    includes_hr_data: bool | None = None,
    occasional_and_not_repetitive: bool = False,
) -> tuple[str, str, str]:
    """Return (status, severity, detail) for a single destination country.

    The DPF keywords describe the importer's entry on the Data Privacy Framework List and
    whether the DPA covers HR data (None means the DPA does not say).
    `occasional_and_not_repetitive` is the recorded nature of a derogation-based transfer.
    """
    country = (country or "").upper()
    mech = (mechanism or "none").lower()
    if country in EEA:
        return ("PRESENT", "INFO", f"{country} is within the EEA; no Chapter V transfer mechanism required.")
    if country in ADEQUACY and mech in {"none", "adequacy"}:
        return ("PRESENT", "LOW", f"{country} benefits from an adequacy decision (Art. 45).")
    if mech == "dpf":
        return _assess_dpf(country, dpf_certified, dpf_covers_hr_data, includes_hr_data)
    if mech == "derogation_art49":
        return _assess_derogation(country, occasional_and_not_repetitive)
    if mech in {"sccs", "bcr"}:
        label = {
            "sccs": "Standard Contractual Clauses (Art. 46(2)(c))",
            "bcr": "Binding Corporate Rules (Art. 47)",
        }[mech]
        return ("NEEDS_REVIEW", "LOW", f"Transfer to {country} relies on {label}; confirm validity and a transfer impact assessment.")
    return (
        "MISSING",
        "HIGH",
        f"Transfer to {country} has no valid Chapter V mechanism (no adequacy, SCCs, BCR, or Art. 49 derogation).",
    )


def _transfer_articles(mechanism: str | None) -> str:
    """Chapter V provisions behind a transfer finding, for its citation."""
    mech = (mechanism or "none").lower()
    if mech == "dpf":
        return f"Art. 44-45; {DPF_DECISION}"
    if mech == "derogation_art49":
        return f"Art. 44, 49; {ART49_GUIDELINES}"
    return "Art. 44-46"


def _transfer_remediation(country: str, mechanism: str | None, occasional_and_not_repetitive: bool) -> str:
    mech = (mechanism or "none").lower()
    if mech == "dpf":
        return (
            f"Record the importer's active certification on the Data Privacy Framework List "
            f"(covering HR data if HR data is transferred), or another Chapter V basis for {country}."
        )
    if mech == "derogation_art49" and occasional_and_not_repetitive:
        return f"Record which Art. 49(1) derogation applies to the transfer to {country} and how its conditions are met."
    return (
        f"Record an Art. 45 adequacy basis or an Art. 46 safeguard for {country}; "
        f"Art. 49 derogations are interpreted restrictively ({ART49_GUIDELINES})."
    )


def check_transfers(dpa: dict) -> list[Finding]:
    findings: list[Finding] = []
    destinations = _get(dpa, "transfers.destinations", []) or []
    mechanisms = _get(dpa, "transfers.mechanisms", {}) or {}
    dpf_certified = _get(dpa, "transfers.dpf_certified", {}) or {}
    dpf_covers_hr_data = _get(dpa, "transfers.dpf_covers_hr_data", {}) or {}
    hr_flag = _get(dpa, "processing.includes_hr_data")
    includes_hr_data = None if hr_flag is None else bool(hr_flag)  # None: the DPA does not say
    occasional = _get(dpa, "transfers.occasional_and_not_repetitive", {}) or {}

    for country in destinations:
        is_occasional = bool(occasional.get(country, False))
        status, severity, detail = assess_transfer(
            country,
            mechanisms.get(country),
            dpf_certified=bool(dpf_certified.get(country, False)),
            dpf_covers_hr_data=bool(dpf_covers_hr_data.get(country, False)),
            includes_hr_data=includes_hr_data,
            occasional_and_not_repetitive=is_occasional,
        )
        findings.append(
            Finding(
                rule_id=f"transfer.{str(country).lower()}",
                title=f"International transfer to {country}",
                citation="GDPR " + _transfer_articles(mechanisms.get(country)),
                severity=severity,
                status=status,
                detail=detail,
                remediation=(
                    "" if status == "PRESENT"
                    else _transfer_remediation(country, mechanisms.get(country), is_occasional)
                ),
            )
        )

    # Sub-processor located in a third country is itself a transfer.
    for sp in _get(dpa, "subprocessors", []) or []:
        country = (sp.get("country") or "").upper()
        if country and country not in EEA:
            status, severity, detail = assess_transfer(
                country,
                sp.get("transfer_mechanism"),
                dpf_certified=bool(sp.get("dpf_certified", False)),
                dpf_covers_hr_data=bool(sp.get("dpf_covers_hr_data", False)),
                includes_hr_data=includes_hr_data,
                occasional_and_not_repetitive=bool(sp.get("occasional_and_not_repetitive", False)),
            )
            findings.append(
                Finding(
                    rule_id=f"transfer.subprocessor.{sp.get('name', 'unknown').lower().replace(' ', '_')}",
                    title=f"Sub-processor transfer: {sp.get('name', 'unknown')} ({country})",
                    citation="GDPR Art. 28(4) / " + _transfer_articles(sp.get("transfer_mechanism")),
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
    # DPF transfers rely on an Art. 45 adequacy decision and therefore do not trigger it.
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
