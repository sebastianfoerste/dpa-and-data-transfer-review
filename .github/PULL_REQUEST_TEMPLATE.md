## What changes

<!-- One or two sentences. Link the issue it closes, if any. -->

## Checklist

<!-- Tick what applies; strike through or delete what does not. -->

- [ ] `make test` and `make lint` pass.
- [ ] Rule output changed: I ran `make demo` and committed the regenerated `examples/`.
- [ ] The input contract, a rule or a fixture changed: I ran `make docs` and committed the regenerated `schema/` and `docs/`.
- [ ] New or changed rule: tests cover both the PRESENT and the MISSING (or NEEDS_REVIEW) case.
- [ ] New or changed citation: the primary source is linked below.
- [ ] An expected result in `tests/fixtures/expected.json` changed: the reason is below. This was a deliberate change, reviewed by a lawyer, not a test fixed to pass.
- [ ] Synthetic data only: no real client data, privileged material or personal data. Every organisation name in structured data is on `tests/fictional_organisations.json` (`make test` checks this).
- [ ] Screenshots and images (for example `docs/demo.png`) were opened and checked by hand: they show real output of this version and no real organisation or person.
- [ ] Adequacy reference data changed only from an Official Journal text snapshotted in `sources/oj`, with its manifest entry (`sources/README.md`).

## Primary sources

<!-- For every citation added or changed, link the official text (EUR-Lex, European Commission, EDPB, CJEU). -->
