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
from datetime import date
from typing import Any, Callable, Mapping

# --- Reference data (kept small, explicit, and citeable) ---------------------

# EEA member states (data transfers within the EEA are not "third country" transfers).
EEA = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES",
    "SE", "IS", "LI", "NO",
}


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _day(text: str) -> date:
    """A date as the Official Journal writes it, such as "26 January 2026"."""
    day, month, year = text.split()
    return date(int(year), _MONTHS.index(month) + 1, int(day))


# Whether a decision covers the importer, judged from the facts the input records about it.
COVERED = "COVERED"
NOT_COVERED = "NOT_COVERED"
UNRESOLVED = "UNRESOLVED"

# How a decision stood on the review date.
IN_FORCE = "IN_FORCE"
NOT_YET_APPLICABLE = "NOT_YET_APPLICABLE"
EXPIRED = "EXPIRED"
EARLIER_VERSION = "EARLIER_VERSION"

# The kinds of importer `recipient_type` records, and the values of `scope_carve_out`.
RECIPIENT_TYPES = ("private_commercial", "public_body", "non_profit")
SCOPE_CARVE_OUT_VALUES = ("none", "applies")
# The facts about an importer that the scope conditions of a decision read: per destination under
# `transfers`, or on a sub-processor entry. Each is optional, and an omitted or null fact leaves the
# condition it decides unresolved.
RECIPIENT_FACTS = ("recipient_type", "scope_carve_out", "automated_processing")

# Interpretation, adopted as the owner's answer of 10 November 2026 ("adoption dates, with a note").
ADOPTION_DATE_NOTE = (
    "the decision sets no date from which it applies; it is addressed to the Member States and takes effect "
    "on notification, which its Official Journal text does not date, so the tool reads it as applying from "
    "its date of adoption"
)
AMENDMENT_DATE_NOTE = (
    "an amending act that sets no date from which it applies takes effect on notification, which its "
    "Official Journal text does not date, so the tool dates the amendment by its adoption"
)


@dataclass(frozen=True)
class Condition:
    """One scope condition a decision's operative part sets, read from a recorded fact about the importer.

    `fact` is one of RECIPIENT_FACTS. A recorded value in `covered` meets the condition, one in
    `not_covered` fails it, and anything else, an omitted or null fact included, leaves it unresolved:
    an unresolved condition never counts as adequacy. `interpretation` states a reading of the decision
    that maps the input's categories onto its text; a finding the condition decides repeats it.
    """

    fact: str
    covered: frozenset
    not_covered: frozenset
    pinpoint: str
    requirement: str
    interpretation: str = ""


@dataclass(frozen=True)
class Amendment:
    """An act that changed a decision's scope or validity, dated by its adoption (ADOPTION_DATE_NOTE)."""

    act: str
    adopted: str
    celex: str
    effect: str  # what it changed, completing "which ..."


