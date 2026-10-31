# dpa-and-data-transfer-review

[![CI](https://github.com/sebastianfoerste/dpa-and-data-transfer-review/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sebastianfoerste/dpa-and-data-transfer-review/actions/workflows/ci.yml)

Deterministic, cited GDPR Art. 28 and Chapter V checks over a structured description of a Data Processing Agreement. It writes a review packet with a visible review state and a gating exit code. Standard-library Python, no network, no model calls. Not legal advice; all bundled data is synthetic.

## What it checks

- **Art. 28(3)(a)-(h) processor clauses**, the processing description, sub-processor authorisation (Art. 28(2)) and flow-down (Art. 28(4)), breach notification without undue delay (Art. 33(2)).
- **Chapter V transfers**, per destination and per sub-processor: EEA, adequacy (Art. 45), SCCs or BCR (Art. 46-47) with a recorded transfer impact assessment, Art. 49 derogations.
- CCPA/CPRA service-provider terms as a secondary lens.

Any open HIGH finding makes the packet `BLOCKED` (exit `2`); any other open finding `NEEDS_REVIEW` (exit `1`); otherwise `CLEARED_FOR_REVIEW` (exit `0`, still subject to lawyer sign-off). Input that breaks the [input contract](docs/input-format.md) exits `3` with no review state: a misspelt key cannot read as "no transfer".

## Run it

```bash
make install   # Python 3.10+, standard library only
make test      # deterministic tests
make demo      # reviews data/sample_dpa.json, writes examples/, exits 2
```

The sample DPA plants three defects (missing flow-down, a US sub-processor and a US transfer without a mechanism); [`examples/review-packet.md`](examples/review-packet.md) and [`examples/transfer-evidence-graph.md`](examples/transfer-evidence-graph.md) are the committed `BLOCKED` packet and weakest-link graph. Fixing them gives `NEEDS_REVIEW`; a test asserts that.

`dpa-review` also reviews a directory of DPAs as a register, prints SARIF 2.1.0 for code scanning, and runs as a [GitHub Action](docs/github-action.md) that fails a check when a DPA is `BLOCKED`.

## Docs

- [`docs/rules.md`](docs/rules.md): every rule, citation and severity.
- [`docs/input-format.md`](docs/input-format.md) and [`schema/dpa.schema.json`](schema/dpa.schema.json): the input contract.
- [`docs/conformance.md`](docs/conformance.md): synthetic fixtures with their expected review state and exit code.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): citation corrections welcome.

## Scope

First-pass triage over a structured description, not free-text contracts. The EEA and adequacy lists in [`src/dpa_review/checks.py`](src/dpa_review/checks.py) are illustrative: verify them against the current European Commission decisions before relying on a result. The checks, reference data and thresholds are human-authored; AI tools assisted the implementation. No legal advice, no lawyer-client relationship, no client data.

## License

MIT. See [`LICENSE`](LICENSE).
