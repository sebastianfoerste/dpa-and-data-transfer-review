"""Every fixture in tests/fixtures/ must produce the review state, exit code and open rules that
tests/fixtures/expected.json records; docs/conformance.md renders the same table."""

import unittest

from dpa_review.review import OPEN_STATUSES, build_packet
from tests.helpers import FIXTURES, load, run_cli

EXPECTED = load(FIXTURES / "expected.json")


class ConformanceSuite(unittest.TestCase):
    def test_every_fixture_has_an_expected_result(self):
        fixtures = {path.name for path in FIXTURES.glob("*.json")} - {"expected.json"}
        self.assertEqual(fixtures, set(EXPECTED))
        self.assertGreaterEqual(len(fixtures), 10)

    def test_fixtures(self):
        for name, case in EXPECTED.items():
            with self.subTest(fixture=name):
                code, stdout, stderr = run_cli("--input", FIXTURES / name, "--quiet")
                self.assertEqual(code, case["exit_code"], stderr)
                self.assertEqual(stdout, "")
                if case["exit_code"] == 3:
                    self.assertIsNone(case["review_state"])
                    for fragment in case["errors"]:
                        self.assertIn(fragment, stderr)
                    continue
                self.assertEqual(stderr, "")
                packet = build_packet(load(FIXTURES / name))
                self.assertEqual(packet.review_state, case["review_state"])
                opened = sorted(f.rule_id for f in packet.findings if f.status in OPEN_STATUSES)
                self.assertEqual(opened, sorted(case["open_rules"]))

    def test_every_state_and_exit_code_is_covered(self):
        self.assertEqual({case["exit_code"] for case in EXPECTED.values()}, {0, 1, 2, 3})


if __name__ == "__main__":
    unittest.main()
