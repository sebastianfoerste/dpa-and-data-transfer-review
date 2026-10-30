"""One derivation of the rule id transfer.subprocessor.<name>, shared by the check that raises the
finding, the fact mapping that attaches its evidence and the graph edge that carries it.

The three used to derive the id each on their own. For a name with punctuation or a non-ASCII
letter the graph's id named no finding, so it drew an open HIGH transfer as "pass".
"""

import random
import unittest

from dpa_review.checks import check_transfers, subprocessor_rule_id
from dpa_review.contract import _name_key, violations
from dpa_review.facts import evidence_for, rule_facts
from dpa_review.review import build_packet
from tests.helpers import SAMPLE_PATH, load

PREFIX = "transfer.subprocessor."


def sample_with(*names: str) -> dict:
    """The sample with sub-processors in the US, one per name, recorded with no transfer mechanism."""
    dpa = load(SAMPLE_PATH)
    dpa["subprocessors"] = [
        {"name": name, "country": "US", "purpose": "support desk", "transfer_mechanism": "none"} for name in names
    ]
    return dpa


class SubprocessorRuleId(unittest.TestCase):
    def test_names_in_the_sample_and_fixtures_keep_their_ids(self):
        for name, rule_id in {
            "Support Tools LLC": "transfer.subprocessor.support_tools_llc",
            "Analytics KK": "transfer.subprocessor.analytics_kk",
            "Example Analytics Pvt Ltd": "transfer.subprocessor.example_analytics_pvt_ltd",
            "Example Support Inc": "transfer.subprocessor.example_support_inc",
        }.items():
            with self.subTest(name=name):
                self.assertEqual(subprocessor_rule_id(name), rule_id)

    def test_each_run_of_other_characters_becomes_one_underscore(self):
        for name, rule_id in {
            "Support Tools, LLC": "transfer.subprocessor.support_tools_llc",
            "Support-Tools LLC": "transfer.subprocessor.support_tools_llc",
            "  Support_Tools  LLC.  ": "transfer.subprocessor.support_tools_llc",
            "Example K.K.": "transfer.subprocessor.example_k_k",
            "Müller Support GmbH": "transfer.subprocessor.müller_support_gmbh",
            "A | B\n## H": "transfer.subprocessor.a_b_h",
        }.items():
            with self.subTest(name=name):
                self.assertEqual(subprocessor_rule_id(name), rule_id)

    def test_the_check_the_facts_and_the_evidence_use_the_same_id(self):
        names = ["Support Tools, LLC", "Example K.K.", "Müller Support GmbH"]
        dpa = sample_with(*names)
        dpa["evidence"] = {
            f"subprocessors[{index}].transfer_mechanism": {"clause": f"Annex 3.{index}", "quote": "..."}
            for index in range(len(names))
        }
        self.assertEqual(violations(dpa), [])
        found = [f.rule_id for f in check_transfers(dpa) if f.rule_id.startswith(PREFIX)]
        self.assertEqual(found, [subprocessor_rule_id(name) for name in names])
        packet = build_packet(dpa)
        for index, rule_id in enumerate(found):
            with self.subTest(rule_id=rule_id):
                self.assertEqual(rule_facts(dpa, rule_id), [("subprocessors", index)])
                self.assertEqual(
                    evidence_for(dpa, rule_id),
                    [{"fact": f"subprocessors[{index}].transfer_mechanism", "clause": f"Annex 3.{index}", "quote": "..."}],
                )
                self.assertIn(rule_id, packet.evidence)

    def test_names_the_contract_accepts_together_never_share_an_id(self):
        # Without its underscores the id is the key the contract compares names by, so two names
        # with the same id have the same key, and the contract refuses the second one.
        alphabet = "aAzZ09 _-.,|'&()/\tßẞüÜİıKﬁΣσςͅꭰᎠ²½①"
        rng = random.Random(20261030)
        names = ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8))) for _ in range(3000)]
        names += ["Straße", "STRASSE", "ﬁrm", "FIRM", "Müller", "Muller", "M-ller", "aͅ", "a"]
        by_id: dict[str, str] = {}
        for name in names:
            rule_id = subprocessor_rule_id(name)
            with self.subTest(name=name):
                self.assertTrue(rule_id.startswith(PREFIX))
                slug = rule_id[len(PREFIX):]
                self.assertEqual(slug.replace("_", ""), _name_key(name))
                self.assertFalse(slug.startswith("_") or slug.endswith("_") or "__" in slug)
                if rule_id in by_id:
                    self.assertEqual(_name_key(by_id[rule_id]), _name_key(name))
                by_id.setdefault(rule_id, name)

    def test_the_contract_refuses_names_that_would_share_an_id(self):
        dpa = sample_with("Support Tools LLC", "Support-Tools, LLC")
        self.assertEqual(len(violations(dpa)), 1)
        self.assertIn("repeats subprocessors[0].name", violations(dpa)[0].message)


if __name__ == "__main__":
    unittest.main()