@dataclass(frozen=True)
class AdequacyDecision:
    """A Commission adequacy decision for one third country or international organisation, as its
    Official Journal text (snapshotted under sources/oj) states it.

    `scope_limit` restates the limit the decision's operative part sets on what it covers: the
    recipients, the processing or the purposes. It is empty when Article 1 covers personal data
    transferred from the Union without such a limit. `conditions` model that limit as facts the input
    records about the importer; a decision with a scope limit and no conditions (Brazil, the Faroe
    Islands) is read as covering every importer, a reading `scope_reading` states, and a finding that
    relies on it asks the reviewer to confirm the limit. `directive_era` marks a decision adopted under
    Article 25(6) of Directive 95/46/EC, which stays in force under Art. 45(9) GDPR until amended,
    replaced or repealed. `amending_acts` are the acts its citation names; `amended` says what they
    changed, for the reference table in docs/rules.md; `amendments` are the acts that changed its scope
    or validity, which a review date before them turns into a review state. `expires` is the date the
    decision itself sets for its expiry, read as its last day of validity, and `applies_from` the date it
    sets for its application (`applies_from_source` names the article). Dates are written as the
    Official Journal writes them. `international_organisation` describes a destination that is an
    international organisation rather than a country; its code is not an ISO country code.
    """

    country: str  # ISO 3166-1 alpha-2 code, or "EPO" for the European Patent Organisation
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
    provision: str = "Art. 1"  # the operative provision a citation names
    conditions: tuple[Condition, ...] = ()
    scope_reading: str = ""
    amendments: tuple[Amendment, ...] = ()
    applies_from: str = ""
    applies_from_source: str = ""
    international_organisation: str = ""

    @property
    def limited(self) -> bool:
        return bool(self.scope_limit)

    @property
    def articles(self) -> tuple[str, ...]:
        """The GDPR provisions a transfer on this decision rests on."""
        return ("45(1)", "45(9)") if self.directive_era else ("45(1)",)

    @property
    def documents(self) -> tuple[str, ...]:
        """The acts a finding that relies on this decision cites, the decision with its operative provision."""
        return (f"{self.act}, {self.provision}", *self.amending_acts)

    @property
    def basis(self) -> str:
        """The decision as a finding names it."""
        text = f"Art. 45(1); {self.act} of {self.adopted}, {self.provision}"
        if self.amending_acts:
            text += ", as last amended by " + " and ".join(self.amending_acts)
        if self.directive_era:
            text += ", in force under Art. 45(9)"
        if self.expires:
            text += f", which expires on {self.expires}"
        return text

    @property
    def start(self) -> str:
        """The first day the tool reads the decision as applying."""
        return self.applies_from or self.adopted

    @property
    def start_note(self) -> str:
        if self.applies_from:
            return f"{self.applies_from_source} of the decision says that it applies from {self.applies_from}."
        return f"Interpretation: {ADOPTION_DATE_NOTE}."

    @property
    def expiry_note(self) -> str:
        return (
            f"Interpretation: the decision says that it shall expire on {self.expires}; the tool reads that "
            "day as its last day of validity."
        )

    def standing(self, review_date: date | None) -> tuple[str, str]:
        """How the decision stood on the review date, and why when it did not stand as modelled.

        Without a review date the decision is read as it stands in this table. Before its start date
        or after its expiry it does not apply. Before an amending act that changed its scope or validity
        it stood in an earlier version, which the table does not model.
        """
        if review_date is None:
            return IN_FORCE, ""
        on = f"on the review date, {review_date.isoformat()}"
        if review_date < _day(self.start):
            start = (
                f"{self.applies_from_source} says that it applies from {self.start}"
                if self.applies_from
                else f"the tool reads it as applying from {self.start}"
            )
            return NOT_YET_APPLICABLE, f"{on}, it did not yet apply: {start}"
        if self.expires and review_date > _day(self.expires):
            return EXPIRED, f"{on}, it had expired: the tool reads {self.expires} as its last day of validity"
        for amendment in self.amendments:
            if review_date < _day(amendment.adopted):
                return EARLIER_VERSION, (
                    f"{on}, it stood before {amendment.act} of {amendment.adopted}, which {amendment.effect}, "
                    "and the tool models only the decision as last amended"
                )
        return IN_FORCE, ""

    def evaluate(self, facts: Mapping[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        """(outcome, reasons, interpretations) for an importer with these recorded facts.

        A failed condition makes the outcome NOT_COVERED, whatever the others record; otherwise an
        unresolved one makes it UNRESOLVED. The reasons and interpretations are those of the conditions
        that decided the outcome. A decision without conditions covers every importer.
        """
        met: list[Condition] = []
        failed: list[Condition] = []
        unresolved: list[Condition] = []
        for condition in self.conditions:
            value = facts.get(condition.fact)
            if isinstance(value, (str, bool)) and value in condition.covered:
                met.append(condition)
            elif isinstance(value, (str, bool)) and value in condition.not_covered:
                failed.append(condition)
            else:
                unresolved.append(condition)
        if failed:
            outcome, decisive = NOT_COVERED, failed
        elif unresolved:
            outcome, decisive = UNRESOLVED, unresolved
        else:
            outcome, decisive = COVERED, met
        reasons = tuple(
            f"under {c.pinpoint}, {c.requirement} ({_recorded_as(c.fact, facts.get(c.fact))})" for c in decisive
        )
        return outcome, reasons, tuple(c.interpretation for c in decisive if c.interpretation)


def _recorded_as(fact: str, value: Any) -> str:
    """What the input records for a fact, in the words of the input."""
    if value is None:
        return f"{fact} not recorded"
    if isinstance(value, bool):
        return f"recorded: {fact} {'true' if value else 'false'}"
    return f'recorded: {fact} "{value}"'


# The date every entry below was last read against the decision's record on EUR-Lex: the operative
# part (Article 1 and, for Israel, Article 2), the date of adoption, the OJ reference, and the
# EUR-Lex record of the act's status (in force; an end of validity only for the United Kingdom). The
# amending acts were read too: Implementing Decision (EU) 2016/2295 replaced the articles on suspending
# data flows and on monitoring in each decision adopted under Directive 95/46/EC and left Article 1
# unchanged; the Isle of Man corrigendum (OJ L 208, 10.6.2004, p. 47) restates the same Article 1. The
# EUR-Lex record of the Israel decision lists one corrigendum (CELEX 32011D0061R(01)), for the Hungarian
# text only. The Uruguay decision's title refers to automated processing, but its Article 1 sets no such
# limit, so the entry has none.
ADEQUACY_VERIFIED_ON = "2026-11-10"

# The date the table was last checked as a whole: every Official Journal text it rests on (sources/oj)
# re-fetched and found byte-identical, and the Publications Office's Cellar searched for later adequacy
# acts (sources/manifest.json, "recheck"). A review date after it gets a note that later acts are not
# reflected, and `dpa-review-table-age` reports how old it is.
TABLE_AS_OF = "2026-11-14"

# The reading of Article 1 of the Canadian decision through its recital 5 (owner's answer of
# 10 November 2026: private-sector scope; a non-profit goes to review).
_CANADA_RECIPIENTS = (
    "recital 5 says that the Act applies to private sector organisations acting in the course of "
    "commercial activities, not to organisations under the Federal Privacy Act or regulated by the public "
    "sector at a provincial level, nor to non-profit organisations and charitable activities unless they "
    "are of a commercial nature; the tool reads a private commercial organisation as covered, a public body "
    "as not covered and a non-profit as unresolved, and does not model the exemptions for organisations "
    "under substantially similar provincial laws (recital 6)."
)
_JAPAN_RECIPIENTS = (
    "recital 32 excludes the government and administrative agencies at central and local level from the "
    "definition of a personal information handling business operator, and recital 33 reads 'business' to "
    "include not-for-profit activities; the tool reads a private commercial organisation and a non-profit "
    "as business operators and a public body as not covered."
)

# Third countries and international organisations with a Commission adequacy decision (Art. 45),
# keyed by ISO code ("EPO" for the European Patent Organisation). The EU-US Data Privacy Framework
# decision is DPF_ADEQUACY below: it covers only listed organisations, so a US transfer relies on it
# through the dpf mechanism and the US is not on this list.
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
            scope_reading=(
                "the input records no fact for this limit, and the tool reads every importer in Brazil as "
                "a controller or processor subject to the LGPD, public or private (recitals 25 and 26); the "
                "exemptions from the LGPD the decision describes from recital 30 are not modelled"
            ),
        ),
        AdequacyDecision(
            "CA", "Canada", "Commission Decision 2002/2/EC", "20 December 2001",
            "OJ L 2, 4.1.2002, p. 13", "32002D0002", directive_era=True,
            scope_limit=(
                "Its Article 1 covers only personal data transferred to recipients subject to the "
                "Personal Information Protection and Electronic Documents Act."
            ),
            conditions=(
                Condition(
                    "recipient_type",
                    covered=frozenset({"private_commercial"}),
                    not_covered=frozenset({"public_body"}),
                    pinpoint="Art. 1 and recital 5",
                    requirement=(
                        "the importer must be subject to the Personal Information Protection and Electronic "
                        "Documents Act"
                    ),
                    interpretation=_CANADA_RECIPIENTS,
                ),
            ),
        ),
        AdequacyDecision(
            "CH", "Switzerland", "Commission Decision 2000/518/EC", "26 July 2000",
            "OJ L 215, 25.8.2000, p. 1", "32000D0518", directive_era=True,
        ),
        AdequacyDecision(
            "EPO", "European Patent Organisation", "Commission Implementing Decision (EU) 2025/1382",
            "15 July 2025", "OJ L, 2025/1382, 18.7.2025", "32025D1382",
            international_organisation=(
                "The European Patent Organisation is an international organisation with its seat in Munich "
                "(recital 7 of the decision)"
            ),
        ),
        AdequacyDecision(
            "FO", "Faroe Islands", "Commission Decision 2010/146/EU", "5 March 2010",
            "OJ L 58, 9.3.2010, p. 17", "32010D0146", directive_era=True,
            scope_limit=(
                "Its Article 1 covers only personal data transferred to recipients subject to the Act on "
                "Processing of Personal Data (the Faeroese Act)."
            ),
            scope_reading=(
                "the input records no fact for this limit, and the tool reads every recipient in the Faroe "
                "Islands as subject to the Faeroese Act"
            ),
            applies_from="15 June 2010",
            applies_from_source="Article 7",
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
            provision="Art. 1(1)",
            amendments=(
                Amendment(
                    "Commission Implementing Decision (EU) 2025/1226", "24 June 2025", "32025D1226",
                    "moved its expiry from 27 June 2025 to 27 December 2025",
                ),
                Amendment(
                    "Commission Implementing Decision (EU) 2025/2574", "19 December 2025", "32025D2574",
                    "repealed its Article 1(2), the exclusion of data transferred for purposes of United "
                    "Kingdom immigration control, and moved its expiry to 27 December 2031",
                ),
            ),
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
            provision="Art. 1(1)",
            conditions=(
                Condition(
                    "automated_processing",
                    covered=frozenset({True}),
                    not_covered=frozenset({False}),
                    pinpoint="Art. 1(1)",
                    requirement=(
                        "the transfer must be automated or, where it is not, the data must be subject to "
                        "further automated processing in the State of Israel"
                    ),
                ),
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
            conditions=(
                Condition(
                    "recipient_type",
                    covered=frozenset({"private_commercial", "non_profit"}),
                    not_covered=frozenset({"public_body"}),
                    pinpoint="Art. 1(1) and recitals 32 and 33",
                    requirement=(
                        "the importer must be a personal information handling business operator subject to "
                        "the Act on the Protection of Personal Information"
                    ),
                    interpretation=_JAPAN_RECIPIENTS,
                ),
                Condition(
                    "scope_carve_out",
                    covered=frozenset({"none"}),
                    not_covered=frozenset({"applies"}),
                    pinpoint="Art. 1(2)",
                    requirement=(
                        "the importer must fall within none of the categories of Art. 1(2)(a) to (e) (press "
                        "organisations, persons engaged in professional writing, academic organisations, "
                        "religious bodies and political bodies, each to the extent of the purposes listed "
                        "there)"
                    ),
                ),
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
            conditions=(
                Condition(
                    "scope_carve_out",
                    covered=frozenset({"none"}),
                    not_covered=frozenset({"applies"}),
                    pinpoint="Art. 1(2)",
                    requirement=(
                        "the importer must fall within none of the categories of Art. 1(2)(a) to (c) (religious "
                        "organisations for their missionary activities, political parties for the "
                        "nomination of candidates, and entities overseen by the Financial Services "
                        "Commission for personal credit information under the Credit Information Act)"
                    ),
                ),
            ),
        ),
        AdequacyDecision(
            "NZ", "New Zealand", "Commission Implementing Decision 2013/65/EU", "19 December 2012",
            "OJ L 28, 30.1.2013, p. 12", "32013D0065", directive_era=True, provision="Art. 1(1)",
        ),
        AdequacyDecision(
            "UY", "Uruguay", "Commission Implementing Decision 2012/484/EU", "21 August 2012",
            "OJ L 227, 23.8.2012, p. 11", "32012D0484", directive_era=True, provision="Art. 1(1)",
            scope_reading=(
                "the decision's title refers to automated processing of personal data, but its Article 1(1) "
                "sets no such limit, and the tool follows Article 1(1)"
            ),
        ),
    )
}

# Destinations that are international organisations rather than countries. A transfer to one is a
# Chapter V transfer (Art. 44) even where its seat is in the EEA, so the EEA exemption never applies.
INTERNATIONAL_ORGANISATIONS = frozenset(
    code for code, decision in ADEQUACY.items() if decision.international_organisation
)

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
    "Re-check the status of Commission Implementing Decision (EU) 2023/1795: the "
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

def table_age(today: date) -> dict[str, Any]:
    """How old the adequacy table is on `today`. The caller reads the clock, never the rules."""
    as_of = date.fromisoformat(TABLE_AS_OF)
    return {
        "table_as_of": TABLE_AS_OF,
        "today": today.isoformat(),
        "age_days": (today - as_of).days,
        "decisions": len(ADEQUACY) + 1,  # the DPF decision is DPF_ADEQUACY, off the list
    }


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_review_date(value: Any, field: str = "review_date") -> date | None:
    """The review date as a date, or None when it is omitted or null; anything but YYYY-MM-DD is refused."""
    if value is None:
        return None
    if isinstance(value, str) and _ISO_DATE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise InvalidInputError(f"{field} must be a calendar date written as YYYY-MM-DD, got {value!r}.")


def recorded_review_date(dpa: dict) -> date | None:
    """The date the input asks the transfers to be assessed on (`review_date`), or None."""
    return parse_review_date(_get(dpa, "review_date"))


def _recipient_fact(value: Any, field: str) -> str | bool | None:
    """A recorded fact about an importer: a word in lower case, a JSON boolean, or None when not recorded."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower()
    raise InvalidInputError(f"{field} must be a string or true/false, got {value!r}.")


def destination_facts(dpa: dict, country: str) -> dict[str, Any]:
    """The facts recorded about the importer at a direct destination (`transfers.<fact>.<COUNTRY>`)."""
    country = country.upper()
    return {
        fact: _by_country(dpa, f"transfers.{fact}", _recipient_fact, '{"CA": "private_commercial"}').get(country)
        for fact in RECIPIENT_FACTS
    }


def subprocessor_facts(sp: dict, index: int) -> dict[str, Any]:
    """The facts recorded about a sub-processor as an importer."""
    return {fact: _recipient_fact(sp.get(fact), f"subprocessors[{index}].{fact}") for fact in RECIPIENT_FACTS}


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
    not say whether that type of data is transferred. A coverage the input leaves open is an
    unknown adequacy condition, NEEDS_REVIEW with HIGH severity like any other (owner's answer of
    10 November 2026). A finding that the DPF may carry (PRESENT, or NEEDS_REVIEW on the data
    covered) ends with DPF_STATUS_NOTE.
    """
    basis = f"the EU-US Data Privacy Framework adequacy decision (Art. 45(1); {DPF_DECISION}, Art. 1)"
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
            "HIGH",
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
            "HIGH",
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


@dataclass(frozen=True)
class _Route:
    """Which Chapter V path a transfer takes, and what decided it.

    kind is one of: eea; adequacy (the destination's decision, judged by its conditions); lapsed (its
    decision did not apply on the review date); earlier_version (the review date falls before an
    amendment); version_question (the same, with an Art. 46 safeguard recorded); redundant (dpf or a
    derogation recorded for an importer the decision covers); covered_safeguard (a safeguard recorded
    for an importer the decision covers); scope_question (a safeguard recorded where the tool cannot
    tell whether the decision covers the importer); outside_scope (a safeguard recorded for an importer
    the decision does not cover); unlisted_adequacy; unrecognised; dpf; derogation; safeguard; none.
    """

    kind: str
    decision: AdequacyDecision | None = None
    reason: str = ""
    outcome: str = ""
    reasons: tuple[str, ...] = ()
    interpretations: tuple[str, ...] = ()


def _route(country: str, mechanism: str | None, facts: Mapping[str, Any], on: date | None) -> _Route:
    """The Chapter V path for a transfer to `country` on `mechanism`, assessed on the review date `on`.

    A decision that did not apply on the review date counts as no decision, except where the transfer is
    recorded as relying on adequacy: then the finding says why the decision does not carry it.
    """
    country = country.upper()
    mech = _mechanism(mechanism)
    if country in EEA:
        return _Route("eea")
    decision = ADEQUACY.get(country)
    if decision is not None:
        standing, reason = decision.standing(on)
        if standing in {NOT_YET_APPLICABLE, EXPIRED}:
            if mech in {"none", "adequacy"}:
                return _Route("lapsed", decision, reason)
        elif standing == EARLIER_VERSION:
            kind = "version_question" if mech in SAFEGUARDS else "earlier_version"
            return _Route(kind, decision, reason)
        else:
            outcome, reasons, interpretations = decision.evaluate(facts)
            found = dict(decision=decision, outcome=outcome, reasons=reasons, interpretations=interpretations)
            if mech in {"none", "adequacy"}:
                return _Route("adequacy", **found)
            if mech in _ADEQUACY_REDUNDANT and outcome == COVERED:
                return _Route("redundant", **found)
            if mech in SAFEGUARDS:
                if decision.limited and not decision.conditions:
                    return _Route("scope_question", **found)
                kind = {COVERED: "covered_safeguard", NOT_COVERED: "outside_scope"}.get(outcome, "scope_question")
                return _Route(kind, **found)
            # dpf or a derogation recorded for an importer the decision may not cover: those paths decide.
    if country == DPF_COUNTRY:
        standing, reason = DPF_ADEQUACY.standing(on)
        dpf_applies = standing == IN_FORCE
        if mech in SAFEGUARDS and dpf_applies:
            return _Route("scope_question", DPF_ADEQUACY)
        if mech == "dpf" and not dpf_applies:
            return _Route("lapsed", DPF_ADEQUACY, reason)
    if mech == "adequacy":
        return _Route("unlisted_adequacy")
    if mech != "none" and mech not in VALID_TRANSFER_MECHANISMS:
        return _Route("unrecognised")
    if mech == "dpf":
        return _Route("dpf", DPF_ADEQUACY if country == DPF_COUNTRY else None)
    if mech == "derogation_art49":
        return _Route("derogation")
    if mech in SAFEGUARDS:
        return _Route("safeguard")
    return _Route("none")


def _destination(decision: AdequacyDecision) -> str:
    """How a finding introduces the destination of a decision."""
    if decision.international_organisation:
        return (
            f"{decision.international_organisation}. A transfer to it is a transfer to an international "
            "organisation under Chapter V (Art. 44), so the EEA exemption does not apply. "
            f"{decision.country}"
        )
    return decision.country


def _interpretations(route: _Route) -> list[str]:
    """The readings behind the conditions that decided the route, and the entry's own reading of its scope."""
    notes = [f"Interpretation: {text}" for text in route.interpretations]
    decision = route.decision
    if decision is not None and decision.scope_reading and route.outcome == COVERED and route.kind != "scope_question":
        notes.append(f"Interpretation: {decision.scope_reading}.")
    return notes


def _date_notes(decision: AdequacyDecision, on: date | None) -> list[str]:
    """What a finding says about the review date: the date readings it turned on, and the table's age."""
    if on is None:
        return []
    notes: list[str] = []
    if on == _day(decision.start):
        notes.append(decision.start_note)
    if decision.expires and on == _day(decision.expires):
        notes.append(decision.expiry_note)
    if on > date.fromisoformat(TABLE_AS_OF):
        notes.append(f"The adequacy table was last checked on {TABLE_AS_OF}, so later Commission acts are not reflected.")
    return notes


def _sentences(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def _assess_adequate_destination(route: _Route, mech: str, impact_assessment_recorded: bool, on: date | None) -> tuple[str, str, str]:
    """A destination whose own adequacy decision applied on the review date (or with no review date).

    Art. 45(1): a transfer on an adequacy decision needs no specific authorisation, and Art. 46(1)
    makes Art. 46 safeguards the basis only in the absence of such a decision. Where the decision covers
    only some importers, the facts the input records about the importer decide: a failed condition means
    the decision does not cover it, and an unresolved condition never counts as adequacy (NEEDS_REVIEW,
    HIGH, on the owner's answer of 10 November 2026). With a safeguard recorded, the safeguard carries a
    transfer the decision does not cover, so the finding takes the severity the safeguard path would
    give: MEDIUM while no transfer impact assessment is recorded, LOW once one is.
    """
    decision = route.decision
    assert decision is not None
    has_decision = f"{_destination(decision)} benefits from an adequacy decision ({decision.basis})."
    scope = decision.scope_limit
    reasons = "; ".join(route.reasons)
    notes = _sentences(*_interpretations(route), *_date_notes(decision, on))
    if route.kind == "adequacy":
        if route.outcome == NOT_COVERED:
            return (
                "MISSING",
                "HIGH",
                _sentences(
                    has_decision, scope, f"It does not cover this importer: {reasons}.",
                    "No Art. 46 safeguard or Art. 49 derogation is recorded for this transfer.", notes,
                ),
            )
        if route.outcome == UNRESOLVED:
            return (
                "NEEDS_REVIEW",
                "HIGH",
                _sentences(
                    has_decision, scope, f"Whether it covers this importer is unresolved: {reasons}.",
                    "An unresolved condition never counts as adequacy.", notes,
                ),
            )
        met = f"Conditions met: {reasons}." if decision.conditions else ""
        confirm = "Confirm that the importer is within it." if decision.limited and not decision.conditions else ""
        return ("PRESENT", "LOW", _sentences(has_decision, scope, met, confirm, notes))
    if route.kind == "redundant":
        met = f"Conditions met: {reasons}." if decision.conditions else ""
        return (
            "NEEDS_REVIEW",
            "LOW",
            _sentences(
                has_decision, scope, met,
                f"The transfer is recorded as relying on {_ADEQUACY_REDUNDANT[mech]}. Confirm the basis "
                "relied on and record the adequacy decision.",
                notes,
            ),
        )
    safeguard = SAFEGUARDS[mech]
    recorded = f"The transfer is recorded as relying on {safeguard.label}."
    not_needed = (
        "The adequacy decision covers the transfer, so Chapter V needs no Art. 46 safeguard and no transfer "
        f"impact assessment for it; {safeguard.short} may still serve other purposes."
    )
    if route.kind == "covered_safeguard" and not decision.limited:
        return (
            "PRESENT",
            "LOW",
            _sentences(
                f"{_destination(decision)} benefits from an adequacy decision ({decision.basis}), and its "
                "Article 1 sets no limit on the recipients or the purposes it covers.",
                recorded, not_needed, notes,
            ),
        )
    if route.kind == "covered_safeguard":
        return ("PRESENT", "LOW", _sentences(has_decision, scope, f"Conditions met: {reasons}.", recorded, not_needed, notes))
    if route.kind == "outside_scope":
        return (
            "NEEDS_REVIEW",
            "LOW" if impact_assessment_recorded else "MEDIUM",
            _sentences(
                has_decision, scope, f"It does not cover this importer: {reasons}.", recorded,
                f"The transfer therefore relies on {safeguard.short}: confirm {safeguard.confirm}, and record a "
                f"transfer impact assessment and any supplementary measures ({SUPPLEMENTARY_MEASURES}).",
                f"{_impact_assessment_status(impact_assessment_recorded)}.", notes,
            ),
        )
    status, severity, detail = _scope_question(decision, safeguard, impact_assessment_recorded, route.reasons)
    return (status, severity, _sentences(detail, notes))


def _scope_question(
    decision: AdequacyDecision,
    safeguard: Safeguard,
    impact_assessment_recorded: bool,
    unresolved: tuple[str, ...] = (),
) -> tuple[str, str, str]:
    """An Art. 46 safeguard recorded for a destination whose adequacy decision covers only some importers.

    The tool cannot tell from the input whether the importer is within the decision's scope, so the
    finding asks exactly that: if it is, the decision covers the transfer (Art. 45(1)) and Art. 46(1)
    leaves no room for the safeguard as the Chapter V basis; if not, the safeguard carries the transfer
    and needs a transfer impact assessment. The severity is the one the safeguard path would give if the
    importer is not covered: MEDIUM while no transfer impact assessment is recorded, LOW once one is.
    For the United States the decision is the DPF decision, which covers only organisations on the Data
    Privacy Framework List; the input records such a certification only for the dpf mechanism.
    `unresolved` names the conditions the input leaves open, for a decision the tool models them for.
    """
    country = decision.country
    recorded = f"The transfer is recorded as relying on {safeguard.label}."
    if decision is DPF_ADEQUACY:
        opening = f"An adequacy decision covers some importers in {country} ({decision.basis})."
        unknown = (
            "The input records a certification on that list only for the dpf mechanism, so it does not "
            "record whether the importer is within the decision's scope."
        )
        covered = (
            "If it is, with a certification that covers the data transferred, the decision covers the "
            "transfer: record the mechanism as dpf, and Chapter V needs no Art. 46 safeguard and no transfer "
            "impact assessment for it."
        )
        note = f" {DPF_STATUS_NOTE}"
    else:
        opening = f"{_destination(decision)} benefits from an adequacy decision ({decision.basis})."
        unknown = "The input does not record whether the importer is within the decision's scope."
        if unresolved:
            unknown = unknown[:-1] + ": " + "; ".join(unresolved) + "."
        covered = (
            "If it is, the decision covers the transfer and Chapter V needs no Art. 46 safeguard and no "
            "transfer impact assessment for it."
        )
        note = ""
    return (
        "NEEDS_REVIEW",
        "LOW" if impact_assessment_recorded else "MEDIUM",
        (
            f"{opening} {decision.scope_limit} {recorded} {unknown} {covered} If it is not, the transfer "
            f"relies on {safeguard.short}: confirm {safeguard.confirm}, and record a transfer impact "
            f"assessment and any supplementary measures ({SUPPLEMENTARY_MEASURES}). "
            f"{_impact_assessment_status(impact_assessment_recorded)}.{note}"
        ),
    )


def _assess_safeguard(country: str, safeguard: Safeguard) -> tuple[str, str, str]:
    """An Art. 46 safeguard for a third country with no adequacy decision at all (not even the DPF's)."""
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
    recipient: Mapping[str, Any] | None = None,
    review_date: str | date | None = None,
) -> tuple[str, str, str]:
    """Return (status, severity, detail) for a single destination country.

    The `dpf_*` keywords describe the importer's entry on the Data Privacy Framework List:
    an active certification, and whether it covers HR and non-HR data. The `includes_*`
    keywords say whether the DPA transfers HR and non-HR data (None means it does not say).
    `occasional_and_not_repetitive` is the recorded nature of a derogation-based transfer.
    `impact_assessment_recorded` is read where an Art. 46 safeguard is recorded for a destination whose
    adequacy decision may not cover the importer, the United States (the DPF decision) included.
    `recipient` holds the facts recorded about the importer (RECIPIENT_FACTS), which a decision's scope
    conditions read; `review_date` (YYYY-MM-DD) is the date the decisions are read on.
    """
    country = (country or "").upper()
    mech = _mechanism(mechanism)
    on = review_date if isinstance(review_date, date) or review_date is None else parse_review_date(review_date)
    route = _route(country, mechanism, recipient or {}, on)
    if route.kind == "eea":
        return ("PRESENT", "INFO", f"{country} is within the EEA; no Chapter V transfer mechanism required.")
    if route.kind in {"adequacy", "redundant", "covered_safeguard", "outside_scope"} or (
        route.kind == "scope_question" and route.decision is not DPF_ADEQUACY
    ):
        return _assess_adequate_destination(route, mech, impact_assessment_recorded, on)
    if route.kind == "scope_question":
        return _scope_question(DPF_ADEQUACY, SAFEGUARDS[mech], impact_assessment_recorded)
    if route.kind in {"lapsed", "earlier_version", "version_question"}:
        return _assess_out_of_date(route, mech, impact_assessment_recorded, on)
    if route.kind == "unlisted_adequacy":
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
                f" The list was last checked for later decisions on {TABLE_AS_OF}; confirm whether a later "
                "adequacy decision covers it."
            )
        return ("MISSING", "HIGH", detail)
    if route.kind == "unrecognised":
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
    if route.kind == "dpf":
        return _assess_dpf(
            country,
            certified=dpf_certified,
            covers_hr_data=dpf_covers_hr_data,
            covers_non_hr_data=dpf_covers_non_hr_data,
            includes_hr_data=includes_hr_data,
            includes_non_hr_data=includes_non_hr_data,
        )
    if route.kind == "derogation":
        return _assess_derogation(country, occasional_and_not_repetitive)
    if route.kind == "safeguard":
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


