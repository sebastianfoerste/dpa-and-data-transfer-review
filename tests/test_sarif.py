"""SARIF 2.1.0 output for GitHub code scanning: one result per open finding, at the line of the
fact that decided it, and an input.invalid error for every input with no review state."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from dpa_review import __version__
from tests.helpers import FIXTURES, SAMPLE_PATH, run_cli

LEVELS = {"none", "note", "warning", "error"}


def sarif(*args):
    code, stdout, stderr = run_cli(*args, "--format", "sarif")
    return code, json.loads(stdout), stderr


def line_containing(path, text):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return next(number for number, line in enumerate(lines, start=1) if text in line)


class Structure:
    """What GitHub code scanning requires of an uploaded SARIF log."""

    def assert_valid_sarif(self, log):
        self.assertEqual(log["version"], "2.1.0")
        self.assertTrue(log["$schema"].endswith("sarif-2.1.0.json"))
        self.assertEqual(len(log["runs"]), 1)
        driver = log["runs"][0]["tool"]["driver"]
        self.assertEqual((driver["name"], driver["version"]), ("dpa-review", __version__))
        rule_ids = [rule["id"] for rule in driver["rules"]]
        self.assertEqual(rule_ids, sorted(set(rule_ids)))
        fingerprints = set()
        for result in log["runs"][0]["results"]:
            self.assertEqual(driver["rules"][result["ruleIndex"]]["id"], result["ruleId"])
            self.assertIn(result["level"], LEVELS)
            self.assertTrue(result["message"]["text"].strip())
            location = result["locations"][0]["physicalLocation"]
            self.assertTrue(location["artifactLocation"]["uri"])
            self.assertGreaterEqual(location["region"]["startLine"], 1)
            fingerprints.add(result["partialFingerprints"]["dpaReviewFinding/v1"])
        self.assertEqual(len(fingerprints), len(log["runs"][0]["results"]), "fingerprints must be unique")


class OpenFindings(Structure, unittest.TestCase):
    def setUp(self):
        self.code, self.log, self.stderr = sarif("--input", SAMPLE_PATH)
        self.results = {result["ruleId"]: result for result in self.log["runs"][0]["results"]}

    def test_the_sample_log_is_valid_and_keeps_the_exit_code(self):
        self.assert_valid_sarif(self.log)
        self.assertEqual(self.code, 2)
        self.assertEqual(self.stderr, "")

    def test_one_result_per_open_finding(self):
        self.assertEqual(
            set(self.results),
            {
                "subprocessor.change_notice_and_objection",
                "subprocessor.flowdown",
                "transfer.subprocessor.support_tools_llc",
                "transfer.us",
            },
        )
        for result in self.results.values():
            self.assertEqual(result["level"], "error")  # all four are HIGH
            self.assertEqual(result["properties"]["review_state"], "BLOCKED")
            self.assertIn("Citation: GDPR Art.", result["message"]["text"])

    def test_results_point_at_the_line_that_decided_them(self):
        expected = {
            # The sample omits the change-notice flag, so the result points at the general authorisation.
            "subprocessor.change_notice_and_objection": '"subprocessor_authorization"',
            "subprocessor.flowdown": '"subprocessor_flowdown"',
            "transfer.subprocessor.support_tools_llc": "Support Tools LLC",
            "transfer.us": '"destinations"',
        }
        for rule_id, text in expected.items():
            with self.subTest(rule_id=rule_id):
                location = self.results[rule_id]["locations"][0]["physicalLocation"]
                self.assertEqual(location["artifactLocation"]["uri"], SAMPLE_PATH.as_posix())
                self.assertEqual(location["region"]["startLine"], line_containing(SAMPLE_PATH, text))

    def test_output_is_deterministic(self):
        self.assertEqual(sarif("--input", SAMPLE_PATH)[1], self.log)

    def test_levels_follow_severity(self):
        _, log, _ = sarif("--input", FIXTURES / "04-sccs-without-tia.json")
        levels = {result["ruleId"]: result["level"] for result in log["runs"][0]["results"]}
        self.assertEqual(levels, {"transfer.impact_assessment": "warning", "transfer.us": "note"})

    def test_a_cleared_input_has_no_results(self):
        code, log, _ = sarif("--input", FIXTURES / "01-eea-only.json")
        self.assertEqual(code, 0)
        self.assert_valid_sarif(log)
        self.assertEqual(log["runs"][0]["results"], [])

    def test_quiet_prints_nothing(self):
        self.assertEqual(run_cli("--input", SAMPLE_PATH, "--format", "sarif", "--quiet")[1], "")


class InvalidInputs(Structure, unittest.TestCase):
    def test_a_refused_input_still_yields_a_log_with_its_problems(self):
        fixture = FIXTURES / "11-misspelt-transfers-key.json"
        code, log, stderr = sarif("--input", fixture)
        self.assertEqual(code, 3)
        self.assertIn("breaks the input contract", stderr)
        self.assert_valid_sarif(log)
        results = log["runs"][0]["results"]
        self.assertEqual({result["ruleId"] for result in results}, {"input.invalid"})
        self.assertEqual({result["level"] for result in results}, {"error"})
        lines = [result["locations"][0]["physicalLocation"]["region"]["startLine"] for result in results]
        self.assertEqual(lines, [line_containing(fixture, '"transfer"'), 1])
        self.assertTrue(results[0]["message"]["text"].startswith("unknown key 'transfer'; did you mean 'transfers'?"))
        rule = log["runs"][0]["tool"]["driver"]["rules"][0]
        self.assertTrue(rule["helpUri"].endswith("docs/input-format.md"))

    def test_an_unreadable_input_is_reported_at_line_1(self):
        code, log, _ = sarif("--input", FIXTURES / "does-not-exist.json")
        self.assertEqual(code, 3)
        (result,) = log["runs"][0]["results"]
        self.assertIn("cannot read", result["message"]["text"])
        self.assertEqual(result["locations"][0]["physicalLocation"]["region"]["startLine"], 1)

    def test_a_register_log_covers_every_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("01-eea-only.json", "07-vague-breach-timing.json", "12-string-false-flag.json"):
                shutil.copy(FIXTURES / name, Path(tmp) / name)
            code, log, _ = sarif("--input", tmp)
        self.assertEqual(code, 3)
        self.assert_valid_sarif(log)
        by_file = {}
        for result in log["runs"][0]["results"]:
            uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            by_file.setdefault(Path(uri).name, []).append(result["ruleId"])
        self.assertEqual(
            by_file,
            {"07-vague-breach-timing.json": ["breach.processor_notifies"], "12-string-false-flag.json": ["input.invalid"]},
        )


if __name__ == "__main__":
    unittest.main()
