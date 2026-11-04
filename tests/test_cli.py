"""Exit codes of the CLI: 2, 1 and 0 are review states; 3 means no review state was decided.

The first tests run the CLI as a real subprocess; the later ones run it in this process, so that
they can replace a function with a failing one.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dpa_review.checks import InvalidInputError
from dpa_review.cli import EXIT_NO_REVIEW_STATE, main

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_dpa.json"
SAMPLE_PATH = SAMPLE


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


class UsageErrors(unittest.TestCase):
    def test_usage_errors_exit_3_not_a_review_state(self):
        # argparse exits 2 on a usage error, which a pipeline would read as BLOCKED.
        for args in ((), ("--input", str(SAMPLE), "--no-such-flag")):
            with self.subTest(args=args):
                result = _run(*args)
                self.assertEqual(result.returncode, 3)
                self.assertIn("usage:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)


class Version(unittest.TestCase):
    def test_version(self):
        result = _run("--version")
        self.assertEqual(result.returncode, 0)
        self.assertRegex(result.stdout, r"^dpa-review \d+\.\d+\.\d+\n$")


class ReviewExitCodes(unittest.TestCase):
    def test_sample_dpa_is_blocked(self):
        result = _run("--input", str(SAMPLE), "--quiet")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")


def _run_in_process(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as exc:  # argparse exits on usage errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class CliExitCodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, payload):
        path = Path(self.tmp.name) / "dpa.json"
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return str(path)

    def test_blocked_sample_exits_2(self):
        code, out, _ = _run_in_process(["--input", str(SAMPLE_PATH), "--quiet"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_malformed_flag_exits_3_not_a_review_state(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["transfers"]["dpf_certified"] = True
        code, out, err = _run_in_process(["--input", self._write(dpa)])
        self.assertEqual(code, EXIT_NO_REVIEW_STATE)
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("transfers.dpf_certified must be an object", err)

    def test_unparseable_json_exits_3(self):
        code, _, err = _run_in_process(["--input", self._write("{not json")])
        self.assertEqual(code, 3)
        self.assertIn("is not valid JSON", err)

    def test_missing_file_exits_3(self):
        code, _, _ = _run_in_process(["--input", str(Path(self.tmp.name) / "absent.json")])
        self.assertEqual(code, 3)

    def test_string_false_flag_exits_3_instead_of_passing_as_present(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["art28_clauses"]["subprocessor_flowdown"] = "false"
        code, out, err = _run_in_process(["--input", self._write(dpa)])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("art28_clauses.subprocessor_flowdown must be true or false", err)

    def test_wrong_shape_list_exits_3(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["subprocessors"] = ["not an object"]
        code, _, err = _run_in_process(["--input", self._write(dpa)])
        self.assertEqual(code, 3)
        self.assertIn("subprocessors must be a list of objects", err)

    def test_unexpected_failure_exits_3(self):
        with mock.patch("dpa_review.cli.build_packet", side_effect=RuntimeError("boom")):
            code, out, err = _run_in_process(["--input", str(SAMPLE_PATH)])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("Traceback", err)

    def test_null_transfers_section_gets_the_same_exit_with_or_without_out(self):
        # The graph used to read a null section with dict methods, so only a run with --out
        # failed (exit 3), after the packet files were written. The input contract now refuses
        # a null required section before any rule runs, with or without --out.
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["transfers"] = None
        path = self._write(dpa)
        out_dir = Path(self.tmp.name) / "out"
        self.assertEqual(_run_in_process(["--input", path, "--quiet"])[0], 3)
        code, _, err = _run_in_process(["--input", path, "--quiet", "--out", str(out_dir)])
        self.assertEqual(code, 3)
        self.assertIn("transfers is required and cannot be null", err)
        self.assertFalse(out_dir.exists())

    def test_omitted_agreement_falls_back_to_the_default_title(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        del dpa["agreement"]
        code, out, err = _run_in_process(["--input", self._write(dpa)])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        self.assertTrue(out.startswith("# Data Processing Agreement review packet\n"))

    def test_null_agreement_exits_3_with_a_message(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["agreement"] = None
        path = self._write(dpa)
        code, out, err = _run_in_process(["--input", path])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("agreement cannot be null", err)
        out_dir = Path(self.tmp.name) / "out"
        code, out, err = _run_in_process(["--input", path, "--out", str(out_dir)])
        self.assertEqual((code, out), (3, ""))
        self.assertIn("agreement cannot be null", err)
        self.assertFalse(out_dir.exists())

    def test_agreement_that_is_not_a_string_exits_3_with_a_message(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["agreement"] = ["Synthetic DPA"]
        code, out, err = _run_in_process(["--input", self._write(dpa)])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("agreement must be a string", err)
        self.assertNotIn("Traceback", err)

    def test_failure_while_building_the_graph_writes_no_output(self):
        out_dir = Path(self.tmp.name) / "out"
        with mock.patch(
            "dpa_review.cli.build_transfer_evidence_graph", side_effect=RuntimeError("boom")
        ):
            code, out, _ = _run_in_process(["--input", str(SAMPLE_PATH), "--out", str(out_dir)])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertFalse(out_dir.exists())

    def test_input_the_rules_refuse_exits_3_without_a_traceback(self):
        # The input contract refuses what the rules refuse; a refusal from the rules themselves is
        # still reported as an input error, not as a crash.
        with mock.patch(
            "dpa_review.cli.build_packet",
            side_effect=InvalidInputError("processing.duration must be a description or true/false, got 'no'."),
        ):
            code, out, err = _run_in_process(["--input", str(SAMPLE_PATH)])
        self.assertEqual((code, out), (3, ""))
        self.assertIn("processing.duration must be a description or true/false", err)
        self.assertNotIn("Traceback", err)

    def test_description_that_reads_as_yes_or_no_exits_3_with_its_line(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["processing"]["subject_matter"] = "false"
        code, out, err = _run_in_process(["--input", self._write(json.dumps(dpa, indent=2))])
        self.assertEqual((code, out), (3, ""))
        self.assertRegex(err, r"line \d+: processing.subject_matter must be a description or true/false")

    def test_usage_error_exits_3_not_2(self):
        code, _, err = _run_in_process([])
        self.assertEqual(code, 3)
        self.assertIn("--input", err)


if __name__ == "__main__":
    unittest.main()
