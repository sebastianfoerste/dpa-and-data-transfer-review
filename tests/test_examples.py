"""The committed sample output must be exactly what the demo produces today.

`make demo` writes examples/ from data/sample_dpa.json. If a rule change alters the
output, these tests fail until examples/ (and the README excerpt) are regenerated, so
the published sample can never drift from the code.
"""

import contextlib
import hashlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from dpa_review.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
DOCS = ROOT / "docs"
OUTPUTS = (
    "review-packet.md",
    "review-packet.json",
    "transfer-evidence-graph.json",
    "transfer-evidence-graph.md",
)


class CommittedExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with contextlib.redirect_stdout(io.StringIO()):
            cls.exit_code = main(["--input", str(ROOT / "data" / "sample_dpa.json"), "--out", cls.tmp.name])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_demo_blocks_the_sample(self):
        self.assertEqual(self.exit_code, 2)

    def test_committed_examples_match_the_demo_output(self):
        for name in OUTPUTS:
            with self.subTest(file=name):
                fresh = (Path(self.tmp.name) / name).read_bytes()
                committed = (EXAMPLES / name).read_bytes()
                self.assertEqual(committed, fresh, f"examples/{name} is stale; run `make demo`")

    def test_readme_excerpt_matches_the_committed_packet(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        packet = (EXAMPLES / "review-packet.md").read_text(encoding="utf-8")
        excerpt = packet.split("\n## Full checklist")[0].rstrip("\n")
        self.assertIn("```\n" + excerpt + "\n```", readme)


# The line make prints after a failing recipe: GNU make 4 names the Makefile line, make 3.81 does not.
MAKE_FAILURE = re.compile(r"make: \*\*\* \[(?:Makefile:\d+: )?demo\] Error (\d+)\n")


class DemoImage(unittest.TestCase):
    """docs/demo.png is a rendering of docs/demo.txt, the captured terminal output of `make demo`.

    A test cannot read the image, so docs/demo.sha256 records the text and the image it was
    rendered into. Changing either without the other, or letting the text drift from the
    demo, fails here.
    """

    def test_captured_text_is_the_live_demo_output(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["--input", str(ROOT / "data" / "sample_dpa.json")])
        printed = stdout.getvalue()
        captured = (DOCS / "demo.txt").read_text(encoding="utf-8")
        self.assertEqual(
            captured[: len(printed)],
            printed,
            "docs/demo.txt is stale: capture it with `make demo > docs/demo.txt 2>&1` and re-render docs/demo.png",
        )
        trailer = MAKE_FAILURE.fullmatch(captured[len(printed):])
        self.assertIsNotNone(trailer, "docs/demo.txt must end with make's report of the CLI's exit code")
        self.assertEqual(int(trailer.group(1)), exit_code)

    def test_image_was_rendered_from_the_captured_text(self):
        recorded = {}
        for line in (DOCS / "demo.sha256").read_text(encoding="utf-8").splitlines():
            digest, name = line.split(maxsplit=1)
            recorded[name.lstrip("*")] = digest
        for name in ("demo.txt", "demo.png"):
            with self.subTest(file=name):
                self.assertEqual(
                    hashlib.sha256((DOCS / name).read_bytes()).hexdigest(),
                    recorded.get(name),
                    f"docs/{name} changed since docs/demo.png was rendered from docs/demo.txt: re-render "
                    "the image from the text, then run `sha256sum demo.txt demo.png > demo.sha256` in docs/",
                )


if __name__ == "__main__":
    unittest.main()