def _assess_out_of_date(route: _Route, mech: str, impact_assessment_recorded: bool, on: date | None) -> tuple[str, str, str]:
    """A destination whose decision did not stand on the review date as the table models it.

    Before its start date or after its expiry the decision does not apply, so a transfer recorded as
    relying on it has no basis (MISSING, HIGH). Before an amendment that changed its scope or validity
    the decision stood in a version the table does not model, so the transfer goes to review (owner's
    answer of 10 November 2026): HIGH, because whether it was adequate then is unknown, unless an Art. 46
    safeguard is recorded, which would carry the transfer if the decision did not.
    """
    decision = route.decision
    assert decision is not None
    name = _destination(decision)
    if route.kind == "lapsed":
        if "did not yet apply" in route.reason:
            date_note = "" if decision.applies_from else decision.start_note
        else:
            date_note = decision.expiry_note
        if decision is DPF_ADEQUACY:
            opening = f"Transfer to {decision.country} is recorded as relying on the EU-US Data Privacy Framework adequacy decision ({decision.basis})"
        else:
            opening = f"{name} has an adequacy decision ({decision.basis})"
        return (
            "MISSING",
            "HIGH",
            _sentences(
                f"{opening}, but {route.reason}.", date_note,
                "No other Chapter V basis is recorded for this transfer.",
            ),
        )
    opening = f"{name} has an adequacy decision ({decision.basis}), but {route.reason}."
    if route.kind == "earlier_version":
        return (
            "NEEDS_REVIEW",
            "HIGH",
            _sentences(
                opening,
                "Confirm that the decision as it stood on that date covered the transfer; until then the "
                "transfer has no confirmed basis.",
                f"Interpretation: {AMENDMENT_DATE_NOTE}.",
            ),
        )
    safeguard = SAFEGUARDS[mech]
    return (
        "NEEDS_REVIEW",
        "LOW" if impact_assessment_recorded else "MEDIUM",
        _sentences(
            opening,
            f"The transfer is recorded as relying on {safeguard.label}. If the decision as it stood on that "
            "date covered the transfer, Chapter V needed no Art. 46 safeguard and no transfer impact "
            f"assessment for it. If it did not, the transfer relies on {safeguard.short}: confirm "
            f"{safeguard.confirm}, and record a transfer impact assessment and any supplementary measures "
            f"({SUPPLEMENTARY_MEASURES}).",
            f"{_impact_assessment_status(impact_assessment_recorded)}.",
            f"Interpretation: {AMENDMENT_DATE_NOTE}.",
        ),
    )


