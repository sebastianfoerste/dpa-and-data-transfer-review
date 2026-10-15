"""Command-line entry point.

    python -m dpa_review.cli --input data/sample_dpa.json --out examples

Writes review-packet.md and review-packet.json. Exit code is non-zero when the
packet is BLOCKED, so the check can gate a pipeline. Unreadable or invalid
input exits 3 with a one-line error on stderr (no traceback).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dpa_review.review import build_packet, render_markdown
from dpa_review.transfer_graph import (
    build_transfer_evidence_graph,
    render_transfer_evidence_graph,
)


EXIT_INPUT_ERROR = 3


def _load_dpa(path: str) -> dict:
    """Read the DPA JSON, raising ValueError with a user-facing message on bad input."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path} is not valid UTF-8 text: {exc.reason}") from exc
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic DPA and data-transfer review.")
    parser.add_argument("--input", required=True, help="Path to a DPA JSON file.")
    parser.add_argument("--out", default=None, help="Output directory for the review packet.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the markdown packet.")
    args = parser.parse_args(argv)

    try:
        dpa = _load_dpa(args.input)
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

    # BLOCKED -> exit 2 so this can gate CI; NEEDS_REVIEW -> exit 1; cleared -> 0.
    return {"BLOCKED": 2, "NEEDS_REVIEW": 1, "CLEARED_FOR_REVIEW": 0}[packet.review_state]


if __name__ == "__main__":
    sys.exit(main())
