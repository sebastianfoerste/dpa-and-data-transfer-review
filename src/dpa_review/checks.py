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
# Department of Commerce. A listed certification states the data it covers, and the
# exporter checks that it covers the type of data transferred (HR or non-HR data). HR data
# from the employment context is covered only where the organisation's self-certification
# extends to it (DPF Principles, Annex I, Supplemental Principles 6 "Self-Certification"
# and 9 "Human Resources Data").
DPF_COUNTRY = "US"
DPF_DECISION = "Commission Implementing Decision (EU) 2023/1795"

# Standard Contractual Clauses (Art. 46(2)(c)): Commission Implementing Decision (EU)
# 2021/914 of 4 June 2021 on standard contractual clauses for the transfer of personal data
# to third countries pursuant to Regulation (EU) 2016/679 (OJ L 199, 7.6.2021, p. 31).
# Since CJEU C-311/18 (Schrems II), an exporter relying on an Art. 46 tool assesses the
# destination's law and practice and adds supplementary measures where needed: EDPB
# Recommendations 01/2020 on measures that supplement transfer tools to ensure compliance
# with the EU level of protection of personal data, version 2.0, adopted 18 June 2021.
SCC_DECISION = "Commission Implementing Decision (EU) 2021/914"
SUPPLEMENTARY_MEASURES = "EDPB Recommendations 01/2020"
SUPPLEMENTARY_MEASURES_TITLE = (
    "EDPB Recommendations 01/2020 on measures that supplement transfer tools to ensure "
    "compliance with the EU level of protection of personal data, version 2.0, adopted "
    "18 June 2021"
)

