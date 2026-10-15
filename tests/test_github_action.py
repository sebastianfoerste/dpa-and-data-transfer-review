"""The GitHub Action (action.yml and scripts/github_action.py): the step exits with dpa-review's
own exit code under fail-on, and writes the packets, the job summary, the step outputs, a SARIF
log and one annotation per open finding. Inputs reach the script only as environment variables."""

import contextlib
import importlib.util
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURES, ROOT, SAMPLE_PATH

_spec = importlib.util.spec_from_file_location("github_action", ROOT / "scripts" / "github_action.py")
github_action = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(github_action)

ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")


def read_outputs(path):
    """Parse the name<<DELIMITER ... DELIMITER blocks the step appends to $GITHUB_OUTPUT."""
    outputs, lines = {}, Path(path).read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        name, delimiter = lines[index].split("<<", 1)
        end = lines.index(delimiter, index + 1)
        outputs[name] = "\n".join(lines[index + 1:end])
        index = end + 1
    return outputs


def declared(section):
    """The keys action.yml declares under its top-level `inputs:` or `outputs:`."""
    block = re.search(rf"^{section}:\n((?:  .*\n|\n)+)", ACTION, re.MULTILINE).group(1)
    return re.findall(r"^  ([a-z-]+):$", block, re.MULTILINE)


