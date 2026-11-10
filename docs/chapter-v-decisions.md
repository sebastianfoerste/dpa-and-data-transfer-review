# Chapter V decisions

PR #4 left four legal questions for the owner. The owner delegated them. This page records each
decision, what the tool now does, and the source text it rests on. Every source below was read on
EUR-Lex on 2026-11-10. The tests that pin each decision are in
[`tests/test_transfer_bases.py`](../tests/test_transfer_bases.py); the conformance fixtures 10, 13, 14
and 15 run them through the CLI ([conformance.md](conformance.md)).

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

The tool models countries only. Commission Implementing Decision (EU) 2025/1382 of 15 July 2025 finds an
adequate level of protection for the European Patent Organisation, an international organisation, and is
not on the list.

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
- **The United States** has no country-wide decision: Implementing Decision (EU) 2023/1795 covers only
  organisations on the Data Privacy Framework List. A safeguard recorded for the US keeps the Art. 46 path,
  with its assessment, and the finding adds that a certified importer can be recorded as `dpf`.

A finding that relies on a decision cites Art. 45(1) and the decision. A decision adopted under Article
25(6) of Directive 95/46/EC also cites Art. 45(9), which keeps it in force.

A transfer recorded as `adequacy` (or with no mechanism) for a destination with a scope-limited decision
stays `PRESENT`, and its finding states the limit and asks the reviewer to confirm that the importer is
within it. The input has no field for that confirmation. Adding one would be a change to the input
contract beyond these four questions.

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

## Sources

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
