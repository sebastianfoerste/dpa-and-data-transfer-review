# Contributing

This is a personal, public-safe prototype. Contributions, corrections, and issues are welcome — especially on citation accuracy and the reference data (EEA members, adequacy decisions, valid transfer mechanisms).

## Ground rules

1. **Synthetic data only.** Never add real client data, privileged material, negotiation history, or personal data. Pull requests that introduce non-synthetic data will be closed.
2. **Deterministic by default.** Rules must produce the same output for the same input. No network calls and no model calls in the checks or the engine.
3. **Cited findings.** Every rule must carry a specific, verifiable citation (GDPR Article, CCPA/CPRA section, or a named decision). A finding without a citation is a bug.
4. **Not legal advice.** Keep the framing as a review/triage packet. Do not add language that asserts a legal conclusion.

## Working on it

```bash
make install   # standard library only
make test      # must pass before any PR
make demo      # regenerate examples/ if rule output changed
```

If a change alters rule output, run `make demo` and commit the regenerated `examples/` (the review packet and the transfer evidence graph, each as Markdown and JSON) in the same PR so the committed sample stays truthful.

## Adding a rule

1. Add a check function in `src/dpa_review/checks.py` returning one or more `Finding`s, each with a citation and severity.
2. Register it in `ALL_CHECKS`.
3. Add a test in `tests/test_review.py` covering both the present and the missing case.
4. Run `make test` and `make demo`.

## Reporting an issue

Good issues are specific: the rule, the citation you think is wrong, and the corrected reference. Citation fixes are the most valuable contribution here.

The issue forms ask for exactly that: a [citation correction](https://github.com/sebastianfoerste/dpa-and-data-transfer-review/issues/new?template=citation-correction.yml), a [rule request](https://github.com/sebastianfoerste/dpa-and-data-transfer-review/issues/new?template=rule-request.yml) or a [bug report](https://github.com/sebastianfoerste/dpa-and-data-transfer-review/issues/new?template=bug.yml). An input that comes out with a better review state than its facts warrant is a security issue: report it privately, as [SECURITY.md](SECURITY.md) describes.

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
