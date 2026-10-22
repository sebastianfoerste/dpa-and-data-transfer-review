"""Command-line options: standard input, --format json, --fail-on, and failures that must exit 3
(no review state decided) instead of a code a pipeline would read as a review state."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import FIXTURES, ROOT, SAMPLE_PATH, run_cli


def stdin(data: bytes):
    return mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


class StandardInput(unittest.TestCase):
    def test_reads_the_dpa_from_standard_input(self):
        with stdin(SAMPLE_PATH.read_bytes()):
            code, stdout, stderr = run_cli("--input", "-")
        self.assertEqual((code, stderr), (2, ""))
        self.assertIn("**Review state: BLOCKED**", stdout)

    def test_input_is_utf8_whatever_the_locale(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["agreement"] = "Auftragsverarbeitungsvertrag (AVV) gemäß Art. 28 DSGVO"
        with stdin(json.dumps(dpa, ensure_ascii=False).encode("utf-8")):
            _, stdout, _ = run_cli("--input", "-")
        self.assertIn("# Auftragsverarbeitungsvertrag (AVV) gemäß Art. 28 DSGVO review packet", stdout)

    def test_errors_name_standard_input(self):
        with stdin(b"\xff\xfe"):
            code, _, stderr = run_cli("--input", "-")
        self.assertEqual(code, 3)
        self.assertIn("standard input is not valid UTF-8 text", stderr)
        with stdin(b'{"transfer": {}}'):
            code, _, stderr = run_cli("--input", "-")
        self.assertEqual(code, 3)
        self.assertIn("error: standard input breaks the input contract", stderr)


class Formats(unittest.TestCase):
    def test_json_prints_the_packet_as_committed(self):
        code, stdout, _ = run_cli("--input", SAMPLE_PATH, "--format", "json")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, (ROOT / "examples" / "review-packet.json").read_text(encoding="utf-8"))

    def test_markdown_is_the_default(self):
        _, stdout, _ = run_cli("--input", SAMPLE_PATH)
        self.assertEqual(stdout, (ROOT / "examples" / "review-packet.md").read_text(encoding="utf-8") + "\n")

    def test_nothing_is_printed_for_a_refused_input(self):
        for fmt in ("md", "json"):
            with self.subTest(format=fmt):
                code, stdout, _ = run_cli("--input", FIXTURES / "12-string-false-flag.json", "--format", fmt)
                self.assertEqual((code, stdout), (3, ""))


class FailOn(unittest.TestCase):
    def test_threshold(self):
        blocked, needs_review = SAMPLE_PATH, FIXTURES / "03-sccs-with-tia.json"
        cases = [
            (blocked, "needs_review", 2),
            (blocked, "blocked", 2),
            (blocked, "never", 0),
            (needs_review, "needs_review", 1),
            (needs_review, "blocked", 0),
            (needs_review, "never", 0),
        ]
        for path, fail_on, expected in cases:
            with self.subTest(input=path.name, fail_on=fail_on):
                self.assertEqual(run_cli("--input", path, "--quiet", "--fail-on", fail_on)[0], expected)

    def test_input_errors_exit_3_whatever_the_threshold(self):
        code, _, _ = run_cli("--input", FIXTURES / "11-misspelt-transfers-key.json", "--quiet", "--fail-on", "never")
        self.assertEqual(code, 3)


class Failures(unittest.TestCase):
    def test_an_unexpected_failure_exits_3_with_its_traceback(self):
        # Python itself exits 1 on an uncaught exception, which would read as NEEDS_REVIEW.
        with mock.patch("dpa_review.cli.build_packet", side_effect=RuntimeError("boom")):
            code, stdout, stderr = run_cli("--input", SAMPLE_PATH, "--fail-on", "blocked")
        self.assertEqual((code, stdout), (3, ""))
        self.assertIn("Traceback", stderr)
        self.assertIn("RuntimeError: boom", stderr)
        self.assertIn("no review state was decided", stderr)

    def test_an_output_that_cannot_be_written_exits_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "out"
            blocker.write_text("a file, not a directory", encoding="utf-8")
            code, _, stderr = run_cli("--input", SAMPLE_PATH, "--out", blocker, "--quiet")
        self.assertEqual(code, 3)
        self.assertIn(f"error: cannot write to {blocker}", stderr)
        self.assertNotIn("Traceback", stderr)


if __name__ == "__main__":
    unittest.main()