# Art. 49 derogations apply only in the absence of an Art. 45(3) adequacy decision or of
# Art. 46 safeguards (Art. 49(1)). EDPB Guidelines 2/2018 on derogations of Article 49
# under Regulation 2016/679 (adopted 25 May 2018), section 1, require them to be interpreted
# restrictively, and say that a transfer that occurs regularly within a stable relationship
# between exporter and importer "can basically be deemed as systematic and repeated", so it
# cannot be considered occasional or not repetitive. Recital 111 expressly limits only the
# contract and legal-claims derogations (Art. 49(1)(b), (c) and (e)) to occasional
# transfers, and the second subparagraph of Art. 49(1) requires a transfer that is not
# repetitive; the guidelines read the other derogations as exceptions too. A DPA governs an
# ongoing processing relationship, so as a conservative tool default a derogation is treated
# like a missing basis unless the input records the transfer as occasional and not
# repetitive.
ART49_GUIDELINES = "EDPB Guidelines 2/2018, section 1"
ART49_GUIDELINES_TITLE = (
    "EDPB Guidelines 2/2018 on derogations of Article 49 under Regulation 2016/679, "
    "adopted 25 May 2018, section 1"
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


class InvalidInputError(ValueError):
    """A DPA input field has the wrong shape, so the review cannot run on it."""


def _get(d: dict, path: str, default=None):
    """The value at a dotted path, or `default` when it is absent or null.

    Every field on the path above the value must be an object: a review cannot run on a
    section given as a list or a scalar, so that is refused rather than read as absent.
    """
    cur: Any = d
    walked: list[str] = []
    for part in path.split("."):
        if cur is None:
            return default
        if not isinstance(cur, dict):
            raise InvalidInputError(f"{'.'.join(walked)} must be an object, got {cur!r}.")
        if part not in cur:
            return default
        cur = cur[part]
        walked.append(part)
    return default if cur is None else cur


def _flag(value: Any, field: str) -> bool | None:
    """A recorded yes/no fact: a JSON boolean, or None when the input does not say."""
    if value is None or isinstance(value, bool):
        return value
    raise InvalidInputError(f"{field} must be true or false, got {value!r}.")


def _recorded(dpa: dict, path: str) -> bool:
    """A yes/no fact that counts only when the input records it as true."""
    return bool(_flag(_get(dpa, path), path))


def _text(value: Any, field: str) -> str | None:
    """A recorded word or phrase, or None when the input does not say."""
    if value is None or isinstance(value, str):
        return value
    raise InvalidInputError(f"{field} must be a string, got {value!r}.")


def _labels(dpa: dict, path: str, example: str) -> list[str]:
    """A list of non-empty strings, such as the categories of data subjects."""
    value = _get(dpa, path)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise InvalidInputError(
            f"{path} must be a list of non-empty strings, such as {example}; got {value!r}."
        )
    return value


def _objects(dpa: dict, path: str) -> list[dict]:
    """A list of objects, such as the sub-processors."""
    value = _get(dpa, path)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise InvalidInputError(f"{path} must be a list of objects, got {value!r}.")
    return value


def _by_country(dpa: dict, path: str, read: Callable[[Any, str], Any], example: str) -> dict[str, Any]:
    """A fact recorded per destination, as an object keyed by country code.

    Country codes are compared without case, as assess_transfer does, so a flag keyed "us"
    applies to the destination "US". Two keys for the same country are refused.
    """
    value = _get(dpa, path)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidInputError(
            f"{path} must be an object keyed by country code, such as {example}; got {value!r}."
        )
    recorded: dict[str, Any] = {}
    for key, item in value.items():
        country = key.upper()
        if country in recorded:
            raise InvalidInputError(f"{path} records {country} more than once (country codes ignore case).")
        recorded[country] = read(item, f"{path}.{key}")
    return recorded


def _country_flags(dpa: dict, path: str) -> dict[str, bool | None]:
    """A yes/no fact recorded per destination."""
    return _by_country(dpa, path, _flag, '{"US": true}')


def transfer_mechanisms(dpa: dict) -> dict[str, str | None]:
    """The transfer mechanism recorded per destination, keyed by upper-case country code."""
    return _by_country(dpa, "transfers.mechanisms", _text, '{"US": "sccs"}')


def _destinations(dpa: dict) -> list[str]:
    """The direct transfer destinations as upper-case country codes, each listed once."""
    destinations = [country.upper() for country in _labels(dpa, "transfers.destinations", '["US"]')]
    repeated = sorted({country for country in destinations if destinations.count(country) > 1})
    if repeated:
        raise InvalidInputError(
            f"transfers.destinations lists {', '.join(repeated)} more than once (country codes ignore case)."
        )
    return destinations


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
    for key, citation, title in _ART28_CLAUSES:
        present = _recorded(dpa, f"art28_clauses.{key}")
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
        present = _recorded(dpa, f"processing.{key}")
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
    data_types = _labels(dpa, "processing.data_types", '["account data"]')
    findings.append(
        Finding(
            rule_id="processing.data_types",
            title="Processing description: type of personal data",
            citation="GDPR Art. 28(3)",
            severity="MEDIUM",
            status="PRESENT" if data_types else "MISSING",
            detail=(
                f"The types of personal data are listed: {', '.join(data_types)}."
                if data_types
                else "The type of personal data is not listed."
            ),
            remediation="" if data_types else "List the type of personal data processed.",
        )
    )
    data_subjects = _labels(dpa, "processing.data_subjects", '["customer end users"]')
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
    path = "art28_clauses.subprocessor_authorization"
    auth = _text(_get(dpa, path), path) or "none"
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
    flowdown = _recorded(dpa, "art28_clauses.subprocessor_flowdown")
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
    processor_notifies = _recorded(dpa, "breach_notification.processor_notifies_controller")
    timing = (_text(_get(dpa, "breach_notification.timing"), "breach_notification.timing") or "").lower()
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

def _join(labels: list[str]) -> tuple[str, str]:
    """Join data-type labels for a sentence, with the matching verb."""
    return " and ".join(labels), ("are" if len(labels) > 1 else "is")


def _assess_dpf(
    country: str,
    *,
    certified: bool,
    covers_hr_data: bool,
    covers_non_hr_data: bool,
    includes_hr_data: bool | None,
    includes_non_hr_data: bool | None,
) -> tuple[str, str, str]:
    """A DPF transfer relies on an Art. 45 adequacy decision limited to listed US organisations.

    The listed certification must also cover each type of data transferred: non-HR data,
    and HR data where HR data is in scope. An `includes_*` value of None means the DPA does
    not say whether that type of data is transferred.
    """
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
    if not certified:
        return (
            "MISSING",
            "HIGH",
            (
                f"Transfer to {country} is recorded as relying on {basis}, but the importer is not "
                "recorded as actively certified on the Data Privacy Framework List; the decision "
                "covers only organisations on that list."
            ),
        )
    uncovered: list[str] = []
    unknown: list[str] = []
    for label, covered, in_scope in (
        ("non-HR data", covers_non_hr_data, includes_non_hr_data),
        ("HR data", covers_hr_data, includes_hr_data),
    ):
        if covered or in_scope is False:
            continue
        (uncovered if in_scope else unknown).append(label)
    if uncovered:
        data, verb = _join(uncovered)
        return (
            "MISSING",
            "HIGH",
            (
                f"Transfer to {country} relies on {basis}, and {data} {verb} in scope, but the "
                f"importer's DPF certification is not recorded as covering {data}."
            ),
        )
    if unknown:
        data, verb = _join(unknown)
        return (
            "NEEDS_REVIEW",
            "MEDIUM",
            (
                f"Transfer to {country} relies on {basis}; the importer is recorded as certified on the "
                f"Data Privacy Framework List, but its certification is not recorded as covering "
                f"{data}, and the DPA does not say whether {data} {verb} transferred. "
                "Confirm the data the certification covers."
            ),
        )
    return (
        "PRESENT",
        "LOW",
        (
            f"Transfer to {country} relies on {basis}; the importer is recorded as actively certified "
            "on the Data Privacy Framework List for the data transferred. As an Art. 45 basis it needs "
            "no transfer impact assessment; re-check the listing before relying on it."
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
            "that occurs regularly within a stable relationship between exporter and importer can "
            f"basically be deemed systematic and repeated ({ART49_GUIDELINES_TITLE}). For the ongoing "
            "transfers a DPA governs, this tool treats such a derogation as a missing basis; no "
            "Art. 45 adequacy decision or Art. 46 safeguard is recorded for this transfer."
        ),
    )


# Recorded mechanisms that do not fit a destination with its own adequacy decision: the DPF
# covers only organisations in the United States, and Art. 49 applies only in the absence of
# an Art. 45(3) adequacy decision or Art. 46 safeguards (Art. 49(1)).
_ADEQUACY_REDUNDANT = {
    "dpf": "the EU-US Data Privacy Framework, which covers only organisations in the United States",
    "derogation_art49": (
        "an Art. 49 derogation, which applies only in the absence of an adequacy decision or "
        "appropriate safeguards (Art. 49(1))"
    ),
}


def assess_transfer(
    country: str,
    mechanism: str | None,
    *,
    dpf_certified: bool = False,
    dpf_covers_hr_data: bool = False,
    dpf_covers_non_hr_data: bool = False,
    includes_hr_data: bool | None = None,
    includes_non_hr_data: bool | None = None,
    occasional_and_not_repetitive: bool = False,
) -> tuple[str, str, str]:
    """Return (status, severity, detail) for a single destination country.

    The `dpf_*` keywords describe the importer's entry on the Data Privacy Framework List:
    an active certification, and whether it covers HR and non-HR data. The `includes_*`
    keywords say whether the DPA transfers HR and non-HR data (None means it does not say).
    `occasional_and_not_repetitive` is the recorded nature of a derogation-based transfer.
    """
    country = (country or "").upper()
    mech = (mechanism or "none").lower()
    if country in EEA:
        return ("PRESENT", "INFO", f"{country} is within the EEA; no Chapter V transfer mechanism required.")
    if country in ADEQUACY:
        if mech in {"none", "adequacy"}:
            return ("PRESENT", "LOW", f"{country} benefits from an adequacy decision (Art. 45).")
        if mech in _ADEQUACY_REDUNDANT:
            return (
                "NEEDS_REVIEW",
                "LOW",
                (
                    f"{country} benefits from an adequacy decision (Art. 45), but the transfer is recorded "
                    f"as relying on {_ADEQUACY_REDUNDANT[mech]}. Confirm the basis relied on and record the "
                    "adequacy decision."
                ),
            )
    if mech == "adequacy":
        # Recorded as adequacy, but the destination has no decision on the tool's list.
        detail = (
            f"Transfer to {country} is recorded as relying on an Art. 45 adequacy decision, but no "
            f"Commission adequacy decision for {country} is on the tool's adequacy list."
        )
        if country == DPF_COUNTRY:
            detail += (
                f" For the United States, the adequacy decision ({DPF_DECISION}) covers only "
                "organisations on the Data Privacy Framework List: record the mechanism as dpf, "
                "with the importer's certification."
            )
        else:
            detail += " The list is illustrative; confirm whether a current adequacy decision covers it."
        return ("MISSING", "HIGH", detail)
    if mech != "none" and mech not in VALID_TRANSFER_MECHANISMS:
        return (
            "MISSING",
            "HIGH",
            (
                f"Transfer to {country} is recorded as relying on '{mechanism}', which is not a Chapter V "
                "basis this tool recognises (adequacy, dpf, sccs, bcr or derogation_art49); no "
                "Art. 45 adequacy decision, Art. 46 safeguard or Art. 49 derogation is recorded."
            ),
        )
    if mech == "dpf":
        return _assess_dpf(
            country,
            certified=dpf_certified,
            covers_hr_data=dpf_covers_hr_data,
            covers_non_hr_data=dpf_covers_non_hr_data,
            includes_hr_data=includes_hr_data,
            includes_non_hr_data=includes_non_hr_data,
        )
    if mech == "derogation_art49":
        return _assess_derogation(country, occasional_and_not_repetitive)
    if mech in {"sccs", "bcr"}:
        label = {
            "sccs": f"Standard Contractual Clauses (Art. 46(2)(c); {SCC_DECISION})",
            "bcr": "Binding Corporate Rules (Art. 47)",
        }[mech]
        return (
            "NEEDS_REVIEW",
            "LOW",
            (
                f"Transfer to {country} relies on {label}; confirm validity, a transfer impact "
                f"assessment and any supplementary measures ({SUPPLEMENTARY_MEASURES})."
            ),
        )
    return (
        "MISSING",
        "HIGH",
        (
            f"Transfer to {country} has no recorded Chapter V basis: no Art. 45 adequacy decision "
            "(including the EU-US Data Privacy Framework), Art. 46 safeguard or Art. 49 derogation "
            "is recorded."
        ),
    )


def _transfer_articles(country: str, mechanism: str | None) -> str:
    """Chapter V provisions behind a transfer finding, for its citation."""
    mech = (mechanism or "none").lower()
    if country.upper() in ADEQUACY and mech in _ADEQUACY_REDUNDANT:
        return "Art. 44-45"
    if mech == "dpf":
        return f"Art. 44-45; {DPF_DECISION}"
    if mech == "derogation_art49":
        return f"Art. 44, 49; {ART49_GUIDELINES}"
    if mech == "sccs":
        return f"Art. 44-46; {SCC_DECISION}"
    return "Art. 44-46"


def _transfer_remediation(country: str, mechanism: str | None, occasional_and_not_repetitive: bool) -> str:
    mech = (mechanism or "none").lower()
    if country.upper() in ADEQUACY and mech in _ADEQUACY_REDUNDANT:
        return f"Record reliance on the Art. 45 adequacy decision for {country} as the transfer basis."
    if mech == "adequacy" and country.upper() not in ADEQUACY:
        if country.upper() == DPF_COUNTRY:
            return (
                f"Record the mechanism for {country} as dpf, with the importer's active certification on "
                "the Data Privacy Framework List and the data it covers, or record an Art. 46 safeguard."
            )
        return (
            f"Confirm that a current Commission adequacy decision covers {country} (the tool's adequacy "
            f"list is illustrative), or record an Art. 46 safeguard for {country}."
        )
    if mech == "dpf":
        return (
            "Record the importer's active certification on the Data Privacy Framework List and the "
            "data it covers (non-HR data, and HR data if HR data is transferred), or another "
            f"Chapter V basis for {country}."
        )
    if mech == "derogation_art49" and occasional_and_not_repetitive:
        return f"Record which Art. 49(1) derogation applies to the transfer to {country} and how its conditions are met."
    if mech == "derogation_art49":
        return (
            f"Record an Art. 45 adequacy basis or an Art. 46 safeguard for {country}, or record that "
            "the transfer is occasional and not repetitive and which Art. 49(1) derogation applies."
        )
    if mech in {"sccs", "bcr"}:
        tool = {
            "sccs": f"the SCCs of {SCC_DECISION}",
            "bcr": "approved Binding Corporate Rules (Art. 47)",
        }[mech]
        return (
            f"Confirm that {tool} cover the transfer to {country}, with a transfer impact assessment "
            f"and any supplementary measures ({SUPPLEMENTARY_MEASURES})."
        )
    return f"Record an Art. 45 adequacy basis or an Art. 46 safeguard for {country}."


def check_transfers(dpa: dict) -> list[Finding]:
    findings: list[Finding] = []
    destinations = _destinations(dpa)
    mechanisms = transfer_mechanisms(dpa)
    subprocessors = _objects(dpa, "subprocessors")
    dpf_certified = _country_flags(dpa, "transfers.dpf_certified")
    dpf_covers_hr_data = _country_flags(dpa, "transfers.dpf_covers_hr_data")
    dpf_covers_non_hr_data = _country_flags(dpa, "transfers.dpf_covers_non_hr_data")
    occasional = _country_flags(dpa, "transfers.occasional_and_not_repetitive")
    # None: the DPA does not say whether that type of data is transferred.
    includes_hr_data = _flag(_get(dpa, "processing.includes_hr_data"), "processing.includes_hr_data")
    includes_non_hr_data = _flag(
        _get(dpa, "processing.includes_non_hr_data"), "processing.includes_non_hr_data"
    )

    for country in destinations:
        is_occasional = bool(occasional.get(country))
        status, severity, detail = assess_transfer(
            country,
            mechanisms.get(country),
            dpf_certified=bool(dpf_certified.get(country)),
            dpf_covers_hr_data=bool(dpf_covers_hr_data.get(country)),
            dpf_covers_non_hr_data=bool(dpf_covers_non_hr_data.get(country)),
            includes_hr_data=includes_hr_data,
            includes_non_hr_data=includes_non_hr_data,
            occasional_and_not_repetitive=is_occasional,
        )
        findings.append(
            Finding(
                rule_id=f"transfer.{str(country).lower()}",
                title=f"International transfer to {country}",
                citation="GDPR " + _transfer_articles(str(country), mechanisms.get(country)),
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
    for index, sp in enumerate(subprocessors):
        for key in ("name", "country", "transfer_mechanism"):
            _text(sp.get(key), f"subprocessors[{index}].{key}")
        flags = {
            key: bool(_flag(sp.get(key), f"subprocessors[{index}].{key}"))
            for key in (
                "dpf_certified",
                "dpf_covers_hr_data",
                "dpf_covers_non_hr_data",
                "occasional_and_not_repetitive",
            )
        }
        country = (sp.get("country") or "").upper()
        if country and country not in EEA:
            status, severity, detail = assess_transfer(
                country,
                sp.get("transfer_mechanism"),
                **flags,
                includes_hr_data=includes_hr_data,
                includes_non_hr_data=includes_non_hr_data,
            )
            findings.append(
                Finding(
                    rule_id=f"transfer.subprocessor.{sp.get('name', 'unknown').lower().replace(' ', '_')}",
                    title=f"Sub-processor transfer: {sp.get('name', 'unknown')} ({country})",
                    citation="GDPR Art. 28(4) / " + _transfer_articles(country, sp.get("transfer_mechanism")),
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
    tia = _recorded(dpa, "transfers.transfer_impact_assessment")
    relies_on_safeguards = any(
        (mechanisms.get(c, "none") or "none").lower() in {"sccs", "bcr"} for c in destinations
    ) or any(
        (sp.get("transfer_mechanism") or "none").lower() in {"sccs", "bcr"}
        for sp in subprocessors
    )
    if relies_on_safeguards:
        findings.append(
            Finding(
                rule_id="transfer.impact_assessment",
                title="Transfer impact assessment (Schrems II)",
                citation=f"GDPR Art. 46 (CJEU C-311/18); {SUPPLEMENTARY_MEASURES}",
                severity="MEDIUM",
                status="PRESENT" if tia else "NEEDS_REVIEW",
                detail=(
                    "A transfer impact assessment is recorded for safeguard-based transfers."
                    if tia
                    else "Safeguard-based transfers are present but no transfer impact assessment is recorded."
                ),
                remediation=(
                    "" if tia
                    else (
                        "Document a transfer impact assessment, and any supplementary measures, for each "
                        f"Art. 46-based transfer ({SUPPLEMENTARY_MEASURES_TITLE})."
                    )
                ),
            )
        )
    return findings


# --- CCPA service-provider basics (secondary, US) ----------------------------

def check_ccpa(dpa: dict) -> list[Finding]:
    sp_terms = _recorded(dpa, "ccpa.service_provider_terms")
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
