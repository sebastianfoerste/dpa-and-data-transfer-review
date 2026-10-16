# Security policy

`dpa-review` is a gate: a pipeline reads its exit code as a review decision. Anything that makes it
report a better review state than the rules decide is therefore a security issue here, not only a bug.

## Supported versions

There are no releases yet. Only the latest commit on `main` is supported, and fixes land there.

## Report privately

- **A fail-open gate:** an input that the [input contract](docs/input-format.md) accepts, but that comes
  out with a better review state or a lower exit code than its facts warrant. For example, a key,
  type or value that the rules read as "clause present" or as "not a transfer".
- **A failure that exits 0, 1 or 2** instead of 3, so that a pipeline would read a crash or an unread
  input as a review state.
- Anything that makes the package use the network, run code taken from its input, or write
  outside the `--out` directory.

## Report publicly

A question about a citation, a severity or the reference data (an EEA member, an adequacy decision,
a transfer mechanism) is not a security issue. Open a
[citation correction](https://github.com/sebastianfoerste/dpa-and-data-transfer-review/issues/new?template=citation-correction.yml)
or a [rule request](https://github.com/sebastianfoerste/dpa-and-data-transfer-review/issues/new?template=rule-request.yml)
so that others can check the source too.

## How to report

Use GitHub's private vulnerability reporting: **Security → Report a vulnerability** on this repository.
If that is not available, contact the maintainer through the details on
<https://github.com/sebastianfoerste>. Please do not open a public issue for a fail-open gate.

Include:

- the smallest **synthetic** input that reproduces it;
- the command;
- the exit code you got and the one you expected;
- the output of `dpa-review --version`, or the commit you ran.

Never send real DPAs, client data, privileged material or personal data.

This is a personal project, maintained on a best-effort basis. There is no guaranteed response time.
