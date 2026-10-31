"""Write docs/demo.txt and docs/demo.png, the README's picture of the demo, from a live run of the CLI.

    python3 scripts/render_demo.py          # rewrite both files
    python3 scripts/render_demo.py --check  # exit 1 if either is out of date

docs/demo.txt is the transcript of the command that `make demo` runs on data/sample_dpa.json: the
command, everything the CLI prints, and its exit code. docs/demo.png draws that text line by line in
a fixed-width bitmap font (scripts/demo-font-9x15.bdf). A line longer than COLUMNS characters wraps
after its last space that fits, and every character stays in the picture.

The script uses only the standard library, so no image tool becomes a dependency, and the same text
always gives the same pixels. tests/test_demo_image.py fails when docs/demo.txt differs from a live
run, or when docs/demo.png does not show docs/demo.txt.
"""

from __future__ import annotations

import contextlib
import io
import struct
import sys
import tempfile
import zlib
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dpa_review.cli import main as cli_main  # noqa: E402

SAMPLE = "data/sample_dpa.json"
# The Makefile's demo recipe with its variables filled in (tests/test_demo_image.py checks this).
COMMAND = f"PYTHONPATH=src python3 -m dpa_review.cli --input {SAMPLE} --out examples"
PROMPT = "$ "
TEXT_PATH = ROOT / "docs" / "demo.txt"
IMAGE_PATH = ROOT / "docs" / "demo.png"
FONT_PATH = ROOT / "scripts" / "demo-font-9x15.bdf"

COLUMNS = 100
PADDING = 16  # pixels around the text
LINE_GAP = 1  # pixels between rows of text
# Palette indices: 0 is the background; prompt lines are drawn in their own colour.
PALETTE = ((22, 27, 34), (230, 237, 243), (126, 231, 135))
BACKGROUND, TEXT, PROMPT_LINE = range(len(PALETTE))
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_INK = bytes([0] + [1] * 255)  # bytes.translate table: background 0, any other index 1


def transcript() -> str:
    """The terminal session that docs/demo.txt records: the command, what the CLI prints on standard
    output and standard error in the order printed, and its exit code. The CLI runs in this process
    with --out set to a temporary directory; what it prints does not depend on --out."""
    printed = io.StringIO()
    with tempfile.TemporaryDirectory() as out:
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            code = cli_main(["--input", str(ROOT / SAMPLE), "--out", out])
    return f"{PROMPT}{COMMAND}\n{printed.getvalue()}{PROMPT}echo $?\n{code}\n"


class Font(NamedTuple):
    width: int
    height: int
    glyphs: dict[str, tuple[bytes, ...]]  # per character, `height` rows of `width` pixels, 1 for ink


def load_font(path: Path = FONT_PATH) -> Font:
    """Read a fixed-width BDF font into whole-cell glyphs."""
    width = height = ascent = code = box = bitmap = None
    glyphs: dict[str, tuple[bytes, ...]] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        key, *values = line.split()
        if bitmap is not None and key != "ENDCHAR":
            bitmap.append(key)
        elif key == "FONTBOUNDINGBOX":
            width, height, _, y_offset = map(int, values)
            ascent = height + y_offset
        elif key == "ENCODING":
            code = int(values[0])
        elif key == "DWIDTH" and int(values[0]) != width:
            raise ValueError(f"{path.name}: U+{code:04X} is not {width} pixels wide; the font must be fixed-width")
        elif key == "BBX":
            box = tuple(map(int, values))
        elif key == "BITMAP":
            bitmap = []
        elif key == "ENDCHAR":
            glyphs[chr(code)] = _cell(bitmap, box, width, height, ascent, f"{path.name}: U+{code:04X}")
            bitmap = None
    return Font(width, height, glyphs)


def _cell(bitmap: list[str], box: tuple, width: int, height: int, ascent: int, name: str) -> tuple[bytes, ...]:
    box_width, box_height, x_offset, y_offset = box
    top = ascent - box_height - y_offset
    if len(bitmap) != box_height or x_offset < 0 or x_offset + box_width > width or top < 0 or top + box_height > height:
        raise ValueError(f"{name}: the glyph does not fit the font's cell")
    cell = [bytearray(width) for _ in range(height)]
    for y, hex_row in enumerate(bitmap):
        value, bits = int(hex_row, 16), 4 * len(hex_row)
        for x in range(box_width):
            cell[top + y][x_offset + x] = (value >> (bits - 1 - x)) & 1
    return tuple(bytes(row) for row in cell)


def wrap(line: str, columns: int = COLUMNS) -> list[str]:
    """Split a line into rows of at most `columns` characters: after the last space that fits, or at
    `columns` when none does. The rows joined together are the line, so no character is lost."""
    rows = []
    while len(line) > columns:
        cut = line.rfind(" ", 0, columns) + 1 or columns
        rows.append(line[:cut])
        line = line[cut:]
    rows.append(line)
    return rows


def layout(text: str) -> list[tuple[int, str]]:
    """(palette index, row) for each row of text the picture shows."""
    rows = []
    for line in text.removesuffix("\n").split("\n"):
        colour = PROMPT_LINE if line.startswith(PROMPT) else TEXT
        rows.extend((colour, row) for row in wrap(line))
    return rows


