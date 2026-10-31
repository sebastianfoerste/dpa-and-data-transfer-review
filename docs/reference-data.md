# Reference data: the EEA and adequacy lists

Last checked: **2026-10-31** (`REFERENCE_DATA_AS_OF` in [`src/dpa_review/checks.py`](../src/dpa_review/checks.py)).

The transfer rules read two sets in `checks.py`: `EEA` (30 codes) and `ADEQUACY` (15 codes). This page records the decision behind each entry, what was checked against which official source on the date above, and what the code does not model. The lists are illustrative: check them again before relying on a result. A citation correction is the most valuable contribution to this repository ([CONTRIBUTING.md](../CONTRIBUTING.md)).

## Adequacy decisions (GDPR Art. 45), as the European Commission lists them

Source: European Commission, "Data protection adequacy for non-EU countries", <https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/adequacy-decisions_en>, opened 2026-10-31. Decision references are those the page links to (CELEX numbers in the link targets).

| Code | Country or territory | Decision | In `ADEQUACY` | Scope and status notes |
| --- | --- | --- | --- | --- |
| AD | Andorra | Decision 2010/625/EU (CELEX 32010D0625) | yes | |
| AR | Argentina | Decision 2003/490/EC (CELEX 32003D0490) | yes | |
| BR | Brazil | Commission Implementing Decision of 26 January 2026, C(2026) 373 final; the Commission page lists it as adopted 27 January 2026 | **yes, added 2026-10-31** | Adopted under Art. 45(3). Art. 1: controllers and processors in Brazil subject to the General Data Protection Law (LGPD). Art. 3(4): first evaluation after four years. The Official Journal citation (EU) 2026/179 appears in the EUR-Lex listing title only: not verified. |
| CA | Canada | Decision 2002/2/EC (CELEX 32002D0002) | yes | Commercial organisations only (PIPEDA). The code does not model this limit. |
| CH | Switzerland | Decision 2000/518/EC (CELEX 32000D0518) | yes | |
| FO | Faroe Islands | Decision 2010/146/EU (CELEX 32010D0146) | yes | |
| GB | United Kingdom | Implementing Decision (EU) 2021/1772, amended by the Commission Implementing Decision of 19 December 2025, C(2025) 8771 final | yes | The amending decision repeals the old Art. 1(2) and replaces Art. 4: "This Decision shall expire on 27 December 2031, unless extended in accordance with the procedure referred to in Article 93(2)". A separate decision of the same day renews the Law Enforcement Directive finding (out of scope here). OJ citation (EU) 2025/2574 from the EUR-Lex listing only: not verified. |
| GG | Guernsey | Decision 2003/821/EC (CELEX 32003D0821) | yes | |
| IL | Israel | Decision 2011/61/EU (CELEX 32011D0061) | yes | |
| IM | Isle of Man | Decision 2004/411/EC (CELEX 32004D0411) | yes | |
| JE | Jersey | Decision 2008/393/EC (CELEX 32008D0393) | yes | |
| JP | Japan | Decision published in OJ L 76, 2019, p. 1 | yes | |
| KR | Republic of Korea | Decision of 17 December 2021 (the page gives no number) | yes | The Commission's first review was concluded on 23 July 2026 (Commission page). |
| NZ | New Zealand | Decision 2013/65/EU (CELEX 32013D0065) | yes | |
| US | United States | Implementing Decision (EU) 2023/1795 of 10 July 2023 (EU-US Data Privacy Framework) | **no** | Covers only organisations certified under the DPF, so it is not a country-level entry. The input records such an importer with the mechanism `dpf`. See "Known gaps". |
| UY | Uruguay | Decision 2012/484/EU (CELEX 32012D0484) | yes | |
| n/a | European Patent Organisation | Decision of 15 July 2025 | n/a | An international organisation, not a country code; not modelled. |

## EEA

`EEA` holds the 27 EU member states plus Iceland, Liechtenstein and Norway (EEA Agreement, Annex XI as amended to cover the GDPR). Transfers inside the EEA are not Chapter V transfers. Not re-verified on 2026-10-31; the membership has not changed since the list was written.

## What was verified on 2026-10-31, and how

| Source | Result |
| --- | --- |
| Commission adequacy page (link above) | Opened. Lists the 16 countries and territories and the European Patent Organisation in the table above. |
| Commission text of the Brazil decision, C(2026) 373 final, <https://commission.europa.eu/document/download/5e457271-4292-4b47-bb10-b6b6cb6700e1_en> | Opened (PDF, 57 pages). Title, legal basis (Art. 45(3)), Art. 1 and Art. 3(4) read from the text. |
| Commission press release IP/26/229 of 27 January 2026 (mutual EU-Brazil adequacy decisions) | Opened (PDF). Confirms adoption and the four-year review. |
| Commission text of the UK renewal, C(2025) 8771 final, <https://commission.europa.eu/document/download/b36eedab-43b8-46eb-ac30-a8d1e6e69f51_en> | Opened (PDF, 39 pages). Title, amended decision, new Art. 4 (expiry 27 December 2031) read from the text. |
| EUR-Lex (ELI pages, CELEX HTML and OJ PDF endpoints for 2026/179, 2025/2574, 2023/1795 and the consolidated GDPR) | **Not opened**: every request returned HTTP 202 with an empty body (a bot challenge). Official Journal numbers above are therefore taken from EUR-Lex search listing titles and marked "not verified". |
| GDPR Art. 28(2), 28(3)(a)-(h), 28(4), 33(2), 44-49 | The citations the rules carry are structural and unchanged since 2016; the consolidated text was not re-read today because EUR-Lex was unreachable. |
| Cal. Civ. Code §§ 1798.140(ag), 1798.100(d) (CCPA/CPRA citation of rule `ccpa.service_provider_terms`) | **Not verified**: leginfo.legislature.ca.gov returned HTTP 403. |

## Known gaps the code does not model (owner decisions)

- **DPF label and TIA.** `assess_transfer` labels `dpf` "an approved certification / framework (Art. 46)" and the packet asks for a transfer impact assessment. Decision (EU) 2023/1795 is an Art. 45 adequacy decision limited to certified importers. Draft PR #4 changes this; the reference data here leaves it alone.
- **Partial-scope decisions.** Canada (commercial organisations), the United States (certified importers) and, in its own terms, Brazil (entities subject to the LGPD) are adequate only within the scope of the decision. The code treats a country code as adequate or not; the reviewer confirms scope.
- **Art. 49 derogations.** The input cannot say whether a transfer is occasional; a derogation goes to review (MEDIUM). Draft PR #4 tightens this.
- **International organisations** (the European Patent Organisation) have no country code and are not modelled.
- **Other Art. 46 instruments** (codes of conduct, certifications, ad hoc clauses under Art. 46(3)) are not modelled; a transfer that relies on one reads as having no recorded safeguard.

## How to update the lists

1. Change `EEA` or `ADEQUACY` in `src/dpa_review/checks.py` with a one-line comment naming the decision and its date, and set `REFERENCE_DATA_AS_OF` to the date of the check.
2. Update the table above and the verification log.
3. Run `make docs` (the rule catalogue prints the lists and the date) and `make test`. A changed review state for a fixture must be recorded in `tests/fixtures/expected.json` with a `legal_review_note`, and needs a lawyer's sign-off, not a test edited to pass.
