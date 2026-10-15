"""Command-line entry point.

    python -m dpa_review.cli --input data/sample_dpa.json --out examples
    dpa-review --input vendors/ --out register --format sarif > dpa-review.sarif
    dpa-review --schema

Reviews one DPA description (a file, or `-` for standard input), or every *.json file directly
inside a directory, which is treated as a register of DPAs. Every input is checked against the
input contract (contract.py) before any rule runs, so a misspelt key or a wrong type cannot
read as "not recorded". With --out, writes review-packet.md and .json and the transfer evidence
graph: for a register, one subdirectory per input (named after the file), plus
register-summary.md and .json.

The exit code gates a pipeline: 2 BLOCKED, 1 NEEDS_REVIEW, 0 CLEARED_FOR_REVIEW (the worst
state across a register). --fail-on blocked exits 0 for NEEDS_REVIEW, --fail-on never always
exits 0. Unreadable input, input that breaks the contract, or a usage error exits 3 with
one-line errors on stderr (no traceback): no review state was decided. So does an output that
cannot be written, and any unexpected failure (with its traceback), so a crash never reads as
a review state.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from dpa_review import __version__
from dpa_review.contract import ContractError, schema_text, validate
from dpa_review.facts import key_lines, line_of
from dpa_review.register import Problem, Review, render_summary, summary, worst_state
from dpa_review.review import build_packet, render_markdown
from dpa_review.sarif import sarif_log
from dpa_review.transfer_graph import (
    build_transfer_evidence_graph,
    render_transfer_evidence_graph,
)


EXIT_INPUT_ERROR = 3
EXIT_CODES = {"BLOCKED": 2, "NEEDS_REVIEW": 1, "CLEARED_FOR_REVIEW": 0}
# The lowest exit code that still fails, per --fail-on.
FAIL_THRESHOLD = {"needs_review": 1, "blocked": 2, "never": 4}
STDIN = "-"


class _ArgumentParser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, which would read as BLOCKED; exit 3 instead."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT_ERROR, f"{self.prog}: error: {message}\n")


def _name(source: str) -> str:
    return "standard input" if source == STDIN else source


def _read(path: str) -> str:
    if path == STDIN:
        # Read bytes where possible, so the input is UTF-8 whatever the locale, as for a file.
        data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read()
        if isinstance(data, str):
            return data
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"standard input is not valid UTF-8 text: {exc.reason}") from exc
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path} is not valid UTF-8 text: {exc.reason}") from exc


def _parse(text: str, path: str) -> dict:
    try:
        dpa = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc
    if not isinstance(dpa, dict):
        raise ValueError(
            f"{path} must contain a JSON object at the top level, got {type(dpa).__name__}"
        )
    return dpa


def _review(source: str) -> Review:
    """Read, check and review one input. A failure is recorded on the Review, never raised."""
    review = Review(source=source)
    try:
        review.text = _read(source)
        review.dpa = _parse(review.text, _name(source))
        validate(review.dpa)
    except ContractError as exc:
        lines = key_lines(review.text)
        review.errors = [Problem(violation.message, line_of(lines, violation.path)) for violation in exc.violations]
        return review
    except ValueError as exc:
        review.errors = [Problem(str(exc))]
        return review
    review.packet = build_packet(review.dpa)
    return review


def _report_errors(review: Review) -> None:
    if review.dpa is None:  # unreadable, or not a JSON object: a single message
        print(f"error: {review.errors[0]}", file=sys.stderr)
        return
    count = len(review.errors)
    print(
        f"error: {_name(review.source)} breaks the input contract, so no review state was decided "
        f"({count} problem{'s' if count != 1 else ''}):",
        file=sys.stderr,
    )
    for error in review.errors:
        print(f"  {error}", file=sys.stderr)
    print("See docs/input-format.md, or run `dpa-review --schema` for the JSON Schema.", file=sys.stderr)


def _write_packet(review: Review, out_dir: Path) -> None:
    packet = review.packet
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "review-packet.md").write_text(render_markdown(packet), encoding="utf-8")
    (out_dir / "review-packet.json").write_text(
        json.dumps(packet.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    transfer_graph = build_transfer_evidence_graph(review.dpa, packet)
    (out_dir / "transfer-evidence-graph.json").write_text(
        json.dumps(transfer_graph, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "transfer-evidence-graph.md").write_text(
        render_transfer_evidence_graph(transfer_graph),
        encoding="utf-8",
    )


def _write_outputs(reviews: list[Review], data: dict | None, out_dir: Path) -> None:
    """Write each packet, and for a register (data is its summary) one directory per input."""
    for review in reviews:
        if review.packet:
            _write_packet(review, out_dir / Path(review.source).stem if data is not None else out_dir)
    if data is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "register-summary.md").write_text(render_summary(data), encoding="utf-8")
        (out_dir / "register-summary.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def _exit_code(state: str | None, fail_on: str) -> int:
    if state is None:
        return EXIT_INPUT_ERROR
    code = EXIT_CODES[state]
    return code if code >= FAIL_THRESHOLD[fail_on] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="dpa-review",
        description="Deterministic DPA and data-transfer review.",
        epilog="Exit codes: 2 BLOCKED, 1 NEEDS_REVIEW, 0 CLEARED_FOR_REVIEW, 3 no review state decided "
        "(unreadable input, input that breaks the input contract, or a usage error).",
    )
    parser.add_argument(
        "--input",
        help="A DPA JSON file, '-' for standard input, or a directory whose *.json files are reviewed as a register.",
    )
    parser.add_argument("--out", default=None, help="Output directory for the review packet(s).")
    parser.add_argument(
        "--format",
        choices=("md", "json", "sarif"),
        default="md",
        help="What to print: the Markdown packet or register summary (default), its JSON, or SARIF 2.1.0.",
    )
    parser.add_argument("--quiet", action="store_true", help="Print nothing on standard output.")
    parser.add_argument(
        "--fail-on",
        choices=tuple(FAIL_THRESHOLD),
        default="needs_review",
        help="Lowest review state that exits non-zero (default needs_review). Input errors always exit 3.",
    )
    parser.add_argument(
        "--schema", action="store_true", help="Print the input contract as JSON Schema and exit."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(parser, args)
    except Exception:
        # Python exits 1 on an uncaught exception, which would read as NEEDS_REVIEW.
        traceback.print_exc()
        print("error: dpa-review failed unexpectedly, so no review state was decided.", file=sys.stderr)
        return EXIT_INPUT_ERROR


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.schema:
        sys.stdout.write(schema_text())
        return 0
    if not args.input:
        parser.error("--input is required (or use --schema)")

    register = args.input != STDIN and Path(args.input).is_dir()
    if register:
        if args.out and Path(args.out).resolve() == Path(args.input).resolve():
            parser.error("--out must not be the input directory: the next run would review the register summary as a DPA")
        sources = sorted(str(path) for path in Path(args.input).iterdir() if path.suffix == ".json" and path.is_file())
        if not sources:
            print(f"error: {args.input} contains no *.json files to review", file=sys.stderr)
            return EXIT_INPUT_ERROR
    else:
        sources = [args.input]

    reviews = [_review(source) for source in sources]
    for review in reviews:
        if not review.packet:
            _report_errors(review)
    if any(not review.packet for review in reviews):
        exit_code = EXIT_INPUT_ERROR
    else:
        exit_code = _exit_code(worst_state(reviews), args.fail_on)

    data = summary(reviews, exit_code) if register else None
    if args.out:
        try:
            _write_outputs(reviews, data, Path(args.out))
        except OSError as exc:
            print(f"error: cannot write to {args.out}: {exc.strerror or exc}", file=sys.stderr)
            return EXIT_INPUT_ERROR

    if not args.quiet:
        if args.format == "sarif":
            print(json.dumps(sarif_log(reviews, __version__), indent=2, ensure_ascii=False))
        elif register:
            print(json.dumps(data, indent=2, ensure_ascii=False) if args.format == "json" else render_summary(data))
        elif reviews[0].packet is None:
            pass  # no review state was decided: nothing to print, the errors are on stderr
        elif args.format == "json":
            print(json.dumps(reviews[0].packet.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(render_markdown(reviews[0].packet))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
