"""Command-line entry point.

    python -m dpa_review.cli --input data/sample_dpa.json --out examples

Writes review-packet.md and review-packet.json. Exit code is non-zero when the
packet is BLOCKED, so the check can gate a pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dpa_review.review import build_packet, render_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic DPA and data-transfer review.")
    parser.add_argument("--input", required=True, help="Path to a DPA JSON file.")
    parser.add_argument("--out", default=None, help="Output directory for the review packet.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the markdown packet.")
    args = parser.parse_args(argv)

    dpa = json.loads(Path(args.input).read_text(encoding="utf-8"))
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

    # BLOCKED -> exit 2 so this can gate CI; NEEDS_REVIEW -> exit 1; cleared -> 0.
    return {"BLOCKED": 2, "NEEDS_REVIEW": 1, "CLEARED_FOR_REVIEW": 0}[packet.review_state]


if __name__ == "__main__":
    sys.exit(main())
