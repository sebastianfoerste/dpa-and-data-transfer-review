"""docs/demo.png, the picture at the top of README.md, must show what the CLI prints for the sample.

docs/demo.txt is the transcript of the command that `make demo` runs: the command, everything the
CLI prints, and its exit code. docs/demo.png draws that text. scripts/render_demo.py writes both
files from a live run. These tests fail when the text differs from a live run, when the image does
not show the text, or when one of the two changes without the other.
"""

import importlib.util
import unittest

from tests.helpers import ROOT

_spec = importlib.util.spec_from_file_location("render_demo", ROOT / "scripts" / "render_demo.py")
render_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_demo)

STALE = "out of date: run `python3 scripts/render_demo.py` and commit docs/demo.txt and docs/demo.png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class DemoText(unittest.TestCase):
    def test_captured_text_is_a_live_run_of_the_cli(self):
        self.assertEqual(render_demo.TEXT_PATH.read_text(encoding="utf-8"), render_demo.transcript(), STALE)

    def test_transcript_ends_with_the_exit_code_of_the_blocked_sample(self):
        self.assertTrue(render_demo.transcript().endswith("\n$ echo $?\n2\n"))

    def test_transcript_shows_the_command_make_demo_runs(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        recipe = makefile.split("\ndemo:\n", 1)[1].splitlines()[0].strip().lstrip("@")
        self.assertEqual(
            recipe.replace("$(PYTHONPATH)", "src").replace("$(PYTHON)", "python3"),
            render_demo.COMMAND,
        )


class DemoImage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.font = render_demo.load_font()
        cls.committed = render_demo.IMAGE_PATH.read_bytes()

    def test_file_is_a_png(self):
        self.assertTrue(self.committed.startswith(PNG_SIGNATURE), "docs/demo.png is not a PNG file")

    def test_image_shows_the_captured_text(self):
        text = render_demo.TEXT_PATH.read_text(encoding="utf-8")
        # assertTrue, not assertEqual: the repr of two images would run to megabytes.
        self.assertTrue(render_demo.decode_png(self.committed) == render_demo.render(text, self.font), STALE)

    def test_text_read_back_from_the_image_is_a_live_run_of_the_cli(self):
        shown = render_demo.read_back(render_demo.decode_png(self.committed), self.font)
        expected = [row.rstrip(" ") for _, row in render_demo.layout(render_demo.transcript())]
        self.assertEqual(shown, expected, STALE)

    def test_check_mode_reports_nothing_stale(self):
        self.assertEqual(render_demo.main(["--check"]), 0)


class Renderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.font = render_demo.load_font()

    def test_every_glyph_is_distinct_so_an_image_has_one_reading(self):
        shapes = list(self.font.glyphs.values())
        self.assertEqual(len(set(shapes)), len(shapes))
        self.assertIn("§", self.font.glyphs)

    def test_every_character_of_the_font_reads_back(self):
        characters = "".join(sorted(self.font.glyphs))
        image = render_demo.render(characters + "\n", self.font)
        self.assertEqual(render_demo.read_back(image, self.font), [characters])

    def test_one_changed_character_changes_the_image(self):
        font = self.font
        self.assertNotEqual(
            render_demo.render("Review state: BLOCKED\n", font),
            render_demo.render("Review state: BLOCKEB\n", font),
        )

    def test_wrapping_keeps_every_character(self):
        lines = render_demo.TEXT_PATH.read_text(encoding="utf-8").splitlines() + ["x" * 250, "a " * 120]
        for line in lines:
            with self.subTest(line=line[:40]):
                rows = render_demo.wrap(line)
                self.assertEqual("".join(rows), line)
                self.assertTrue(all(len(row) <= render_demo.COLUMNS for row in rows))
        self.assertEqual([len(row) for row in render_demo.wrap("x" * 250)], [100, 100, 50])

    def test_a_long_line_wraps_after_a_space(self):
        rows = render_demo.wrap("word " * 30)
        self.assertTrue(all(row.endswith(" ") for row in rows))

    def test_a_character_without_a_glyph_is_refused(self):
        with self.assertRaisesRegex(ValueError, r"U\+00FC"):
            render_demo.render("Müller Support GmbH\n", self.font)

    def test_png_round_trip_does_not_depend_on_the_compression(self):
        image = render_demo.render("$ echo $?\n2\n", self.font)
        for level in (1, 9):
            with self.subTest(level=level):
                self.assertEqual(render_demo.decode_png(render_demo.encode_png(image, level=level)), image)

    def test_a_corrupt_png_is_refused(self):
        data = bytearray(render_demo.encode_png(render_demo.render("x\n", self.font)))
        data[-20] ^= 0xFF  # inside the IDAT chunk, before its CRC
        with self.assertRaisesRegex(ValueError, "CRC"):
            render_demo.decode_png(bytes(data))


if __name__ == "__main__":
    unittest.main()