def relies_on_art46_safeguard(
    country: str,
    mechanism: str | None,
    recipient: Mapping[str, Any] | None = None,
    review_date: date | None = None,
) -> bool:
    """Whether a transfer relies on an Art. 46 safeguard, so that rule transfer.impact_assessment is due.

    A destination inside the EEA is not a Chapter V transfer (Art. 44 covers transfers to a third
    country or an international organisation), and Art. 46(1) makes the safeguards the basis only
    in the absence of an adequacy decision, so a safeguard recorded for either is not relied on here.
    Where the destination's decision may not cover the importer, the United States included, the
    transfer finding itself asks for the assessment (scope_question_reads_impact_assessment). A decision
    that did not apply on the review date counts as no decision.
    """
    return _route(country, mechanism, recipient or {}, review_date).kind == "safeguard"


# Routes whose finding reads `transfers.transfer_impact_assessment` itself.
_READS_IMPACT_ASSESSMENT = {"scope_question", "outside_scope", "version_question"}


def scope_question_reads_impact_assessment(
    country: str,
    mechanism: str | None,
    recipient: Mapping[str, Any] | None = None,
    review_date: date | None = None,
) -> bool:
    """Whether the transfer finding reads `transfers.transfer_impact_assessment`.

    It does for an Art. 46 safeguard recorded for a destination whose adequacy decision may not cover the
    importer, the United States and its DPF decision included, or stood in an earlier version on the
    review date: the finding states whether an assessment is recorded and takes its severity from that.
    """
    return _route(country, mechanism, recipient or {}, review_date).kind in _READS_IMPACT_ASSESSMENT


