"""Command-line entry point.

    python -m dpa_review.cli --input data/sample_dpa.json --out examples
    dpa-review --schema

Writes review-packet.md and review-packet.json, and the transfer evidence graph. The input is
checked against the input contract (contract.py) before any rule runs, so a misspelt key or a
wrong type cannot read as "not recorded".

The exit code gates a pipeline: 2 BLOCKED, 1 NEEDS_REVIEW, 0 CLEARED_FOR_REVIEW. Unreadable
input, input that breaks the contract, or a usage error exits 3 with one-line errors on stderr
(no traceback): no review state was decided.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dpa_review.contract import ContractError, schema_text, validate
from dpa_review.facts import key_lines, line_of
from dpa_review.review import build_packet, render_markdown
from dpa_review.transfer_graph import (
    build_transfer_evidence_graph,
    render_transfer_evidence_graph,
)


EXIT_INPUT_ERROR = 3
EXIT_CODES = {"BLOCKED": 2, "NEEDS_REVIEW": 1, "CLEARED_FOR_REVIEW": 0}


class _ArgumentParser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, which would read as BLOCKED; exit 3 instead."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT_ERROR, f"{self.prog}: error: {message}\n")


def _read(path: str) -> str:
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


def _report_violations(path: str, text: str, error: ContractError) -> None:
    lines = key_lines(text)
    count = len(error.violations)
    print(
        f"error: {path} breaks the input contract, so no review state was decided "
        f"({count} problem{'s' if count != 1 else ''}):",
        file=sys.stderr,
    )
    for violation in error.violations:
        print(f"  line {line_of(lines, violation.path)}: {violation.message}", file=sys.stderr)
    print("See docs/input-format.md, or run `dpa-review --schema` for the JSON Schema.", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="dpa-review",
        description="Deterministic DPA and data-transfer review.",
        epilog="Exit codes: 2 BLOCKED, 1 NEEDS_REVIEW, 0 CLEARED_FOR_REVIEW, 3 no review state decided "
        "(unreadable input, input that breaks the input contract, or a usage error).",
    )
    parser.add_argument("--input", help="Path to a DPA JSON file.")
    parser.add_argument("--out", default=None, help="Output directory for the review packet.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the markdown packet.")
    parser.add_argument(
        "--schema", action="store_true", help="Print the input contract as JSON Schema and exit."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.schema:
        sys.stdout.write(schema_text())
        return 0
    if not args.input:
        parser.error("--input is required (or use --schema)")

    text = ""
    try:
        text = _read(args.input)
        dpa = _parse(text, args.input)
        validate(dpa)
    except ContractError as exc:
        _report_violations(args.input, text, exc)
        return EXIT_INPUT_ERROR
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    packet = build_packet(dpa)
    markdown = render_markdown(packet)

    if not args.quiet:
        print(markdown)

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "review-packet.md").write_text(markdown, encoding="utf-8")
        (out_dir / "review-packet.json").write_text(
            json.dumps(packet.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        transfer_graph = build_transfer_evidence_graph(dpa, packet)
        (out_dir / "transfer-evidence-graph.json").write_text(
            json.dumps(transfer_graph, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (out_dir / "transfer-evidence-graph.md").write_text(
            render_transfer_evidence_graph(transfer_graph),
            encoding="utf-8",
        )

    return EXIT_CODES[packet.review_state]


if __name__ == "__main__":
    sys.exit(main())
