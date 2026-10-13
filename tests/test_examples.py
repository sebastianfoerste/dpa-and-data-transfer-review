"""The committed sample output must be exactly what the demo produces today.

`make demo` writes examples/ from data/sample_dpa.json. If a rule change alters the
output, these tests fail until examples/ (and the README excerpt) are regenerated, so
the published sample can never drift from the code.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from dpa_review.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
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


if __name__ == "__main__":
    unittest.main()