def _cite(articles: tuple[str, ...], documents: tuple[str, ...] = ()) -> str:
    return "Art. " + ", ".join(articles) + "".join(f"; {document}" for document in documents)


def _transfer_articles(
    country: str,
    mechanism: str | None,
    recipient: Mapping[str, Any] | None = None,
    review_date: date | None = None,
) -> str:
    """Chapter V provisions behind a transfer finding, for its citation."""
    route = _route(country, mechanism, recipient or {}, review_date)
    decision = route.decision
    safeguard = SAFEGUARDS.get(_mechanism(mechanism))
    if route.kind == "eea":
        return "Art. 44-46"  # no Chapter V transfer; the recorded mechanism is not relied on
    if route.kind in _READS_IMPACT_ASSESSMENT:
        assert decision is not None and safeguard is not None
        return _cite(
            ("44", *decision.articles, *safeguard.articles),
            (*decision.documents, *safeguard.documents, SUPPLEMENTARY_MEASURES),
        )
    if decision is not None and route.kind in {"adequacy", "lapsed", "earlier_version", "redundant", "covered_safeguard"}:
        return _cite(("44", *decision.articles), decision.documents)
    if route.kind == "dpf":
        return _cite(("44", "45(1)"), DPF_ADEQUACY.documents)
    if route.kind == "derogation":
        return f"Art. 44, 49; {ART49_GUIDELINES}"
    if route.kind == "safeguard":
        assert safeguard is not None
        return _cite(("44", *safeguard.articles), safeguard.documents)
    return "Art. 44-46"


