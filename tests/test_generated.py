"""The schema and the generated docs must match what scripts/generate.py writes (`make docs`)."""

import importlib.util
import unittest

from dpa_review.contract import violations
from dpa_review.review import build_packet
from tests.helpers import ROOT

_spec = importlib.util.spec_from_file_location("generate", ROOT / "scripts" / "generate.py")
generate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate)


class GeneratedFiles(unittest.TestCase):
    def test_committed_files_are_current(self):
        for path, content in generate.generated_files().items():
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertTrue(path.exists(), "missing; run `make docs`")
                self.assertEqual(path.read_text(encoding="utf-8"), content, "out of date; run `make docs`")

    def test_documented_minimal_input_is_valid_and_blocked(self):
        self.assertEqual(violations(generate.MINIMAL_INPUT), [])
        self.assertEqual(build_packet(generate.MINIMAL_INPUT).review_state, "BLOCKED")

    def test_check_mode_reports_nothing_stale(self):
        self.assertEqual(generate.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
