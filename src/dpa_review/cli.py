"""Command-line entry point.

    python -m dpa_review.cli --input data/sample_dpa.json --out examples

Writes review-packet.md and review-packet.json. Exit code is non-zero when the
packet is BLOCKED, so the check can gate a pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from dpa_review.checks import InvalidInputError
from dpa_review.review import build_packet, render_markdown
from dpa_review.transfer_graph import (
    build_transfer_evidence_graph,
    render_transfer_evidence_graph,
)

# BLOCKED -> exit 2 so this can gate CI; NEEDS_REVIEW -> exit 1; cleared -> 0.
EXIT_CODES = {"BLOCKED": 2, "NEEDS_REVIEW": 1, "CLEARED_FOR_REVIEW": 0}
# No review state was decided: unreadable or malformed input, a usage error, or a failure.
# It must differ from the codes above, so that a crash never reads as a review state.
EXIT_NO_REVIEW_STATE = 3


class _ArgumentParser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, which would read as BLOCKED; use 3 instead."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_NO_REVIEW_STATE, f"{self.prog}: error: {message}\n")


def _review(args: argparse.Namespace) -> int:
    dpa = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(dpa, dict):
        raise InvalidInputError("the DPA input must be a JSON object.")
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


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description="Deterministic DPA and data-transfer review.")
    parser.add_argument("--input", required=True, help="Path to a DPA JSON file.")
    parser.add_argument("--out", default=None, help="Output directory for the review packet.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the markdown packet.")
    args = parser.parse_args(argv)

    try:
        return _review(args)
    except (OSError, ValueError) as exc:  # includes InvalidInputError and JSON decode errors
        print(f"error: cannot review {args.input}: {exc}", file=sys.stderr)
    except Exception:  # any other failure must not read as a review state either
        traceback.print_exc()
        print(f"error: cannot review {args.input}; see the traceback above.", file=sys.stderr)
    return EXIT_NO_REVIEW_STATE


if __name__ == "__main__":
    sys.exit(main())