def _fact_names(route: _Route) -> str:
    """The facts a decision's unresolved conditions read, for a remediation."""
    assert route.decision is not None
    names = [c.fact for c in route.decision.conditions if c.fact in " ".join(route.reasons)]
    return " and ".join(dict.fromkeys(names))


def _transfer_remediation(
    country: str,
    mechanism: str | None,
    occasional_and_not_repetitive: bool,
    importer: str | None = None,
    recipient: Mapping[str, Any] | None = None,
    review_date: date | None = None,
) -> str:
    """What to record or confirm for an open transfer finding.

    `importer` names a sub-processor; a direct transfer is described by its country alone.
    The same defect gets the same remediation in either place.
    """
    mech = _mechanism(mechanism)
    country = country.upper()
    route = _route(country, mechanism, recipient or {}, review_date)
    decision = route.decision
    where = f"{importer} in {country}" if importer else country
    transfer = f"the transfer to {importer}" if importer else "the transfer"
    who = importer or f"the importer in {country}"
    certification = f"the active certification of {importer}" if importer else "the importer's active certification"
    safeguard = SAFEGUARDS.get(mech)
    tia = f"with a transfer impact assessment and any supplementary measures ({SUPPLEMENTARY_MEASURES})"
    if route.kind == "redundant":
        return f"Record reliance on the Art. 45 adequacy decision for {country} as the basis for {transfer}."
    if route.kind == "adequacy" and decision is not None:
        if route.outcome == NOT_COVERED:
            return (
                f"{decision.act} does not cover {who} as recorded: record an Art. 46 safeguard for {where}, "
                "or correct the recorded facts."
            )
        return (
            f"Confirm whether {who} is within the scope of Article 1 of {decision.act} ({_fact_names(route)} "
            f"decides it), or record an Art. 46 safeguard for {where}."
        )
    if route.kind == "lapsed" and decision is not None:
        return (
            f"{decision.act} did not apply on the review date: record another Chapter V basis for {where}, or "
            "check the review date."
        )
    if route.kind == "earlier_version" and decision is not None:
        return (
            f"Confirm that {decision.act}, as it stood on the review date, covered {transfer}, or record an "
            f"Art. 46 safeguard for {where}."
        )
    if route.kind == "version_question" and decision is not None and safeguard is not None:
        return (
            f"Confirm whether {decision.act}, as it stood on the review date, covered {transfer}; if not, "
            f"confirm that {safeguard.covers} the transfer to {where}, {tia}."
        )
    if route.kind == "outside_scope" and safeguard is not None:
        return f"Confirm that {safeguard.covers} the transfer to {where}, {tia}."
    if route.kind == "scope_question" and decision is not None and safeguard is not None:
        if decision is DPF_ADEQUACY:
            covered = (
                f"Confirm whether {who} is within the scope of Article 1 of {decision.act}: on the Data "
                "Privacy Framework List, with a certification that covers the data transferred. If it is, "
                "record the mechanism as dpf with that certification"
            )
        elif decision.conditions:
            covered = (
                f"Confirm whether {who} is within the scope of Article 1 of {decision.act}, and record "
                f"{_fact_names(route)}. If it is, record the mechanism as adequacy"
            )
        else:
            covered = (
                f"Confirm whether {who} is within the scope of Article 1 of {decision.act}. If it is, record "
                "the mechanism as adequacy"
            )
        return f"{covered}; if not, confirm that {safeguard.covers} the transfer to {where}, {tia}."
    if route.kind == "unlisted_adequacy":
        if country == DPF_COUNTRY:
            return (
                f"Record the mechanism for {where} as dpf, with {certification} on the Data Privacy "
                "Framework List and the data it covers, or record an Art. 46 safeguard."
            )
        return (
            f"Confirm that a current Commission adequacy decision covers {country} (the tool's adequacy "
            f"list was last checked for later decisions on {TABLE_AS_OF}), or record an Art. 46 safeguard "
            f"for {where}."
        )
    if route.kind == "dpf" or (route.kind == "lapsed" and mech == "dpf"):
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
        return f"Confirm that {safeguard.covers} the transfer to {where}, {tia}."
    return f"Record an Art. 45 adequacy basis or an Art. 46 safeguard for {where}."


