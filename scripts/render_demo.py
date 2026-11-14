"""Render docs/demo.txt, the captured `make demo` output, into docs/demo.png.

    make demo > docs/demo.txt 2>&1
    python3 scripts/render_demo.py
    cd docs && shasum -a 256 demo.txt demo.png > demo.sha256

The image shows the captured text verbatim, with a "$ make demo" prompt line added and
long lines wrapped for display; nothing else is drawn. This is a documentation tool, not
part of the package: it needs Pillow, which the review itself never imports. The same text,
font file and Pillow version give a byte-identical image; tests/test_examples.py checks
the text against the live demo and the recorded hashes against both files.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT_CANDIDATES = (
    "/System/Library/Fonts/Menlo.ttc",  # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",  # Debian and Ubuntu
)
BACKGROUND = (22, 27, 34)
TITLE_BAR = (33, 38, 45)
TITLE_TEXT = (139, 148, 158)
TEXT = (230, 237, 243)
PROMPT = (126, 231, 135)
TITLE = "dpa-and-data-transfer-review"


def _font_path(explicit: str | None) -> str:
    if explicit:
        return explicit
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("no monospace font found; pass --font PATH")


def _display_lines(text: str, columns: int) -> list[str]:
    lines: list[str] = []
    for line in text.rstrip("\n").split("\n"):
        wrapped = textwrap.wrap(
            line, width=columns, break_long_words=True, break_on_hyphens=False, drop_whitespace=True
        )
        lines.extend(wrapped or [""])
    return lines


def render(text: str, font_path: str, columns: int, size: int) -> Image.Image:
    font = ImageFont.truetype(font_path, size)
    char_width = font.getlength("M")
    line_height = round(size * 1.55)
    margin = round(size * 1.5)
    title_height = round(size * 2.6)
    body = [("$ make demo", PROMPT)] + [(line, TEXT) for line in _display_lines(text, columns)]
    width = round(2 * margin + columns * char_width)
    height = title_height + 2 * margin + len(body) * line_height
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, title_height), fill=TITLE_BAR)
    draw.text((margin * 0.8, (title_height - size) / 2), TITLE, font=font, fill=TITLE_TEXT)
    y = title_height + margin
    for line, colour in body:
        draw.text((margin, y), line, font=font, fill=colour)
        y += line_height
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--text", default=str(ROOT / "docs" / "demo.txt"))
    parser.add_argument("--out", default=str(ROOT / "docs" / "demo.png"))
    parser.add_argument("--font", default=None, help="Monospace TrueType font file.")
    parser.add_argument("--columns", type=int, default=130)
    parser.add_argument("--size", type=int, default=22)
    args = parser.parse_args()
    text = Path(args.text).read_text(encoding="utf-8")
    render(text, _font_path(args.font), args.columns, args.size).save(args.out, format="PNG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
