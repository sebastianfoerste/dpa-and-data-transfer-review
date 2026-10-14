"""Exit codes of the CLI: 2, 1 and 0 are review states; 3 means no review state was decided."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dpa_review.cli import EXIT_NO_REVIEW_STATE, main

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "data" / "sample_dpa.json"


def _run(argv):
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
        code, out, _ = _run(["--input", str(SAMPLE_PATH), "--quiet"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_malformed_flag_exits_3_not_a_review_state(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["transfers"]["dpf_certified"] = True
        code, out, err = _run(["--input", self._write(dpa)])
        self.assertEqual(code, EXIT_NO_REVIEW_STATE)
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("transfers.dpf_certified must be an object", err)

    def test_unparseable_json_exits_3(self):
        code, _, err = _run(["--input", self._write("{not json")])
        self.assertEqual(code, 3)
        self.assertIn("cannot review", err)

    def test_missing_file_exits_3(self):
        code, _, _ = _run(["--input", str(Path(self.tmp.name) / "absent.json")])
        self.assertEqual(code, 3)

    def test_string_false_flag_exits_3_instead_of_passing_as_present(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["art28_clauses"]["subprocessor_flowdown"] = "false"
        code, out, err = _run(["--input", self._write(dpa)])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("art28_clauses.subprocessor_flowdown must be true or false", err)

    def test_wrong_shape_list_exits_3(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["subprocessors"] = ["not an object"]
        code, _, err = _run(["--input", self._write(dpa)])
        self.assertEqual(code, 3)
        self.assertIn("subprocessors must be a list of objects", err)

    def test_unexpected_failure_exits_3(self):
        with mock.patch("dpa_review.cli.build_packet", side_effect=RuntimeError("boom")):
            code, out, err = _run(["--input", str(SAMPLE_PATH)])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("Traceback", err)

    def test_null_transfers_section_gets_the_same_exit_with_or_without_out(self):
        # A null section counts as not recorded. The graph used to read it with dict methods,
        # so only a run with --out failed (exit 3), after the packet files were written.
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["transfers"] = None
        path = self._write(dpa)
        out_dir = Path(self.tmp.name) / "out"
        self.assertEqual(_run(["--input", path, "--quiet"])[0], 2)
        code, _, err = _run(["--input", path, "--quiet", "--out", str(out_dir)])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        self.assertTrue((out_dir / "transfer-evidence-graph.json").exists())

    def test_null_agreement_falls_back_to_the_default_title(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["agreement"] = None
        code, out, err = _run(["--input", self._write(dpa)])
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        self.assertTrue(out.startswith("# Data Processing Agreement review packet\n"))

    def test_agreement_that_is_not_a_string_exits_3_with_a_message(self):
        dpa = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        dpa["agreement"] = ["Synthetic DPA"]
        code, out, err = _run(["--input", self._write(dpa)])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("agreement must be a string", err)
        self.assertNotIn("Traceback", err)

    def test_failure_while_building_the_graph_writes_no_output(self):
        out_dir = Path(self.tmp.name) / "out"
        with mock.patch(
            "dpa_review.cli.build_transfer_evidence_graph", side_effect=RuntimeError("boom")
        ):
            code, out, _ = _run(["--input", str(SAMPLE_PATH), "--out", str(out_dir)])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertFalse(out_dir.exists())

    def test_usage_error_exits_3_not_2(self):
        code, _, err = _run([])
        self.assertEqual(code, 3)
        self.assertIn("--input", err)


if __name__ == "__main__":
    unittest.main()
