"""Run dpa-review as the GitHub Action step that action.yml defines.

Reviews the input (one DPA description, or a directory reviewed as a register) and writes the
packets to the output directory. Then it writes an optional SARIF log, the job summary, one
annotation per open finding on the line of the DPA file that decided it, and the step outputs.
It exits with dpa-review's own exit code, so `fail-on` decides whether the step fails.

The inputs arrive as environment variables (DPA_REVIEW_INPUT, DPA_REVIEW_OUT, DPA_REVIEW_FAIL_ON,
DPA_REVIEW_SARIF, DPA_REVIEW_ANNOTATE), never interpolated into a shell command, so an input
cannot run code. dpa-review's standard error quotes file names and input values; it is relayed
with every line the runner would read as a workflow command made inert (neutralise), so a DPA
cannot issue one. Standard library only, like the package.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path

if sys.version_info < (3, 10):  # checked before the package is imported
    print(f"::error::dpa-review needs Python 3.10 or later; python3 is {sys.version.split()[0]}.")
    sys.exit(3)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dpa_review.cli import EXIT_INPUT_ERROR  # noqa: E402
from dpa_review.cli import main as dpa_review  # noqa: E402
from dpa_review.register import SCHEMA as REGISTER_SCHEMA  # noqa: E402
from dpa_review.register import render_summary  # noqa: E402

DEFAULT_OUT = "dpa-review"
DEFAULT_FAIL_ON = "blocked"
# SARIF level -> workflow command. GitHub shows at most 10 of each per step, so errors go first.
COMMANDS = {"error": "error", "warning": "warning", "note": "notice", "none": "notice"}
_ORDER = ("error", "warning", "notice")


def _run(args: list[str]) -> tuple[int, str, str]:
    """dpa-review's exit code, and what it printed on standard output and standard error."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = dpa_review(args)
        except SystemExit as exc:  # argparse exits on a usage error, with dpa-review's code 3
            code = exc.code if isinstance(exc.code, int) else EXIT_INPUT_ERROR
    return code, out.getvalue(), err.getvalue()


def _data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _property(text: str) -> str:
    return _data(text).replace(":", "%3A").replace(",", "%2C")


def neutralise(text: str) -> str:
    """text with every line the runner could read as a workflow command made inert.

    The runner reads a line of standard output or standard error as a command when it starts with
    "::" after leading white space, or when it contains "##[" anywhere (actions/runner,
    src/Runner.Common/ActionCommand.cs, TryParseV2 and TryParse). So the "::" that opens a line
    becomes "%3A%3A" and every "##[" becomes "#%23[". Lines are split wherever Python splits them,
    which includes CR and LF, the runner's line ends. Any other text is unchanged.
    """
    lines = []
    for line in text.splitlines(keepends=True):
        body = line.lstrip()
        if body.startswith("::"):
            line = line[: len(line) - len(body)] + "%3A%3A" + body[2:]
        lines.append(line.replace("##[", "#%23["))
    return "".join(lines)


def annotations(log: dict) -> list[str]:
    """One workflow command per SARIF result, errors first: ::error file=…,line=…,title=…::message."""
    commands = []
    for result in log["runs"][0]["results"]:
        location = result["locations"][0]["physicalLocation"]
        command = COMMANDS[result["level"]]
        text = (
            f"::{command} file={_property(location['artifactLocation']['uri'])},"
            f"line={location['region']['startLine']},title={_property(result['ruleId'])}"
            f"::{_data(result['message']['text'])}"
        )
        commands.append((_ORDER.index(command), text))
    return [text for _, text in sorted(commands, key=lambda item: item[0])]


def _no_state(source: str, errors: str) -> str:
    return (
        "# dpa-review\n\n"
        f"**No review state was decided** for `{source or '(no input given)'}` (exit code {EXIT_INPUT_ERROR}). "
        "dpa-review reported:\n\n"
        f"```text\n{errors.strip()}\n```\n\n"
        "docs/input-format.md describes the input contract.\n"
    )


def _set_outputs(path: str, outputs: dict[str, str]) -> None:
    delimiter = f"dpa-review-{uuid.uuid4().hex}"
    with open(path, "a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def run(environ: Mapping[str, str]) -> int:
    source = environ.get("DPA_REVIEW_INPUT", "")
    out = Path(environ.get("DPA_REVIEW_OUT", "") or DEFAULT_OUT)
    fail_on = environ.get("DPA_REVIEW_FAIL_ON", "") or DEFAULT_FAIL_ON
    sarif = environ.get("DPA_REVIEW_SARIF", "")
    annotate = environ.get("DPA_REVIEW_ANNOTATE", "true").strip().lower() != "false"

    common = ["--input", source, "--fail-on", fail_on]
    code, printed, errors = _run([*common, "--out", str(out), "--format", "json"])
    sys.stderr.write(neutralise(errors))
    # dpa-review prints the packet or the register summary only once it has written --out.
    data = json.loads(printed) if printed.strip() else None

    log = None
    if sarif or annotate:
        # The same deterministic review again, as SARIF; its errors are already in the log.
        _, sarif_text, _ = _run([*common, "--format", "sarif"])
        if sarif_text.strip():
            log = json.loads(sarif_text)
            if sarif:
                Path(sarif).parent.mkdir(parents=True, exist_ok=True)
                Path(sarif).write_text(sarif_text, encoding="utf-8")

    if data is None:
        state, summary_path, summary = "", "", _no_state(source, errors)
    elif data.get("schema") == REGISTER_SCHEMA:
        state = data["worst_review_state"] or ""
        summary_path, summary = str(out / "register-summary.md"), render_summary(data)
    else:
        state = data["review_state"]
        summary_path = str(out / "review-packet.md")
        summary = Path(summary_path).read_text(encoding="utf-8")

    if annotate and log is not None:
        for command in annotations(log):
            print(command)
    if environ.get("GITHUB_STEP_SUMMARY"):
        with open(environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    if environ.get("GITHUB_OUTPUT"):
        _set_outputs(
            environ["GITHUB_OUTPUT"],
            {
                "review-state": state,
                "exit-code": str(code),
                "out": str(out),
                "summary": summary_path,
                "sarif": sarif if sarif and log is not None else "",
            },
        )
    return code


if __name__ == "__main__":
    sys.exit(run(os.environ))
