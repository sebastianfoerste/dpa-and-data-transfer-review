# Chapter V decisions

PR #4 left four legal questions for the owner. The owner delegated them. This page records each
decision, what the tool now does, and the source text it rests on. Every source in sections 1 to 4 was
read on EUR-Lex on 2026-11-10. The tests that pin each decision are in
[`tests/test_transfer_bases.py`](../tests/test_transfer_bases.py); the conformance fixtures 10, 13, 14
and 15 run them through the CLI ([conformance.md](conformance.md)). Section 5 records the scope
conditions, dates and the European Patent Organisation, on the answers given on 10 November 2026 for
the legal review of 14 October; its sources are the Official Journal snapshots in
[`sources/oj`](../sources/oj), and its tests are in [`tests/test_adequacy.py`](../tests/test_adequacy.py),
with fixtures 02 and 16 to 21.

## 1. Brazil and the adequacy list

**Decision.** Brazil is on the adequacy list under Commission Implementing Decision (EU) 2026/179 of
26 January 2026 (OJ L, 2026/179, 28.1.2026; CELEX 32026D0179). Its Article 1 finds an adequate level of
protection "for personal data transferred from the European Union to controllers and processors in
Brazil subject to the General Data Protection Law (LGPD)". The decision has no entry-into-force article;
Article 4 addresses it to the Member States, and EUR-Lex records 26 January 2026 as its date of
notification and of effect, with no end date.