class Step(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def step(self, **inputs):
        """Run the step as the runner would: (exit code, stdout, stderr, outputs, job summary)."""
        environ = {
            "GITHUB_OUTPUT": str(self.tmp / "github-output"),
            "GITHUB_STEP_SUMMARY": str(self.tmp / "step-summary.md"),
            "DPA_REVIEW_OUT": str(self.tmp / "out"),
        }
        environ.update({f"DPA_REVIEW_{name.upper()}": str(value) for name, value in inputs.items()})
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = github_action.run(environ)
        summary = (self.tmp / "step-summary.md").read_text(encoding="utf-8")
        return code, out.getvalue(), err.getvalue(), read_outputs(self.tmp / "github-output"), summary


class ExitCodes(Step):
    def test_a_blocked_dpa_fails_the_step(self):
        code, stdout, stderr, outputs, summary = self.step(input=SAMPLE_PATH)
        self.assertEqual((code, stderr), (2, ""))
        self.assertEqual((outputs["review-state"], outputs["exit-code"]), ("BLOCKED", "2"))
        self.assertEqual(outputs["summary"], str(self.tmp / "out" / "review-packet.md"))
        self.assertEqual(summary, (ROOT / "examples" / "review-packet.md").read_text(encoding="utf-8") + "\n")
        self.assertTrue((self.tmp / "out" / "transfer-evidence-graph.md").is_file())

    def test_fail_on_defaults_to_blocked(self):
        needs_review = FIXTURES / "03-sccs-with-tia.json"
        cases = [({}, 0), ({"fail_on": "needs_review"}, 1), ({"fail_on": "never"}, 0)]
        for extra, expected in cases:
            with self.subTest(**extra):
                code, _, _, outputs, _ = self.step(input=needs_review, **extra)
                self.assertEqual(code, expected)
                self.assertEqual(outputs["review-state"], "NEEDS_REVIEW")
                self.assertEqual(outputs["exit-code"], str(expected))

    def test_a_register_reports_its_worst_state(self):
        vendors = self.tmp / "vendors"
        vendors.mkdir()
        for name in ("01-eea-only.json", "03-sccs-with-tia.json", "07-vague-breach-timing.json"):
            shutil.copy(FIXTURES / name, vendors / name)
        code, _, _, outputs, summary = self.step(input=vendors, fail_on="never")
        self.assertEqual(code, 0)
        self.assertEqual(outputs["review-state"], "BLOCKED")
        self.assertEqual(outputs["summary"], str(self.tmp / "out" / "register-summary.md"))
        self.assertEqual(summary, (self.tmp / "out" / "register-summary.md").read_text(encoding="utf-8") + "\n")
        self.assertIn("**Worst review state: BLOCKED** (exit code 0)", summary)


class NoReviewState(Step):
    def test_an_input_that_breaks_the_contract_fails_whatever_fail_on(self):
        code, stdout, stderr, outputs, summary = self.step(
            input=FIXTURES / "11-misspelt-transfers-key.json", fail_on="never"
        )
        self.assertEqual(code, 3)
        self.assertIn("unknown key 'transfer'; did you mean 'transfers'?", stderr)
        self.assertEqual((outputs["review-state"], outputs["exit-code"], outputs["summary"]), ("", "3", ""))
        self.assertIn("**No review state was decided**", summary)
        self.assertIn("unknown key 'transfer'; did you mean 'transfers'?", summary)
        self.assertRegex(stdout, r"(?m)^::error file=[^,]*11-misspelt-transfers-key\.json,line=\d+,title=input\.invalid::")

    def test_errors_are_printed_once(self):
        _, _, stderr, _, _ = self.step(input=FIXTURES / "12-string-false-flag.json")
        self.assertEqual(stderr.count("must be true or false"), 1)

    def test_a_missing_input_is_a_usage_error(self):
        code, _, stderr, outputs, summary = self.step(input="")
        self.assertEqual(code, 3)
        self.assertIn("--input is required", stderr)
        self.assertEqual(outputs["sarif"], "")
        self.assertIn("(no input given)", summary)


class Annotations(Step):
    def test_one_annotation_per_open_finding_on_its_line(self):
        _, stdout, _, _, _ = self.step(input=SAMPLE_PATH)
        commands = stdout.splitlines()
        self.assertEqual(len(commands), 3)
        lines = SAMPLE_PATH.read_text(encoding="utf-8").splitlines()
        for command in commands:
            match = re.fullmatch(r"::error file=([^,]+),line=(\d+),title=([^:]+)::(.+)", command)
            self.assertIsNotNone(match, command)
            self.assertTrue(match.group(1).endswith("sample_dpa.json"))
            if match.group(3) == "subprocessor.flowdown":
                self.assertIn('"subprocessor_flowdown"', lines[int(match.group(2)) - 1])

    def test_errors_come_first(self):
        _, stdout, _, _, _ = self.step(input=FIXTURES / "04-sccs-without-tia.json")
        kinds = [line.split(" ", 1)[0] for line in stdout.splitlines()]
        self.assertEqual(kinds, sorted(kinds, key=["::error", "::warning", "::notice"].index))
        self.assertIn("::warning", kinds)  # transfer.impact_assessment is MEDIUM
        self.assertIn("::notice", kinds)  # transfer.us is LOW

    def test_annotate_false_prints_nothing(self):
        _, stdout, _, _, _ = self.step(input=SAMPLE_PATH, annotate="false")
        self.assertEqual(stdout, "")

    def test_values_are_escaped(self):
        log = {
            "runs": [
                {
                    "results": [
                        {
                            "ruleId": "rule,with:separators",
                            "level": "note",
                            "message": {"text": "100% sure\nsecond line"},
                            "locations": [
                                {"physicalLocation": {"artifactLocation": {"uri": "a,b:c.json"}, "region": {"startLine": 4}}}
                            ],
                        }
                    ]
                }
            ]
        }
        self.assertEqual(
            github_action.annotations(log),
            ["::notice file=a%2Cb%3Ac.json,line=4,title=rule%2Cwith%3Aseparators::100%25 sure%0Asecond line"],
        )


class Sarif(Step):
    def test_the_sarif_log_is_written_where_asked(self):
        path = self.tmp / "reports" / "dpa-review.sarif"
        code, _, _, outputs, _ = self.step(input=SAMPLE_PATH, sarif=path)
        self.assertEqual((code, outputs["sarif"]), (2, str(path)))
        log = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(log["version"], "2.1.0")
        self.assertEqual(len(log["runs"][0]["results"]), 3)

    def test_no_sarif_unless_asked(self):
        _, _, _, outputs, _ = self.step(input=SAMPLE_PATH)
        self.assertEqual(outputs["sarif"], "")
        self.assertEqual(sorted(path.name for path in self.tmp.iterdir()), ["github-output", "out", "step-summary.md"])


class ActionMetadata(unittest.TestCase):
    def test_every_input_reaches_the_script_as_an_environment_variable(self):
        script = (ROOT / "scripts" / "github_action.py").read_text(encoding="utf-8")
        for name in declared("inputs"):
            variable = "DPA_REVIEW_" + name.upper().replace("-", "_")
            with self.subTest(input=name):
                self.assertIn(f"{variable}: ${{{{ inputs.{name} }}}}", ACTION)
                self.assertIn(f'"{variable}"', script)

    def test_no_expression_is_interpolated_into_the_shell(self):
        run_lines = re.findall(r"^\s+run: (.*)$", ACTION, re.MULTILINE)
        self.assertEqual(run_lines, ['python3 "$GITHUB_ACTION_PATH/scripts/github_action.py"'])

    def test_every_output_is_one_the_script_sets(self):
        script = (ROOT / "scripts" / "github_action.py").read_text(encoding="utf-8")
        for name in declared("outputs"):
            with self.subTest(output=name):
                self.assertIn(f"value: ${{{{ steps.review.outputs.{name} }}}}", ACTION)
                self.assertIn(f'"{name}": ', script)

    def test_the_documented_defaults_are_the_scripts(self):
        self.assertIn(f"default: {github_action.DEFAULT_OUT}\n", ACTION)
        self.assertIn(f"default: {github_action.DEFAULT_FAIL_ON}\n", ACTION)

    def test_the_docs_describe_every_input_and_output(self):
        docs = (ROOT / "docs" / "github-action.md").read_text(encoding="utf-8")
        for name in declared("inputs") + declared("outputs"):
            with self.subTest(name=name):
                self.assertIn(f"| `{name}` |", docs)


if __name__ == "__main__":
    unittest.main()
