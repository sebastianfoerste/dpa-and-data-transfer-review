# Source snapshots

The adequacy reference data in `src/dpa_review/checks.py` (`ADEQUACY` and
`DPF_ADEQUACY`) rests on the texts in this folder: each entry's decision number,
date of adoption, Official Journal reference, operative provision, scope
conditions, start date and end date. The folder also holds Regulation (EU)
2016/679 and Implementing Decision (EU) 2021/914 on standard contractual
clauses, which the transfer findings cite. Each file is the English expression
of an act as served by the Publications Office of the European Union, retrieved
through its CELEX resource URL:

```
curl -sSL -H "Accept: application/xhtml+xml" -H "Accept-Language: eng" \
  https://publications.europa.eu/resource/celex/<CELEX>
```

Four acts from 2000 to 2003 have no XHTML expression; they were retrieved with
`Accept: text/html`.

`manifest.json` records, for every file, the CELEX number, the Official Journal
reference, the requested and resolved URL, the request headers, the retrieval
time, the time it was last re-fetched and found byte-identical (`rechecked_at`)
and the SHA-256 of the bytes as received. Its `recheck` block records the last
full re-check: every file re-fetched, and the Publications Office's Cellar
searched for later adequacy acts. `TABLE_AS_OF` in `checks.py` is that date, and
`dpa-review-table-age` (or `make table-age`) reports how old it is.

`tests/test_sources.py` checks that every file still matches its recorded hash.
`tests/test_adequacy.py` checks that every adequacy entry cites a file listed
here, that its number, date and Official Journal reference appear in that file,
and that every case in `tests/adequacy_cases.json` quotes its snapshot verbatim.

Rules:

- Never edit a snapshot by hand. A new text is a new retrieval with a new
  manifest entry.
- The Commission's adequacy page served as an index only. No rule rests on it.
- When a decision is adopted, amended, renewed or repealed: snapshot the act,
  add its manifest entry, write the fixture cases in `tests/adequacy_cases.json`
  from its text, then update the entry in `checks.py`, `TABLE_AS_OF` and the
  `recheck` block, and regenerate the docs and the sample packet (`make docs`,
  `make demo`).
- The United Kingdom decisions under Directive (EU) 2016/680 (law enforcement)
  are outside the tool's GDPR scope and are not snapshotted.

## Texts consulted but not snapshotted

Some citations rest on texts outside the Official Journal: the judgment in
Case C-311/18, EDPB Guidelines 2/2018 and Recommendations 01/2020, and the
California Civil Code sections of the CCPA check. `manifest.json` lists them
under `texts_consulted` with the URL, retrieval time, SHA-256 of the file as
received and the passages checked. They are not stored here. EDPB guidance is
guidance, not law.
