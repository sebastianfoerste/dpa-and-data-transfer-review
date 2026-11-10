"""Deterministic DPA and international data-transfer checks.

Each rule maps a single, observable feature of a Data Processing Agreement (DPA)
to a citation, a severity, and a plain-language finding. The rules are intentionally
boring: they do not interpret, they check whether a required, citeable element is
present, missing, or needs human review. This is a review packet, never legal advice.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Callable

# --- Reference data (kept small, explicit, and citeable) ---------------------

# EEA member states (data transfers within the EEA are not "third country" transfers).
EEA = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES",
    "SE", "IS", "LI", "NO",
}


@dataclass(frozen=True)
class AdequacyDecision:
    """A Commission adequacy decision for one third country, as its text on EUR-Lex states it.

    `scope_limit` restates the limit the decision's operative part sets on what it covers: the
    recipients, the processing or the purposes. It is empty when Article 1 covers personal data
    transferred from the Union to the country without such a limit. The tool cannot check a limit
    from its input, so a finding that relies on the decision states it for the reviewer.
    `directive_era` marks a decision adopted under Article 25(6) of Directive 95/46/EC, which stays
    in force under Art. 45(9) GDPR until amended, replaced or repealed. `amending_acts` are the acts
    that changed the decision's scope or validity, which its citation names; `amended` says what
    they changed, for the reference table in docs/rules.md; `expires` is the date the decision
    itself sets for its expiry.
    """

    country: str  # ISO 3166-1 alpha-2 code
    name: str
    act: str
    adopted: str
    oj: str
    celex: str
    directive_era: bool = False
    scope_limit: str = ""
    amending_acts: tuple[str, ...] = ()
    amended: str = ""
    expires: str = ""

    @property
    def limited(self) -> bool:
        return bool(self.scope_limit)

    @property
    def articles(self) -> tuple[str, ...]:
        """The GDPR provisions a transfer on this decision rests on."""
        return ("45(1)", "45(9)") if self.directive_era else ("45(1)",)

    @property
    def documents(self) -> tuple[str, ...]:
        """The acts a finding that relies on this decision cites."""
        return (self.act, *self.amending_acts)

    @property
    def basis(self) -> str:
        """The decision as a finding names it."""
        text = f"Art. 45(1); {self.act} of {self.adopted}"
        if self.amending_acts:
            text += ", as last amended by " + " and ".join(self.amending_acts)
        if self.directive_era:
            text += ", in force under Art. 45(9)"
        if self.expires:
            text += f", which expires on {self.expires}"
        return text


# The date every entry below was last read against the decision's text on EUR-Lex: the operative
# part (Article 1 and, for Israel, Article 2), the date of adoption, the OJ reference, and the
# EUR-Lex record of the act's status (in force; an end of validity only for the United Kingdom). The
# amending acts were read too: Implementing Decision (EU) 2016/2295 replaced the articles on suspending
# data flows and on monitoring in each decision adopted under Directive 95/46/EC and left Article 1
# unchanged; the Isle of Man corrigendum (OJ L 208, 10.6.2004, p. 47) restates the same Article 1. The
# EUR-Lex record of the Israel decision lists one corrigendum (CELEX 32011D0061R(01)), for the Hungarian
# text only. The Uruguay decision's title refers to automated processing, but its Article 1 sets no such
# limit, so the entry has none.
ADEQUACY_VERIFIED_ON = "2026-11-10"

# Third countries with a Commission adequacy decision (Art. 45), keyed by ISO code. The EU-US Data
# Privacy Framework decision is DPF_ADEQUACY below: it covers only listed organisations, so a US
# transfer relies on it through the dpf mechanism and the US is not on this list. The tool models
# countries only, not international organisations.
ADEQUACY: dict[str, AdequacyDecision] = {
    decision.country: decision
    for decision in (
        AdequacyDecision(
            "AD", "Andorra", "Commission Decision 2010/625/EU", "19 October 2010",
            "OJ L 277, 21.10.2010, p. 27", "32010D0625", directive_era=True,
        ),
        AdequacyDecision(
            "AR", "Argentina", "Commission Decision 2003/490/EC", "30 June 2003",
            "OJ L 168, 5.7.2003, p. 19", "32003D0490", directive_era=True,
        ),
        AdequacyDecision(
            "BR", "Brazil", "Commission Implementing Decision (EU) 2026/179", "26 January 2026",
            "OJ L, 2026/179, 28.1.2026", "32026D0179",
            scope_limit=(
                "Its Article 1 covers only personal data transferred to controllers and processors in "
                "Brazil subject to the General Data Protection Law (LGPD)."
            ),
        ),
        AdequacyDecision(
            "CA", "Canada", "Commission Decision 2002/2/EC", "20 December 2001",
            "OJ L 2, 4.1.2002, p. 13", "32002D0002", directive_era=True,
            scope_limit=(
                "Its Article 1 covers only personal data transferred to recipients subject to the "
                "Personal Information Protection and Electronic Documents Act."
            ),
        ),
        AdequacyDecision(
            "CH", "Switzerland", "Commission Decision 2000/518/EC", "26 July 2000",
            "OJ L 215, 25.8.2000, p. 1", "32000D0518", directive_era=True,
        ),
        AdequacyDecision(
            "FO", "Faroe Islands", "Commission Decision 2010/146/EU", "5 March 2010",
            "OJ L 58, 9.3.2010, p. 17", "32010D0146", directive_era=True,
            scope_limit=(
                "Its Article 1 covers only personal data transferred to recipients subject to the Act on "
                "Processing of Personal Data (the Faeroese Act)."
            ),
        ),
        AdequacyDecision(
            "GB", "United Kingdom", "Commission Implementing Decision (EU) 2021/1772", "28 June 2021",
            "OJ L 360, 11.10.2021, p. 1", "32021D1772",
            amending_acts=("Commission Implementing Decision (EU) 2025/2574",),
            amended=(
                "Implementing Decision (EU) 2025/1226 of 24 June 2025 extended it to 27 December 2025; "
                "Implementing Decision (EU) 2025/2574 of 19 December 2025 (OJ L, 2025/2574, 23.12.2025) "
                "repealed its Article 1(2), which excluded data transferred for purposes of United Kingdom "
                "immigration control, and replaced its Article 4, so that it expires on 27 December 2031"
            ),
            expires="27 December 2031",
        ),
        AdequacyDecision(
            "GG", "Guernsey", "Commission Decision 2003/821/EC", "21 November 2003",
            "OJ L 308, 25.11.2003, p. 27", "32003D0821", directive_era=True,
        ),
        AdequacyDecision(
            "IL", "Israel", "Commission Decision 2011/61/EU", "31 January 2011",
            "OJ L 27, 1.2.2011, p. 39", "32011D0061", directive_era=True,
            scope_limit=(
                "Its Article 1 covers only automated international transfers of personal data or, "
                "where a transfer is not automated, data subject to further automated processing in "
                "Israel, and its Article 2 limits it to the State of Israel as defined in accordance "
                "with international law."
            ),
        ),
        AdequacyDecision(
            "IM", "Isle of Man", "Commission Decision 2004/411/EC", "28 April 2004",
            "OJ L 151, 30.4.2004, p. 48", "32004D0411", directive_era=True,
        ),
        AdequacyDecision(
            "JE", "Jersey", "Commission Decision 2008/393/EC", "8 May 2008",
            "OJ L 138, 28.5.2008, p. 21", "32008D0393", directive_era=True,
        ),
        AdequacyDecision(
            "JP", "Japan", "Commission Implementing Decision (EU) 2019/419", "23 January 2019",
            "OJ L 76, 19.3.2019, p. 1", "32019D0419",
            scope_limit=(
                "Its Article 1 covers only personal data transferred to personal information handling "
                "business operators in Japan subject to the Act on the Protection of Personal "
                "Information as complemented by the Supplementary Rules set out in its Annex I, and "
                "Article 1(2) excludes, to the extent of the purposes it lists, press organisations, "
                "persons engaged in professional writing, universities and other organisations or "
                "groups aimed at academic studies, religious bodies and political bodies."
            ),
        ),
        AdequacyDecision(
            "KR", "Republic of Korea", "Commission Implementing Decision (EU) 2022/254", "17 December 2021",
            "OJ L 44, 24.2.2022, p. 1", "32022D0254",
            scope_limit=(
                "Its Article 1 covers only personal data transferred to entities in the Republic of "
                "Korea subject to the Personal Information Protection Act as complemented by the "
                "additional safeguards set out in its Annex I, and Article 1(2) excludes, to the extent "
                "of the purposes it lists, religious organisations (missionary activities), political "
                "parties (nomination of candidates) and entities subject to oversight by the Financial "
                "Services Commission for the processing of personal credit information under the "
                "Credit Information Act."
            ),
        ),
        AdequacyDecision(
            "NZ", "New Zealand", "Commission Implementing Decision 2013/65/EU", "19 December 2012",
            "OJ L 28, 30.1.2013, p. 12", "32013D0065", directive_era=True,
        ),
        AdequacyDecision(
            "UY", "Uruguay", "Commission Implementing Decision 2012/484/EU", "21 August 2012",
            "OJ L 227, 23.8.2012, p. 11", "32012D0484", directive_era=True,
        ),
    )
}

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
DPF_ADEQUACY = AdequacyDecision(
    DPF_COUNTRY, "United States", DPF_DECISION, "10 July 2023", "OJ L 231, 20.9.2023, p. 118", "32023D1795",
    scope_limit=(
        "Its Article 1 covers only personal data transferred to organisations in the United States that "
        "are included in the 'Data Privacy Framework List' maintained by the U.S. Department of Commerce."
    ),
)
# The status of the DPF decision, as EUR-Lex recorded it on ADEQUACY_VERIFIED_ON. The General Court
# dismissed the action for its annulment in Latombe v Commission (judgment of 3 September 2025,
# T-553/23, ECLI:EU:T:2025:831, CELEX 62023TJ0553). EUR-Lex records an appeal against that judgment
# (Case C-703/25 P, brought on 31 October 2025, OJ C, C/2025/6610, 22.12.2025; CELEX 62025CN0703) and
# lists no judgment on it. The EUR-Lex record of the decision also lists a request for a preliminary
# ruling from the Cour d'appel de Bruxelles (Case C-804/25, lodged on 10 December 2025, OJ C,
# C/2026/2199, 27.4.2026), whose tenth question asks whether the decision is an adequacy decision for
# the tax-data transfers at issue there.
DPF_STATUS_NOTE = (
    "Re-check the status of Commission Implementing Decision (EU) 2023/1795 as well: the "
    "General Court dismissed an action for its annulment (Latombe v Commission, T-553/23, judgment of "
    "3 September 2025), and EUR-Lex records an appeal against that judgment (Case C-703/25 P, brought on "
    f"31 October 2025) with no judgment on it as of {ADEQUACY_VERIFIED_ON}."
)

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


@dataclass(frozen=True)
class Safeguard:
    """An Art. 46 safeguard the input can record as a transfer mechanism.

    Art. 46(1) makes these the transfer basis in the absence of an adequacy decision. The tool
    cannot verify an approval, an authorisation or an importer's commitments, so a transfer on any
    of them goes to review, with a transfer impact assessment as for the SCCs.
    """

    mechanism: str
    label: str  # how a finding names the safeguard, with its provision
    short: str  # how a later sentence refers back to it
    articles: tuple[str, ...]
    documents: tuple[str, ...] = ()
    unverifiable: str = ""  # what the tool cannot check; empty for the SCCs and BCR
    confirm: str = "validity"  # what a reviewer confirms, besides the transfer impact assessment
    covers: str = ""  # "Confirm that <covers> the transfer to ..."


# GDPR Art. 46(2) and (3), with Art. 40(3) and 42(2) for codes of conduct and certification, as
# read on EUR-Lex (CELEX 32016R0679) on ADEQUACY_VERIFIED_ON.
SAFEGUARDS: dict[str, Safeguard] = {
    safeguard.mechanism: safeguard
    for safeguard in (
        Safeguard(
            "sccs",
            f"Standard Contractual Clauses (Art. 46(2)(c); {SCC_DECISION})",
            "the SCCs",
            ("46(2)(c)",),
            (SCC_DECISION,),
            covers=f"the SCCs of {SCC_DECISION} cover",
        ),
        Safeguard(
            "bcr",
            "Binding Corporate Rules (Art. 46(2)(b), 47)",
            "the BCR",
            ("46(2)(b)", "47"),
            covers="approved Binding Corporate Rules (Art. 47) cover",
        ),
        Safeguard(
            "public_bodies_instrument",
            "a legally binding and enforceable instrument between public authorities or bodies (Art. 46(2)(a))",
            "the instrument",
            ("46(2)(a)",),
            unverifiable="the instrument",
            confirm="that a legally binding and enforceable instrument between public authorities or bodies covers it",
            covers="a legally binding and enforceable instrument between public authorities or bodies covers",
        ),
        Safeguard(
            "sa_standard_clauses",
            "standard data protection clauses adopted by a supervisory authority and approved by the "
            "Commission (Art. 46(2)(d))",
            "the clauses",
            ("46(2)(d)",),
            unverifiable="the adoption or the approval of the clauses",
            confirm=(
                "that a supervisory authority adopted the clauses and the Commission approved them "
                "pursuant to the examination procedure referred to in Art. 93(2)"
            ),
            covers="standard data protection clauses adopted by a supervisory authority and approved by the Commission cover",
        ),
        Safeguard(
            "code_of_conduct",
            "an approved code of conduct with binding and enforceable commitments of the importer "
            "(Art. 46(2)(e), 40(3))",
            "the code of conduct",
            ("46(2)(e)", "40(3)"),
            unverifiable="the approval of the code or the importer's commitments",
            confirm=(
                "that the code is approved under Art. 40(5) and has general validity under Art. 40(9), and "
                "that the importer has made binding and enforceable commitments, via contractual or other "
                "legally binding instruments, to apply the appropriate safeguards, including with regard to "
                "the rights of data subjects (Art. 40(3))"
            ),
            covers="an approved code of conduct, with the importer's binding and enforceable commitments, covers",
        ),
        Safeguard(
            "certification",
            "an approved certification mechanism with binding and enforceable commitments of the importer "
            "(Art. 46(2)(f), 42(2))",
            "the certification",
            ("46(2)(f)", "42(2)"),
            unverifiable="the approval of the certification mechanism or the importer's commitments",
            confirm=(
                "that the certification mechanism, seal or mark is approved under Art. 42(5), and that the "
                "importer has made binding and enforceable commitments, via contractual or other legally "
                "binding instruments, to apply the appropriate safeguards, including with regard to the "
                "rights of data subjects (Art. 42(2))"
            ),
            covers="an approved certification mechanism, with the importer's binding and enforceable commitments, covers",
        ),
        Safeguard(
            "authorised_clauses",
            "contractual clauses authorised by the competent supervisory authority (Art. 46(3)(a))",
            "the authorised clauses",
            ("46(3)(a)",),
            unverifiable="the authorisation",
            confirm=(
                "that the competent supervisory authority authorised the clauses (Art. 46(3)), or that an "
                "authorisation given on the basis of Article 26(2) of Directive 95/46/EC remains valid "
                "(Art. 46(5))"
            ),
            covers="contractual clauses authorised by the competent supervisory authority cover",
        ),
        Safeguard(
            "administrative_arrangement",
            "provisions in administrative arrangements between public authorities or bodies, authorised by "
            "the competent supervisory authority (Art. 46(3)(b))",
            "the administrative arrangement",
            ("46(3)(b)",),
            unverifiable="the authorisation",
            confirm=(
                "that the competent supervisory authority authorised the provisions (Art. 46(3)), that the "
                "arrangement is between public authorities or bodies and that the provisions include "
                "enforceable and effective data subject rights"
            ),
            covers="provisions in an administrative arrangement authorised by the competent supervisory authority cover",
        ),
    )
}

# Every value the input may record as a transfer mechanism, in the order the docs list them: "none"
# for a recorded absence, then the Art. 45, Art. 46 and Art. 49 bases.
TRANSFER_MECHANISMS = ("none", "adequacy", *SAFEGUARDS, "dpf", "derogation_art49")
VALID_TRANSFER_MECHANISMS = set(TRANSFER_MECHANISMS) - {"none"}

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

SUBPROCESSOR_TRANSFER_PREFIX = "transfer.subprocessor."


def subprocessor_rule_id(name: Any) -> str:
    """The rule id of a sub-processor's transfer finding, derived from its name.

    The rules, the fact mapping (facts.py), the evidence graph (transfer_graph.py) and the input
    contract (contract.py) must all derive it here, or a name with punctuation gives the graph a
    rule id the packet never emits and a blocked transfer renders as passed.

    The name is put in Unicode normalisation form NFC, so its decomposed and its composed spelling
    ("u" followed by the combining mark U+0308, or "ü") give one id. It is then put in lower case
    and in NFC again, because a few letters have a composed form only in lower case ("T" followed by
    U+0308 lowers to "t" and the mark, which compose into "ẗ"), so an accent NFC can compose stays
    part of its letter. Letters and digits of every script are then kept, so "Müller Inc",
    "Múller Inc" and "Möller Inc", composed or decomposed, or two names written in Chinese, get
    distinct ids. Each space becomes "_", and every other run of characters that are not letters,
    digits or "_" becomes one "_", so "Support Tools, LLC." gives "support_tools__llc". Only letters
    and digits are sure to keep names apart: where one symbol, or one combining mark NFC cannot
    compose into a letter, stands in for another ("Acme™"/"Acme®", "q" followed by U+0308 or by
    U+0303), the names share an id, and a symbol, mark or extra space that only one name has changes
    only the underscores ("Acme™ Inc" gives "acme__inc", "Acme Inc" "acme_inc"). The input contract
    compares names without any of these, so it refuses both kinds of pair, as it refuses any two
    names that would share an id and a name that would give an empty one. A caller that skips it
    (build_packet without validate) gets two findings with one id, which the fact mapping and the
    evidence graph cannot tell apart (the graph attaches the finding that comes first in the packet
    to both entries).
    """
    name = unicodedata.normalize("NFC", unicodedata.normalize("NFC", str(name)).lower())
    return SUBPROCESSOR_TRANSFER_PREFIX + re.sub(r"\W+", "_", name.replace(" ", "_")).strip("_")


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


# Strings that read as an answer to a yes/no question rather than as a description.
_YES_NO_WORDS = {"true", "false", "yes", "no"}


def _described(dpa: dict, path: str) -> bool:
    """A part of the processing description, given as a description or as `true`.

    A non-empty description counts as stated; `false`, an empty string, null or an omitted
    value counts as not stated. A string such as "false" is refused rather than read as a
    description, and so is any other type.
    """
    value = _get(dpa, path)
    if value is None or isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        if value.strip().lower() in _YES_NO_WORDS:
            raise InvalidInputError(
                f"{path} must be a description or true/false, got {value!r}; record yes/no as a JSON boolean."
            )
        return bool(value.strip())
    raise InvalidInputError(f"{path} must be a description (a string) or true/false, got {value!r}.")


def _text(value: Any, field: str) -> str | None:
    """A recorded word or phrase, or None when the input does not say."""
    if value is None or isinstance(value, str):
        return value
    raise InvalidInputError(f"{field} must be a string, got {value!r}.")


def recorded_text(dpa: dict, path: str) -> str | None:
    """The string at a dotted path, or None when it is omitted or null."""
    return _text(_get(dpa, path), path)


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


def subprocessors(dpa: dict) -> list[dict]:
    """The sub-processor entries; an omitted or null list means none."""
    return _objects(dpa, "subprocessors")


def subprocessor_text(sp: dict, index: int, key: str) -> str | None:
    """A string field of a sub-processor entry, or None when it is omitted or null."""
    return _text(sp.get(key), f"subprocessors[{index}].{key}")


def subprocessor_name(sp: dict, index: int) -> str:
    """The sub-processor's name, or its position in the list when it has none."""
    return subprocessor_text(sp, index, "name") or f"Sub-processor {index + 1}"


