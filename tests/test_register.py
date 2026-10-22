"""Register mode: every *.json file directly inside a directory is reviewed, a summary ranks the
open rules across the register, and the exit code is the worst review state found."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURES, load, run_cli


class RegisterMode(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vendors = self.root / "vendors"
        self.vendors.mkdir()
        self.out = self.root / "out"

    def add(self, *names):
        for name in names:
            shutil.copy(FIXTURES / name, self.vendors / name)

    def review(self, *args):
        return run_cli("--input", self.vendors, "--out", self.out, "--quiet", *args)

    def summary(self):
        return load(self.out / "register-summary.json")

    def test_exit_code_is_the_worst_state(self):
        steps = [("01-eea-only.json", 0), ("03-sccs-with-tia.json", 1), ("07-vague-breach-timing.json", 2)]
        for name, expected in steps:
            with self.subTest(added=name):
                self.add(name)
                code, stdout, stderr = self.review()
                self.assertEqual(code, expected, stderr)
                self.assertEqual((stdout, stderr), ("", ""))

    def test_summary_counts_and_ranks_the_open_rules(self):
        self.add(
            "01-eea-only.json",
            "03-sccs-with-tia.json",
            "04-sccs-without-tia.json",
            "07-vague-breach-timing.json",
        )
        self.assertEqual(self.review()[0], 2)
        data = self.summary()
        self.assertEqual(data["schema"], "dpa-review.register-summary.v1")
        self.assertEqual(data["worst_review_state"], "BLOCKED")
        self.assertEqual(data["exit_code"], 2)
        self.assertEqual(
            data["counts"],
            {"dpas": 4, "blocked": 1, "needs_review": 2, "cleared_for_review": 1, "invalid_input": 0},
        )
        # transfer.us is open in two DPAs, so it ranks first although it is only LOW.
        ranked = [(rule["rule_id"], rule["dpa_count"]) for rule in data["open_rules"]]
        self.assertEqual(
            ranked,
            [("transfer.us", 2), ("breach.processor_notifies", 1), ("transfer.impact_assessment", 1)],
        )
        self.assertEqual(data["invalid_inputs"], [])

    def test_one_packet_directory_per_input(self):
        self.add("01-eea-only.json", "07-vague-breach-timing.json")
        self.review()
        self.assertEqual(
            sorted(path.name for path in self.out.iterdir()),
            ["01-eea-only", "07-vague-breach-timing", "register-summary.json", "register-summary.md"],
        )
        packet = load(self.out / "07-vague-breach-timing" / "review-packet.json")
        self.assertEqual(packet["review_state"], "BLOCKED")
        for name in ("review-packet.md", "transfer-evidence-graph.json", "transfer-evidence-graph.md"):
            self.assertTrue((self.out / "01-eea-only" / name).is_file(), name)

    def test_an_invalid_input_exits_3_and_is_listed(self):
        self.add("01-eea-only.json", "11-misspelt-transfers-key.json")
        code, _, stderr = self.review("--fail-on", "never")
        self.assertEqual(code, 3)
        self.assertIn("11-misspelt-transfers-key.json breaks the input contract", stderr)
        data = self.summary()
        self.assertEqual(data["exit_code"], 3)
        self.assertEqual(data["counts"]["invalid_input"], 1)
        self.assertEqual(data["counts"]["cleared_for_review"], 1)
        self.assertEqual(
            data["invalid_inputs"][0]["errors"][0], "line 43: unknown key 'transfer'; did you mean 'transfers'?"
        )
        self.assertFalse((self.out / "11-misspelt-transfers-key").exists())
        markdown = (self.out / "register-summary.md").read_text(encoding="utf-8")
        self.assertIn("**Worst review state: CLEARED_FOR_REVIEW** (exit code 3)", markdown)
        self.assertIn("## Inputs that break the input contract", markdown)

    def test_fail_on(self):
        self.add("03-sccs-with-tia.json")
        self.assertEqual(self.review()[0], 1)
        self.assertEqual(self.review("--fail-on", "blocked")[0], 0)
        self.add("07-vague-breach-timing.json")
        self.assertEqual(self.review("--fail-on", "blocked")[0], 2)
        self.assertEqual(self.review("--fail-on", "never")[0], 0)

    def test_only_json_files_directly_inside_are_reviewed(self):
        self.add("01-eea-only.json")
        (self.vendors / "notes.txt").write_text("not a DPA", encoding="utf-8")
        (self.vendors / "nested").mkdir()
        shutil.copy(FIXTURES / "07-vague-breach-timing.json", self.vendors / "nested" / "blocked.json")
        self.assertEqual(self.review()[0], 0)
        self.assertEqual(self.summary()["counts"]["dpas"], 1)

    def test_an_empty_register_exits_3(self):
        code, stdout, stderr = run_cli("--input", self.vendors)
        self.assertEqual(code, 3)
        self.assertEqual(stdout, "")
        self.assertIn("contains no *.json files to review", stderr)

    def test_out_must_not_be_the_register_itself(self):
        # The next run would review register-summary.json as a DPA.
        self.add("01-eea-only.json")
        with self.assertRaises(SystemExit) as caught:
            run_cli("--input", self.vendors, "--out", self.vendors)
        self.assertEqual(caught.exception.code, 3)
        self.assertEqual([path.name for path in self.vendors.iterdir()], ["01-eea-only.json"])

    def test_prints_the_summary_in_the_chosen_format(self):
        self.add("01-eea-only.json", "07-vague-breach-timing.json")
        code, stdout, _ = run_cli("--input", self.vendors)
        self.assertEqual(code, 2)
        self.assertIn("# DPA register review summary", stdout)
        self.assertIn("**Worst review state: BLOCKED** (exit code 2)", stdout)
        self.assertIn("| BLOCKED | Synthetic DPA: vague breach-notification timing review packet |", stdout)
        _, stdout, _ = run_cli("--input", self.vendors, "--format", "json")
        self.assertEqual(json.loads(stdout)["counts"]["blocked"], 1)

    def test_summary_is_deterministic(self):
        self.add("01-eea-only.json", "04-sccs-without-tia.json", "09-third-country-subprocessor-chain.json")
        self.review()
        first = {path.name: path.read_bytes() for path in self.out.rglob("*") if path.is_file()}
        shutil.rmtree(self.out)
        self.review()
        second = {path.name: path.read_bytes() for path in self.out.rglob("*") if path.is_file()}
        self.assertEqual(first, second)

    def test_pipes_in_titles_cannot_break_the_table(self):
        dpa = load(FIXTURES / "01-eea-only.json")
        dpa["agreement"] = "Vendor A | Vendor B"
        (self.vendors / "piped.json").write_text(json.dumps(dpa), encoding="utf-8")
        self.review()
        markdown = (self.out / "register-summary.md").read_text(encoding="utf-8")
        self.assertIn("| Vendor A \\| Vendor B review packet |", markdown)


if __name__ == "__main__":
    unittest.main()