Every other entry was read against its decision too: the operative part, the date, the Official Journal
reference and the EUR-Lex record of status and amendments. One entry had changed. The United Kingdom
decision (Implementing Decision (EU) 2021/1772) was due to expire on 27 June 2025. Implementing Decision
(EU) 2025/1226 extended it to 27 December 2025, and Implementing Decision (EU) 2025/2574 of 19 December
2025 repealed its Article 1(2), which excluded data transferred for United Kingdom immigration control,
and extended it to 27 December 2031. The table in [rules.md](rules.md#reference-data) lists every entry.

Adequacy recorded for a country off the list stays a missing basis (`HIGH`). The list is now dated and
sourced, so a country off it had no decision on that date.

Commission Implementing Decision (EU) 2025/1382 of 15 July 2025 finds an adequate level of protection for
the European Patent Organisation, an international organisation. Section 5 adds it to the list.

## 2. A safeguard recorded for a destination with an adequacy decision

**Decision.** Art. 45(1) GDPR lets a transfer take place on an adequacy decision without any specific
authorisation, and Art. 46(1) makes Art. 46 safeguards the basis only "in the absence of a decision
pursuant to Article 45(3)". The tool asks for a transfer impact assessment on the Art. 46 path, as it did
before (CJEU C-311/18; EDPB Recommendations 01/2020). It therefore no longer asks for one for every
safeguard recorded for an adequate destination:

- **The decision sets no scope limit** (Andorra, Argentina, Guernsey, the Isle of Man, Jersey, New
  Zealand, Switzerland, the United Kingdom, Uruguay): the transfer is `PRESENT`. The finding says that the
  decision covers it, that Chapter V needs no Art. 46 safeguard and no transfer impact assessment for it,
  and that the safeguard may still serve other purposes.
- **The decision covers only some importers or processing** (Brazil: controllers and processors subject
  to the LGPD; Canada: recipients subject to PIPEDA; the Faroe Islands: recipients subject to the Faeroese
  Act; Israel: automated transfers, or data subject to further automated processing in Israel; Japan:
  business operators subject to the APPI with the Supplementary Rules, without the press, writing,
  academic, religious and political exclusions of Article 1(2); Korea: entities subject to PIPA with the
  additional safeguards, without the exclusions of Article 1(2)): the transfer goes to `NEEDS_REVIEW`.
  The finding states the limit and asks whether the importer is within it. If it is, the decision covers
  the transfer; if not, the safeguard carries it and needs a transfer impact assessment. The finding is
  `MEDIUM` while no assessment is recorded and `LOW` once one is, the severity the safeguard path would
  give. It replaces the generic `transfer.impact_assessment` finding for that transfer.
- **The United States** has a decision that covers only some importers: Article 1 of Implementing
  Decision (EU) 2023/1795 covers organisations on the Data Privacy Framework List. A safeguard recorded
  for a US importer therefore gets the same scope question: if the importer is certified on that list,
  with a certification that covers the data transferred, record the mechanism as `dpf` and the decision
  covers the transfer; if it is not, the safeguard carries the transfer and needs a transfer impact
  assessment (`MEDIUM` until one is recorded, then `LOW`). The finding also carries the status note of
  section 3.

A finding that relies on a decision cites Art. 45(1) and the decision. A decision adopted under Article
25(6) of Directive 95/46/EC also cites Art. 45(9), which keeps it in force.

A transfer recorded as `adequacy` (or with no mechanism) for a destination with a scope-limited decision
stayed `PRESENT`, and its finding stated the limit and asked the reviewer to confirm that the importer is
within it; the input had no field for that confirmation. Section 5 adds the fields for Canada, Israel,
Japan and Korea. Brazil and the Faroe Islands keep the behaviour described here.

## 3. The status of the EU-US Data Privacy Framework decision

**Decision.** A DPF finding that the decision may carry (`PRESENT`, or `NEEDS_REVIEW` on the data the
certification covers) tells the reviewer to re-check the decision's status, citing what EUR-Lex records:

- The General Court dismissed the action for annulment of Implementing Decision (EU) 2023/1795 by its
  judgment of 3 September 2025, Latombe v Commission, T-553/23, ECLI:EU:T:2025:831 (CELEX 62023TJ0553).
- An appeal against that judgment was brought on 31 October 2025 (Case C-703/25 P, OJ C, C/2025/6610,
  22.12.2025). EUR-Lex listed no judgment on it on 2026-11-10. Whether it is still pending was not
  verifiable: curia.europa.eu was not reachable.
- The EUR-Lex record of the decision also lists a request for a preliminary ruling from the Cour d'appel
  de Bruxelles (Case C-804/25, lodged on 10 December 2025, OJ C, C/2026/2199, 27.4.2026). Its tenth
  question asks whether the decision is an adequacy decision for the tax-data transfers at issue there.
  The finding does not cite it, because it concerns transfers under an international tax agreement rather
  than the transfers a DPA governs.

## 4. The other Art. 46 safeguards

**Decision.** The input accepts every Art. 46 safeguard as a transfer mechanism. The tool cannot verify an
approval, an authorisation or an importer's commitment, so each goes to `NEEDS_REVIEW` with its exact
citation and what to confirm, and needs a transfer impact assessment like the SCCs:

| Value | Provision | What the reviewer confirms |
| --- | --- | --- |
| `public_bodies_instrument` | Art. 46(2)(a) | A legally binding and enforceable instrument between public authorities or bodies covers the transfer. |
| `sa_standard_clauses` | Art. 46(2)(d) | A supervisory authority adopted the clauses and the Commission approved them under the examination procedure of Art. 93(2). |
| `code_of_conduct` | Art. 46(2)(e), 40(3) | The code is approved under Art. 40(5) and has general validity under Art. 40(9), and the importer made binding and enforceable commitments, via contractual or other legally binding instruments, to apply the safeguards. |
| `certification` | Art. 46(2)(f), 42(2) | The certification mechanism, seal or mark is approved under Art. 42(5), and the importer made binding and enforceable commitments to apply the safeguards. |
| `authorised_clauses` | Art. 46(3)(a) | The competent supervisory authority authorised the clauses, or an authorisation given under Article 26(2) of Directive 95/46/EC remains valid (Art. 46(5)). |
| `administrative_arrangement` | Art. 46(3)(b) | The competent supervisory authority authorised the provisions, the arrangement is between public authorities or bodies, and it includes enforceable and effective data subject rights. |

BCR now cite Art. 46(2)(b) with Art. 47, and the SCCs Art. 46(2)(c) with Implementing Decision (EU)
2021/914, instead of the article ranges they cited before.

## 5. Scope conditions, dates and the European Patent Organisation

**Decision.** The legal review of 14 October 2026 asked about the scope of each decision, its dates and
the European Patent Organisation. The answers of 10 November 2026 adopt the model of branch
`fix/chapter-v-adequacy-model`; they are recorded as answers given under the owner's delegation, not as a
lawyer's sign-off. Each entry in `checks.ADEQUACY` now carries its operative provision, the date it
applies from, its last day of validity where it has one, the amendments that changed its scope or
validity, and the scope conditions below, all transcribed from the Official Journal texts in
[`sources/oj`](../sources/oj).

- **Unknown conditions fail closed.** A condition reads one fact the input records about the importer
  (per destination under `transfers`, or on the sub-processor entry). A failed condition means the
  decision does not cover the importer: with no other basis the transfer is `MISSING` (`HIGH`). An
  unknown condition is `NEEDS_REVIEW` with `HIGH` severity, so it blocks the packet until the fact is
  recorded. The same applies to a DPF certification whose coverage of the data transferred the input
  leaves open, which was `MEDIUM` before. With an Art. 46 safeguard recorded, the safeguard carries a
  transfer the decision does not cover, and the finding keeps the severity of section 2.
- **Canada** (Decision 2002/2/EC, Art. 1 and recital 5): `recipient_type`. A private commercial
  organisation is covered and a public body is not; a non-profit goes to review, because recital 5 brings
  non-profit organisations in only for activities of a commercial nature. Interpretation: mapping the
  input's categories onto "recipients subject to" PIPEDA through recital 5. Not modelled, and stated in
  the finding: recital 5's statement that the Act does not cover employment data used for non-commercial
  purposes other than that relating to employees in the federally regulated private sector, and the
  provincial exemptions (recital 6).
- **Japan** (Implementing Decision (EU) 2019/419, Art. 1(1) and (2), recitals 32 and 33):
  `recipient_type` (a public body is not a personal information handling business operator; a
  non-profit is, under recital 33) and `scope_carve_out`, one three-state input for the exclusions of
  Art. 1(2)(a) to (e): `"none"`, `"applies"`, or not recorded.
- **Korea** (Implementing Decision (EU) 2022/254, Art. 1(2)): `scope_carve_out`, one three-state input
  for the exclusions of Art. 1(2)(a) to (c). PIPA covers public and private entities (recital 19).
- **Israel** (Decision 2011/61/EU, Art. 1(1)): `automated_processing`, true when the transfer is
  automated or the data are subject to further automated processing in Israel. Article 2 limits the
  decision to the State of Israel as defined in accordance with international law; the input records no
  fact for it, and the tool reads every importer as within it (interpretation, stated in the finding).
- **Uruguay** (Implementing Decision 2012/484/EU): no condition. The title refers to automated processing;
  Article 1(1) sets no such limit, and the tool follows Article 1(1) (interpretation).
- **Brazil and the Faroe Islands**: no input. The tool reads every importer as within the scope limit
  (Brazil: controllers and processors subject to the LGPD, public or private, recitals 25 and 26; the
  Faroe Islands: recipients subject to the Faeroese Act), states that interpretation in the finding and
  asks the reviewer to confirm the limit. A safeguard recorded for either keeps the question of section 2.
- **The European Patent Organisation** (Implementing Decision (EU) 2025/1382, Art. 1): destination code
  `EPO`. It is an international organisation with its seat in Munich (recital 7); a transfer to it is a
  transfer under Chapter V (Art. 44), so the EEA exemption does not apply. A sub-processor's `country`
  stays a country code.
- **Citation form.** A finding cites "GDPR Art. 45(1)" (with Art. 45(9) for a decision adopted under
  Directive 95/46/EC) and the decision with its operative provision, for example "Commission Implementing
  Decision (EU) 2019/419, Art. 1".
- **Dates.** A decision with no date of application takes effect on notification, which its Official
  Journal text does not date; the tool reads it as applying from its date of adoption and dates an
  amending act the same way (interpretation). The Faroe Islands decision applies from 15 June 2010
  (Article 7). The United Kingdom decision "shall expire on 27 December 2031" (Article 4 as replaced by
  Implementing Decision (EU) 2025/2574); the tool reads that day as its last day of validity.
- **Review date.** `review_date` reads every decision as it applied on that date. Before its start date
  or after its last day, it does not cover the transfer. Before an amendment that changed its scope or
  validity (for the United Kingdom, Implementing Decisions (EU) 2025/1226 and 2025/2574), the transfer
  goes to review (`HIGH`, or the safeguard question where a safeguard is recorded), because the table
  models only the decision as last amended. A review date after the table date (`TABLE_AS_OF`) gets a
  note that later acts are not reflected; a value that is not a calendar date is refused (exit `3`).
- **Out of scope.** The United Kingdom decisions under Directive (EU) 2016/680 (law enforcement) are not
  snapshotted and not modelled.

The cases behind each answer are in [`tests/adequacy_cases.json`](../tests/adequacy_cases.json), written
from the snapshots before the rule code; each quotes the provision it rests on, and a test checks every
quote against its snapshot. On the pending appeal against the DPF decision see section 3. On
2026-11-14 a search of the Publications Office's Cellar found only the notice of appeal in C-703/25 P
(CELEX 62025CN0703) and no judgment, order or Opinion in the case; the Court's own register was not
read.

## Sources

Official Journal texts snapshotted under [`sources/oj`](../sources/oj) (retrieved 2026-10-14, re-fetched
byte-identical on 2026-11-14; URL, headers and SHA-256 in
[`sources/manifest.json`](../sources/manifest.json)): every adequacy decision on the list, the amending
acts 2016/2295, 2025/1226 and 2025/2574, Implementing Decision (EU) 2025/1382, the GDPR with its 2018
corrigendum, the corrigendum to Implementing Decision (EU) 2021/1772, and Implementing Decision (EU)
2021/914. A search of the Publications Office's Cellar on 2026-11-14 found no adequacy act later than
Implementing Decision (EU) 2026/179.

Read on EUR-Lex (English) on 2026-11-10:

- Regulation (EU) 2016/679 (GDPR), Art. 40(3), (5) and (9), 42(2) and (5), 44, 45(1), (3) and (9),
  46 and 49(1); CELEX 32016R0679.
- The adequacy decisions on the list, with their EUR-Lex records: CELEX 32000D0518, 32002D0002,
  32003D0490, 32003D0821, 32004D0411 (with its corrigendum, OJ L 208, 10.6.2004, p. 47), 32008D0393,
  32010D0146, 32010D0625, 32011D0061, 32012D0484, 32013D0065, 32019D0419, 32021D1772 (with its
  corrigendum to the title, OJ L 382, 28.10.2021, p. 55), 32022D0254, 32023D1795 and 32026D0179.
- The amending acts: Implementing Decision (EU) 2016/2295 (CELEX 32016D2295), 2025/1226 (32025D1226)
  and 2025/2574 (32025D2574).
- Implementing Decision (EU) 2025/1382 on the European Patent Organisation (CELEX 32025D1382).
- The General Court's judgment in T-553/23 (CELEX 62023TJ0553), the notice of appeal in C-703/25 P
  (CELEX 62025CN0703) and the notice of the reference in C-804/25 (CELEX 62025CN0804).

Not verified: the English text of the corrigendum to the Israel decision (CELEX 32011D0061R(01)) was not
available on EUR-Lex. The EDPB Recommendations 01/2020 and the Commission's adequacy page could not be
reached from the review environment (edpb.europa.eu and commission.europa.eu); the tool cites the
Recommendations as before.
