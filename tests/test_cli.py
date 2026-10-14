"""Exit-code tests for the command-line interface (run as a real subprocess)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_dpa.json"


def _run(*args):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run(
        [sys.executable, "-m", "dpa_review.cli", *args],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )


class InputErrors(unittest.TestCase):
    def _assert_clean_error(self, result, fragment):
        self.assertEqual(result.returncode, 3)
        self.assertIn("error:", result.stderr)
        self.assertIn(fragment, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def _write(self, content, mode="w"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "in.json"
        if "b" in mode:
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return str(path)

    def test_invalid_json(self):
        self._assert_clean_error(_run("--input", self._write("{not json"), "--quiet"), "not valid JSON")

    def test_empty_file(self):
        self._assert_clean_error(_run("--input", self._write(""), "--quiet"), "not valid JSON")

    def test_non_object_top_level(self):
        self._assert_clean_error(_run("--input", self._write("[]"), "--quiet"), "JSON object")

    def test_missing_file(self):
        self._assert_clean_error(_run("--input", "does-not-exist.json", "--quiet"), "cannot read")

    def test_invalid_utf8(self):
        path = self._write(b"\xff\xfe\x00{", mode="wb")
        self._assert_clean_error(_run("--input", path, "--quiet"), "UTF-8")

    def test_no_output_written_on_error(self):
        with tempfile.TemporaryDirectory() as out:
            result = _run("--input", self._write("{"), "--out", out, "--quiet")
            self.assertEqual(result.returncode, 3)
            self.assertEqual(list(Path(out).iterdir()), [])


class ReviewExitCodes(unittest.TestCase):
    def test_sample_dpa_is_blocked(self):
        result = _run("--input", str(SAMPLE), "--quiet")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