def check_transfers(dpa: dict) -> list[Finding]:
    findings: list[Finding] = []
    destinations = transfer_destinations(dpa)
    mechanisms = transfer_mechanisms(dpa)
    entries = subprocessors(dpa)
    on = recorded_review_date(dpa)
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

    relies_on_safeguards = False
    for country in destinations:
        is_occasional = bool(occasional.get(country))
        facts = destination_facts(dpa, country)
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
            recipient=facts,
            review_date=on,
        )
        relies_on_safeguards |= relies_on_art46_safeguard(country, mechanisms.get(country), facts, on)
        findings.append(
            Finding(
                rule_id=f"transfer.{str(country).lower()}",
                title=f"International transfer to {country}",
                citation="GDPR " + _transfer_articles(str(country), mechanisms.get(country), facts, on),
                severity=severity,
                status=status,
                detail=detail,
                remediation=(
                    "" if status == "PRESENT"
                    else _transfer_remediation(
                        country, mechanisms.get(country), is_occasional, recipient=facts, review_date=on
                    )
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
        facts = subprocessor_facts(sp, index)
        country = subprocessor_country(sp, index)
        name = subprocessor_name(sp, index)
        if country and country not in EEA:
            mechanism = sp.get("transfer_mechanism")
            status, severity, detail = assess_transfer(
                country,
                mechanism,
                **flags,
                includes_hr_data=includes_hr_data,
                includes_non_hr_data=includes_non_hr_data,
                impact_assessment_recorded=tia,
                recipient=facts,
                review_date=on,
            )
            relies_on_safeguards |= relies_on_art46_safeguard(country, mechanism, facts, on)
            findings.append(
                Finding(
                    rule_id=subprocessor_rule_id(name),
                    title=f"Sub-processor transfer: {name} ({country})",
                    citation="GDPR Art. 28(4) / " + _transfer_articles(country, mechanism, facts, on),
                    severity=severity,
                    status=status,
                    detail=f"{name} processes data in {country}. {detail}",
                    remediation=(
                        "" if status == "PRESENT"
                        else _transfer_remediation(
                            country,
                            mechanism,
                            flags["occasional_and_not_repetitive"],
                            importer=name,
                            recipient=facts,
                            review_date=on,
                        )
                    ),
                )
            )

    # Transfer impact assessment (Schrems II): required where an Art. 46 safeguard is relied on for a
    # transfer to a third country with no adequacy decision (or none that applied on the review date).
    # DPF transfers rely on an Art. 45 adequacy decision and therefore do not trigger it; a safeguard
    # recorded for a destination whose decision may not cover the importer (the United States and its
    # DPF decision included) is asked about in its own transfer finding, which reads the recorded
    # assessment.
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
