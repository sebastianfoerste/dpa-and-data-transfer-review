# GitHub Action

This is for teams that keep their DPA descriptions, or a whole vendor register, in Git. The
action reviews them on every push or pull request. It fails the check when a DPA is `BLOCKED`, so
a required status check can stop the merge. The decision is deterministic: the same files give the
same result on every run, with no network access, no model call and no token.

## Usage

```yaml
# .github/workflows/dpa-review.yml
name: dpa-review

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: sebastianfoerste/dpa-and-data-transfer-review@<full-length commit SHA>
        with:
          input: vendors/
```

`input` is one DPA description, or a directory whose `*.json` files are reviewed as a register
(see [input-format.md](input-format.md)). Pin a full commit SHA: there are no release tags yet, and
a SHA cannot move. To block merges, make the job a required status check in the branch protection
rules.

## Inputs

| Name | Default | Meaning |
| --- | --- | --- |
| `input` | (required) | A DPA description (a JSON file), or a directory whose `*.json` files are reviewed as a register. |
| `out` | `dpa-review` | Directory for the review packets. A register gets one subdirectory per input, plus `register-summary.md` and `.json`. |
| `fail-on` | `blocked` | Lowest review state that fails the step: `blocked`, `needs_review` or `never`. Input that cannot be read or that breaks the input contract always fails it. |
| `sarif` | empty | Path of a SARIF 2.1.0 log to write. Empty writes none. |
| `annotate` | `true` | Annotate each open finding on the line of the DPA file that decided it. |

`fail-on` defaults to `blocked`: the step fails when any DPA has an open `HIGH` finding. The CLI
itself defaults to `needs_review`. A merge gate needs a different default because `NEEDS_REVIEW`
means "a lawyer has to look", and every DPA that relies on SCCs stays there by design (see
[rules.md](rules.md)). A check that always fails gets ignored. Set `fail-on: needs_review` to fail
on those as well.

## Outputs

| Name | Meaning |
| --- | --- |
| `review-state` | The worst review state found: `BLOCKED`, `NEEDS_REVIEW` or `CLEARED_FOR_REVIEW`. Empty when no review state was decided. |
| `exit-code` | The exit code of `dpa-review` after `fail-on`, which is also the step's exit code: `2` blocked, `1` needs review, `0` passed, `3` no review state was decided. |
| `out` | The directory the review packets were written to. |
| `summary` | Path of the Markdown review packet, or of the register summary. Empty when no review state was decided. |
| `sarif` | Path of the SARIF log, when one was written. |

## What the step writes

- **Review packets** in `out`, exactly as `dpa-review --out` writes them.
- **The job summary:** the review packet, or for a register the summary, which counts the states,
  lists every DPA and ranks the open rules. Input that breaks the contract is listed with every
  error.
- **Annotations:** each open finding becomes an annotation on the line of the DPA file holding
  the fact that decided it. `HIGH` becomes an error, `MEDIUM` a warning, and `LOW` a notice. On a pull
  request they appear next to the changed lines. GitHub shows at most 10 of each kind per step;
  the job summary and the SARIF log list them all.
- **A SARIF log**, if `sarif` is set. Upload it to code scanning to track findings across runs:

```yaml
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: sebastianfoerste/dpa-and-data-transfer-review@<full-length commit SHA>
        with:
          input: vendors/
          sarif: dpa-review.sarif
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: dpa-review.sarif
          category: dpa-review
```

Code scanning is available on public repositories, and on private ones with GitHub Code
Security.

## Requirements

The step runs `python3` under bash and needs Python 3.10 or later. GitHub-hosted Ubuntu runners
have it. On other runners, run `actions/setup-python` first. Windows runners are not supported.
Nothing is installed: the package is standard library only and runs from the action's own
checkout. The inputs reach the step as environment variables, never as shell code.