class Image(NamedTuple):
    width: int
    height: int
    palette: tuple[tuple[int, int, int], ...]
    rows: tuple[bytes, ...]  # one palette index per pixel


def render(text: str, font: Font) -> Image:
    """Draw text as rows of glyphs on the background. A character the font lacks is an error."""
    rows = layout(text)
    missing = sorted({char for _, row in rows for char in row} - font.glyphs.keys())
    if missing:
        names = ", ".join(f"U+{ord(char):04X} {char!r}" for char in missing)
        raise ValueError(f"the demo font has no glyph for {names}; add one to {FONT_PATH.name}")
    line_height = font.height + LINE_GAP
    width = 2 * PADDING + COLUMNS * font.width
    pixels = [bytearray(width) for _ in range(2 * PADDING + len(rows) * line_height)]
    for index, (colour, row) in enumerate(rows):
        top = PADDING + index * line_height
        for column, char in enumerate(row):
            left = PADDING + column * font.width
            for y, ink in enumerate(font.glyphs[char]):
                pixels[top + y][left : left + font.width] = bytes(colour * bit for bit in ink)
    return Image(width, len(pixels), PALETTE, tuple(bytes(row) for row in pixels))


def read_back(image: Image, font: Font) -> list[str]:
    """The rows of text an image shows, read cell by cell against the font's glyphs, with trailing
    blanks dropped. Every glyph in the font is distinct, so there is one reading."""
    characters = {shape: char for char, shape in font.glyphs.items()}
    rows = []
    for top in range(PADDING, image.height - PADDING, font.height + LINE_GAP):
        row = []
        for left in range(PADDING, image.width - PADDING, font.width):
            shape = tuple(image.rows[top + y][left : left + font.width].translate(_INK) for y in range(font.height))
            if shape not in characters:
                raise ValueError(f"no glyph matches the cell at x={left}, y={top}")
            row.append(characters[shape])
        rows.append("".join(row).rstrip(" "))
    return rows


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def encode_png(image: Image, level: int = 9) -> bytes:
    """An 8-bit indexed-colour PNG with unfiltered scanlines and no ancillary chunks: no timestamp
    or other metadata, only the pixels."""
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 3, 0, 0, 0)
    scanlines = b"".join(b"\x00" + row for row in image.rows)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"PLTE", b"".join(bytes(rgb) for rgb in image.palette))
        + _chunk(b"IDAT", zlib.compress(scanlines, level))
        + _chunk(b"IEND", b"")
    )


def decode_png(data: bytes) -> Image:
    """The pixels of a PNG in the form encode_png writes. zlib builds compress the same pixels to
    different bytes, so images are compared by what they decode to, never byte for byte."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")
    chunks: dict[bytes, bytes] = {}
    compressed = []
    position = len(PNG_SIGNATURE)
    while position + 12 <= len(data):
        (length,) = struct.unpack_from(">I", data, position)
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        if len(body) != length or position + 12 + length > len(data):
            raise ValueError("the PNG file is truncated")
        (crc,) = struct.unpack_from(">I", data, position + 8 + length)
        if zlib.crc32(kind + body) != crc:
            raise ValueError(f"bad CRC in the {kind.decode('latin-1')!r} chunk")
        if kind == b"IDAT":
            compressed.append(body)
        else:
            chunks[kind] = body
        position += 12 + length
        if kind == b"IEND":
            break
    if not {b"IHDR", b"PLTE", b"IEND"} <= chunks.keys() or not compressed:
        raise ValueError("the PNG file lacks a required chunk")
    width, height, *form = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    if form != [8, 3, 0, 0, 0]:
        raise ValueError("not an 8-bit indexed-colour, non-interlaced PNG, as encode_png writes")
    try:
        scanlines = zlib.decompress(b"".join(compressed))
    except zlib.error as exc:
        raise ValueError(f"the PNG pixel data does not decompress: {exc}") from exc
    stride = width + 1
    if len(scanlines) != stride * height:
        raise ValueError("the PNG pixel data does not match its size")
    if any(scanlines[y * stride] != 0 for y in range(height)):
        raise ValueError("a scanline uses a PNG filter, which encode_png never writes")
    plte = chunks[b"PLTE"]
    palette = tuple(tuple(plte[i : i + 3]) for i in range(0, len(plte), 3))
    rows = tuple(scanlines[y * stride + 1 : (y + 1) * stride] for y in range(height))
    return Image(width, height, palette, rows)


def generated_files() -> dict[Path, bytes]:
    text = transcript()
    return {TEXT_PATH: text.encode("utf-8"), IMAGE_PATH: encode_png(render(text, load_font()))}


def _current(path: Path, content: bytes) -> bool:
    if not path.exists():
        return False
    if path.suffix == ".png":
        try:
            return decode_png(path.read_bytes()) == decode_png(content)
        except ValueError:
            return False
    return path.read_text(encoding="utf-8") == content.decode("utf-8")


def main(argv: list[str]) -> int:
    stale = []
    for path, content in generated_files().items():
        if _current(path, content):
            continue
        if "--check" in argv:
            stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.write_bytes(content)
            print(f"wrote {path.relative_to(ROOT).as_posix()}")
    if stale:
        print("out of date (run `python3 scripts/render_demo.py`): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