def subprocessor_country(sp: dict, index: int) -> str:
    """The sub-processor's country as an upper-case code, or "" when none is recorded."""
    return (subprocessor_text(sp, index, "country") or "").upper()


def transfer_destinations(dpa: dict) -> list[str]:
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
        present = _described(dpa, f"processing.{key}")
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
    auth = recorded_text(dpa, path) or "none"
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
    timing = (recorded_text(dpa, "breach_notification.timing") or "").lower()
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
    not say whether that type of data is transferred. A finding that the DPF may carry (PRESENT,
    or NEEDS_REVIEW on the data covered) ends with DPF_STATUS_NOTE.
    """
    basis = f"the EU-US Data Privacy Framework adequacy decision (Art. 45(1); {DPF_DECISION})"
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
    if includes_hr_data is False and includes_non_hr_data is False:
        # Every personal datum is HR or non-HR data, so the input contradicts itself.
        return (
            "NEEDS_REVIEW",
            "MEDIUM",
            (
                f"Transfer to {country} relies on {basis}; the importer is recorded as certified on the "
                "Data Privacy Framework List, but the DPA records that neither non-HR data nor HR data "
                "is transferred, so the data the certification must cover is unclear. Confirm the data "
                f"transferred and that the certification covers it. {DPF_STATUS_NOTE}"
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
                f"Confirm the data the certification covers. {DPF_STATUS_NOTE}"
            ),
        )
    return (
        "PRESENT",
        "LOW",
        (
            f"Transfer to {country} relies on {basis}; the importer is recorded as actively certified "
            "on the Data Privacy Framework List for the data transferred. As an Art. 45 basis it needs "
            f"no transfer impact assessment; re-check the listing before relying on it. {DPF_STATUS_NOTE}"
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


def _mechanism(mechanism: str | None) -> str:
    """A recorded transfer mechanism in lower case, or "none" when none is recorded."""
    return (mechanism or "none").lower()


def _impact_assessment_status(recorded: bool) -> str:
    return "A transfer impact assessment is recorded" if recorded else "The input records no transfer impact assessment"


def _assess_adequate_destination(
    decision: AdequacyDecision, mech: str, impact_assessment_recorded: bool
) -> tuple[str, str, str] | None:
    """A destination with its own adequacy decision, or None for a mechanism handled elsewhere.

    Art. 45(1): a transfer on an adequacy decision needs no specific authorisation, and Art. 46(1)
    makes Art. 46 safeguards the basis only in the absence of such a decision. A safeguard recorded
    for a destination whose decision has no scope limit is therefore not needed for Chapter V. Where
    the decision covers only some recipients, processing or purposes, the tool cannot tell from the
    input whether the importer is covered, so the finding asks exactly that, and the severity is the
    one the safeguard path would give if the importer is not covered: MEDIUM while no transfer impact
    assessment is recorded, LOW once one is.
    """
    country = decision.country
    has_decision = f"{country} benefits from an adequacy decision ({decision.basis})."
    scope = f" {decision.scope_limit}" if decision.limited else ""
    if mech in {"none", "adequacy"}:
        confirm = " Confirm that the importer is within it." if decision.limited else ""
        return ("PRESENT", "LOW", has_decision + scope + confirm)
    if mech in _ADEQUACY_REDUNDANT:
        return (
            "NEEDS_REVIEW",
            "LOW",
            (
                f"{has_decision}{scope} The transfer is recorded as relying on {_ADEQUACY_REDUNDANT[mech]}. "
                "Confirm the basis relied on and record the adequacy decision."
            ),
        )
    safeguard = SAFEGUARDS.get(mech)
    if safeguard is None:
        return None
    recorded = f"The transfer is recorded as relying on {safeguard.label}."
    if not decision.limited:
        return (
            "PRESENT",
            "LOW",
            (
                f"{country} benefits from an adequacy decision ({decision.basis}), and its Article 1 sets "
                f"no limit on the recipients or the purposes it covers. {recorded} The adequacy decision "
                "covers the transfer, so Chapter V needs no Art. 46 safeguard and no transfer impact "
                f"assessment for it; {safeguard.short} may still serve other purposes."
            ),
        )
    return (
        "NEEDS_REVIEW",
        "LOW" if impact_assessment_recorded else "MEDIUM",
        (
            f"{has_decision}{scope} {recorded} The input does not record whether the importer is within "
            "the decision's scope. If it is, the decision covers the transfer and Chapter V needs no "
            "Art. 46 safeguard and no transfer impact assessment for it. If it is not, the transfer relies "
            f"on {safeguard.short}: confirm {safeguard.confirm}, and record a transfer impact assessment "
            f"and any supplementary measures ({SUPPLEMENTARY_MEASURES}). "
            f"{_impact_assessment_status(impact_assessment_recorded)}."
        ),
    )


def _assess_safeguard(country: str, safeguard: Safeguard) -> tuple[str, str, str]:
    """An Art. 46 safeguard for a third country with no adequacy decision on the tool's list."""
    if safeguard.unverifiable:
        detail = (
            f"Transfer to {country} relies on {safeguard.label}. The tool cannot verify "
            f"{safeguard.unverifiable}: confirm {safeguard.confirm}, and record a transfer impact "
            f"assessment and any supplementary measures ({SUPPLEMENTARY_MEASURES})."
        )
    else:
        detail = (
            f"Transfer to {country} relies on {safeguard.label}; confirm {safeguard.confirm}, a transfer "
            f"impact assessment and any supplementary measures ({SUPPLEMENTARY_MEASURES})."
        )
    if country == DPF_COUNTRY:
        detail += (
            f" {DPF_DECISION} covers only organisations on the Data Privacy Framework List: if the "
            "importer is certified there for the data transferred, record the mechanism as dpf, and "
            "Chapter V needs no Art. 46 safeguard and no transfer impact assessment for the transfer."
        )
    return ("NEEDS_REVIEW", "LOW", detail)


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
    impact_assessment_recorded: bool = False,
) -> tuple[str, str, str]:
    """Return (status, severity, detail) for a single destination country.

    The `dpf_*` keywords describe the importer's entry on the Data Privacy Framework List:
    an active certification, and whether it covers HR and non-HR data. The `includes_*`
    keywords say whether the DPA transfers HR and non-HR data (None means it does not say).
    `occasional_and_not_repetitive` is the recorded nature of a derogation-based transfer.
    `impact_assessment_recorded` is read only for an Art. 46 safeguard recorded for a destination
    whose adequacy decision has a scope limit.
    """
    country = (country or "").upper()
    mech = _mechanism(mechanism)
    if country in EEA:
        return ("PRESENT", "INFO", f"{country} is within the EEA; no Chapter V transfer mechanism required.")
    if country in ADEQUACY:
        assessed = _assess_adequate_destination(ADEQUACY[country], mech, impact_assessment_recorded)
        if assessed is not None:
            return assessed
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
            detail += (
                f" The list was checked against the decisions on EUR-Lex on {ADEQUACY_VERIFIED_ON}; "
                "confirm whether a later adequacy decision covers it."
            )
        return ("MISSING", "HIGH", detail)
    if mech != "none" and mech not in VALID_TRANSFER_MECHANISMS:
        return (
            "MISSING",
            "HIGH",
            (
                f"Transfer to {country} is recorded as relying on '{mechanism}', which is not a Chapter V "
                f"basis this tool recognises ({', '.join(TRANSFER_MECHANISMS[1:-1])} or "
                f"{TRANSFER_MECHANISMS[-1]}); no Art. 45 adequacy decision, Art. 46 safeguard or Art. 49 "
                "derogation is recorded."
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
    if mech in SAFEGUARDS:
        return _assess_safeguard(country, SAFEGUARDS[mech])
    return (
        "MISSING",
        "HIGH",
        (
            f"Transfer to {country} has no recorded Chapter V basis: no Art. 45 adequacy decision "
            "(including the EU-US Data Privacy Framework), Art. 46 safeguard or Art. 49 derogation "
            "is recorded."
        ),
    )


def relies_on_art46_safeguard(country: str, mechanism: str | None) -> bool:
    """Whether a transfer relies on an Art. 46 safeguard, so that a transfer impact assessment is due.

    A destination inside the EEA is not a Chapter V transfer (Art. 44 covers transfers to a third
    country or an international organisation), and Art. 46(1) makes the safeguards the basis only
    in the absence of an adequacy decision, so a safeguard recorded for either is not relied on here.
    For a destination whose decision has a scope limit, the transfer finding itself asks whether the
    importer is covered and, if not, for the assessment (scope_question_reads_impact_assessment).
    """
    country = country.upper()
    return country not in EEA and country not in ADEQUACY and _mechanism(mechanism) in SAFEGUARDS


def scope_question_reads_impact_assessment(country: str, mechanism: str | None) -> bool:
    """Whether the transfer finding reads `transfers.transfer_impact_assessment`.

    It does for an Art. 46 safeguard recorded for a destination whose adequacy decision has a
    scope limit: the finding states whether an assessment is recorded and takes its severity
    from that.
    """
    decision = ADEQUACY.get(country.upper())
    return bool(decision and decision.limited and _mechanism(mechanism) in SAFEGUARDS)


def _cite(articles: tuple[str, ...], documents: tuple[str, ...] = ()) -> str:
    return "Art. " + ", ".join(articles) + "".join(f"; {document}" for document in documents)


def _transfer_articles(country: str, mechanism: str | None) -> str:
    """Chapter V provisions behind a transfer finding, for its citation."""
    mech = _mechanism(mechanism)
    country = country.upper()
    if country in EEA:
        return "Art. 44-46"  # no Chapter V transfer; the recorded mechanism is not relied on
    decision = ADEQUACY.get(country)
    safeguard = SAFEGUARDS.get(mech)
    if decision and (mech in {"none", "adequacy"} or mech in _ADEQUACY_REDUNDANT or safeguard):
        if safeguard and decision.limited:
            return _cite(
                ("44", *decision.articles, *safeguard.articles),
                (*decision.documents, *safeguard.documents, SUPPLEMENTARY_MEASURES),
            )
        return _cite(("44", *decision.articles), decision.documents)
    if mech == "dpf":
        return _cite(("44", "45(1)"), (DPF_DECISION,))
    if mech == "derogation_art49":
        return f"Art. 44, 49; {ART49_GUIDELINES}"
    if safeguard:
        return _cite(("44", *safeguard.articles), safeguard.documents)
    return "Art. 44-46"


def _transfer_remediation(
    country: str,
    mechanism: str | None,
    occasional_and_not_repetitive: bool,
    importer: str | None = None,
) -> str:
    """What to record or confirm for an open transfer finding.

    `importer` names a sub-processor; a direct transfer is described by its country alone.
    The same defect gets the same remediation in either place.
    """
    mech = _mechanism(mechanism)
    country = country.upper()
    where = f"{importer} in {country}" if importer else country
    transfer = f"the transfer to {importer}" if importer else "the transfer"
    certification = f"the active certification of {importer}" if importer else "the importer's active certification"
    decision = ADEQUACY.get(country)
    safeguard = SAFEGUARDS.get(mech)
    if decision and mech in _ADEQUACY_REDUNDANT:
        return f"Record reliance on the Art. 45 adequacy decision for {country} as the basis for {transfer}."
    if decision and decision.limited and safeguard:
        who = importer or f"the importer in {country}"
        return (
            f"Confirm whether {who} is within the scope of Article 1 of {decision.act}. If it is, record "
            f"the mechanism as adequacy; if not, confirm that {safeguard.covers} the transfer to {where}, "
            f"with a transfer impact assessment and any supplementary measures ({SUPPLEMENTARY_MEASURES})."
        )
    if mech == "adequacy" and not decision:
        if country == DPF_COUNTRY:
            return (
                f"Record the mechanism for {where} as dpf, with {certification} on the Data Privacy "
                "Framework List and the data it covers, or record an Art. 46 safeguard."
            )
        return (
            f"Confirm that a current Commission adequacy decision covers {country} (the tool's adequacy "
            f"list was checked against EUR-Lex on {ADEQUACY_VERIFIED_ON}), or record an Art. 46 safeguard "
            f"for {where}."
        )
    if mech == "dpf":
        return (
            f"Record {certification} on the Data Privacy Framework List and the data it covers "
            "(non-HR data, and HR data if HR data is transferred), or another Chapter V basis for "
            f"{where}."
        )
    if mech == "derogation_art49" and occasional_and_not_repetitive:
        return f"Record which Art. 49(1) derogation applies to the transfer to {where} and how its conditions are met."
    if mech == "derogation_art49":
        return (
            f"Record an Art. 45 adequacy basis or an Art. 46 safeguard for {where}, or record that "
            "the transfer is occasional and not repetitive and which Art. 49(1) derogation applies."
        )
    if safeguard:
        return (
            f"Confirm that {safeguard.covers} the transfer to {where}, with a transfer impact assessment "
            f"and any supplementary measures ({SUPPLEMENTARY_MEASURES})."
        )
    return f"Record an Art. 45 adequacy basis or an Art. 46 safeguard for {where}."


def check_transfers(dpa: dict) -> list[Finding]:
    findings: list[Finding] = []
    destinations = transfer_destinations(dpa)
    mechanisms = transfer_mechanisms(dpa)
    entries = subprocessors(dpa)
    dpf_certified = _country_flags(dpa, "transfers.dpf_certified")
    dpf_covers_hr_data = _country_flags(dpa, "transfers.dpf_covers_hr_data")
    dpf_covers_non_hr_data = _country_flags(dpa, "transfers.dpf_covers_non_hr_data")
    occasional = _country_flags(dpa, "transfers.occasional_and_not_repetitive")
    tia = _recorded(dpa, "transfers.transfer_impact_assessment")
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
            impact_assessment_recorded=tia,
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
    for index, sp in enumerate(entries):
        for key in ("name", "country", "transfer_mechanism"):
            subprocessor_text(sp, index, key)
        flags = {
            key: bool(_flag(sp.get(key), f"subprocessors[{index}].{key}"))
            for key in (
                "dpf_certified",
                "dpf_covers_hr_data",
                "dpf_covers_non_hr_data",
                "occasional_and_not_repetitive",
            )
        }
        country = subprocessor_country(sp, index)
        name = subprocessor_name(sp, index)
        if country and country not in EEA:
            status, severity, detail = assess_transfer(
                country,
                sp.get("transfer_mechanism"),
                **flags,
                includes_hr_data=includes_hr_data,
                includes_non_hr_data=includes_non_hr_data,
                impact_assessment_recorded=tia,
            )
            findings.append(
                Finding(
                    rule_id=subprocessor_rule_id(name),
                    title=f"Sub-processor transfer: {name} ({country})",
                    citation="GDPR Art. 28(4) / " + _transfer_articles(country, sp.get("transfer_mechanism")),
                    severity=severity,
                    status=status,
                    detail=f"{name} processes data in {country}. {detail}",
                    remediation=(
                        "" if status == "PRESENT"
                        else _transfer_remediation(
                            country,
                            sp.get("transfer_mechanism"),
                            flags["occasional_and_not_repetitive"],
                            importer=name,
                        )
                    ),
                )
            )

    # Transfer impact assessment (Schrems II): required where an Art. 46 safeguard is relied on for a
    # transfer to a third country with no adequacy decision on the tool's list. DPF transfers rely on
    # an Art. 45 adequacy decision and therefore do not trigger it; a safeguard recorded for a
    # destination with a scope-limited adequacy decision is asked about in its own transfer finding.
    relies_on_safeguards = any(
        relies_on_art46_safeguard(c, mechanisms.get(c)) for c in destinations
    ) or any(
        relies_on_art46_safeguard(subprocessor_country(sp, i), sp.get("transfer_mechanism"))
        for i, sp in enumerate(entries)
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
            citation="Cal. Civ. Code §§ 1798.140(ag), 1798.100(d) (CCPA, as amended by the CPRA)",
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
