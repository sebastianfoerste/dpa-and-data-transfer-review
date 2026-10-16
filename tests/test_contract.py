"""The input contract: unknown keys, missing sections and wrong types exit 3 before any rule runs."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from dpa_review.contract import ContractError, json_schema, schema_text, validate, violations
from dpa_review.review import build_packet
from tests.helpers import FIXTURES, ROOT, SAMPLE_PATH, load, run_cli

SAMPLE = load(SAMPLE_PATH)

try:
    import jsonschema
except ImportError:  # the stdlib-only suite skips the JSON Schema cross-checks
    jsonschema = None


def messages(dpa):
    return [violation.message for violation in violations(dpa)]


def changed(**changes):
    """A copy of the sample with dotted-path changes applied; None deletes the key."""
    dpa = copy.deepcopy(SAMPLE)
    for path, value in changes.items():
        *parents, last = path.split("__")
        target = dpa
        for part in parents:
            target = target[int(part)] if part.isdigit() else target[part]
        if value is DELETE:
            del target[last]
        else:
            target[int(last) if last.isdigit() else last] = value
    return dpa


DELETE = object()


class Conforming(unittest.TestCase):
    def test_sample_conforms(self):
        self.assertEqual(violations(SAMPLE), [])

    def test_optional_flags_may_be_null(self):
        self.assertEqual(messages(changed(art28_clauses__subprocessor_flowdown=None, ccpa=None)), [])

    def test_a_schema_key_lets_editors_attach_the_schema(self):
        self.assertEqual(messages({"$schema": "../schema/dpa.schema.json", **SAMPLE}), [])
        self.assertIn("$schema must be a string, got 1.", messages({"$schema": 1, **SAMPLE}))
        self.assertIn("unknown key 'schema'; did you mean '$schema'?", messages({"schema": "x", **SAMPLE}))

    def test_validate_raises_with_every_violation(self):
        with self.assertRaises(ContractError) as caught:
            validate({})
        self.assertEqual(len(caught.exception.violations), 5)


class FailOpenInputs(unittest.TestCase):
    def test_misspelt_section_is_refused_with_a_suggestion(self):
        dpa = changed()
        dpa["transfer"] = dpa.pop("transfers")
        found = messages(dpa)
        self.assertIn("unknown key 'transfer'; did you mean 'transfers'?", found)
        self.assertTrue(any(message.startswith("missing required key 'transfers'") for message in found))

    def test_misspelt_nested_key_names_the_full_path(self):
        dpa = changed(art28_clauses__subprocessor_flowdown=DELETE)
        dpa["art28_clauses"]["subprocessor_flow_down"] = True
        self.assertIn(
            "unknown key 'art28_clauses.subprocessor_flow_down'; did you mean 'art28_clauses.subprocessor_flowdown'?",
            messages(dpa),
        )

    def test_string_false_is_not_a_flag(self):
        self.assertIn(
            "art28_clauses.subprocessor_flowdown must be true or false, got 'false'.",
            messages(changed(art28_clauses__subprocessor_flowdown="false")),
        )

    def test_required_sections_and_keys(self):
        for path in ("processing", "art28_clauses", "breach_notification", "subprocessors", "transfers"):
            with self.subTest(path=path):
                self.assertTrue(any(f"missing required key '{path}'" in m for m in messages(changed(**{path: DELETE}))))
        self.assertTrue(
            any("'transfers.destinations'" in m for m in messages(changed(transfers__destinations=DELETE)))
        )
        self.assertTrue(any("cannot be null" in m for m in messages(changed(transfers__destinations=None))))
        self.assertTrue(any("subprocessors[1].country" in m for m in messages(changed(subprocessors__1__country=DELETE))))

    def test_wrong_types(self):
        cases = {
            "processing__data_types": "account data",
            "processing__subject_matter": 1,
            "art28_clauses__subprocessor_authorization": "generic",
            "breach_notification__timing": 72,
            "subprocessors": {"name": "x"},
            "transfers__mechanisms": ["US"],
            "transfers__mechanisms__US": True,
            "agreement": None,
            "subprocessors__0__purpose": None,
            "subprocessors__0__name": " ",
        }
        for path, value in cases.items():
            with self.subTest(path=path):
                self.assertNotEqual(messages(changed(**{path: value})), [])

    def test_choice_suggests_the_spelling(self):
        found = messages(changed(transfers__mechanisms__US="SCCs"))
        self.assertTrue(any(m.endswith("did you mean 'sccs'?") for m in found), found)


class Countries(unittest.TestCase):
    def test_codes_must_be_upper_case_iso(self):
        cases = {
            "us": "must be upper case: use 'US'",
            "UK": '"GB"',
            "EL": '"GR"',
            "EU": "member state",
            "USA": "two-letter",
        }
        for code, fragment in cases.items():
            with self.subTest(code=code):
                found = messages(changed(subprocessors__1__country=code))
                self.assertTrue(any(fragment in m for m in found), found)

    def test_mechanism_for_an_unlisted_destination_is_refused(self):
        found = messages(changed(transfers__mechanisms__IN="sccs"))
        self.assertTrue(any("records IN, which transfers.destinations does not list" in m for m in found))

    def test_duplicate_destination_is_refused(self):
        found = messages(changed(transfers__destinations=["FR", "US", "JP", "US"]))
        self.assertIn("transfers.destinations lists US more than once.", found)

    def test_a_typo_in_destinations_is_reported_once(self):
        found = messages(changed(transfers__destinations=["FR", "us", "JP"]))
        self.assertEqual(len(found), 1, found)

    def test_sub_processor_names_must_give_distinct_rule_ids(self):
        dpa = changed()
        dpa["subprocessors"].append({"name": "support tools, llc", "country": "US"})
        self.assertTrue(any("repeats subprocessors[1].name" in m for m in messages(dpa)))


class Evidence(unittest.TestCase):
    def test_valid_evidence(self):
        dpa = changed(evidence={
            "art28_clauses.subprocessor_flowdown": {"clause": "§ 7.2", "quote": "..."},
            "subprocessors[1]": {"clause": "Annex 3"},
            "transfers.mechanisms.US": {"quote": "Standard Contractual Clauses apply."},
        })
        self.assertEqual(messages(dpa), [])

    def test_evidence_for_a_fact_the_input_does_not_record(self):
        found = messages(changed(evidence={"art28_clauses.subprocesor_flowdown": {"clause": "7.2"}}))
        self.assertTrue(any("did you mean 'art28_clauses.subprocessor_flowdown'?" in m for m in found), found)
        self.assertTrue(messages(changed(evidence={"subprocessors[7]": {"clause": "x"}})))
        self.assertTrue(messages(changed(evidence={"not a path!": {"clause": "x"}})))

    def test_evidence_items_need_a_clause_or_quote(self):
        for item in ({}, {"clause": ""}, {"page": "4"}, "§ 7"):
            with self.subTest(item=item):
                self.assertTrue(messages(changed(evidence={"ccpa": item})))


class CommandLine(unittest.TestCase):
    def test_fail_open_fixture_is_refused(self):
        # Without the contract, the misspelt section reads as "no direct transfers": cleared, exit 0.
        fixture = FIXTURES / "11-misspelt-transfers-key.json"
        self.assertEqual(build_packet(load(fixture)).review_state, "CLEARED_FOR_REVIEW")
        with tempfile.TemporaryDirectory() as out:
            code, stdout, stderr = run_cli("--input", fixture, "--out", out)
            self.assertEqual(code, 3)
            self.assertEqual(stdout, "")
            self.assertEqual(list(Path(out).iterdir()), [])
        self.assertIn("line 43: unknown key 'transfer'; did you mean 'transfers'?", stderr)
        self.assertIn("no review state was decided", stderr)

    def test_schema_flag_prints_the_committed_schema(self):
        code, stdout, _ = run_cli("--schema")
        self.assertEqual(code, 0)
        self.assertEqual(stdout, (ROOT / "schema" / "dpa.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(stdout), json_schema())
        self.assertEqual(stdout, schema_text())


@unittest.skipUnless(jsonschema, "jsonschema is not installed")
class JsonSchemaAgreesWithTheContract(unittest.TestCase):
    """The published schema accepts what the CLI accepts and refuses the structural errors it refuses."""

    def setUp(self):
        self.validator = jsonschema.Draft202012Validator(json_schema())

    def test_schema_is_valid(self):
        jsonschema.Draft202012Validator.check_schema(json_schema())

    def test_conforming_inputs_validate(self):
        inputs = [SAMPLE, {"$schema": "../schema/dpa.schema.json", **SAMPLE}] + [
            load(path) for path in sorted(FIXTURES.glob("*.json")) if path.name != "expected.json"
        ]
        for dpa in inputs:
            if violations(dpa):
                continue
            with self.subTest(agreement=dpa.get("agreement")):
                self.assertEqual(list(self.validator.iter_errors(dpa)), [])

    def test_structural_errors_fail_the_schema_too(self):
        bad = [
            load(FIXTURES / "11-misspelt-transfers-key.json"),
            load(FIXTURES / "12-string-false-flag.json"),
            changed(subprocessors__1__country="UK"),
            changed(subprocessors__1__country="us"),
            changed(transfers__mechanisms__US="SCCs"),
            changed(agreement=None),
            changed(evidence={"ccpa": {}}),
            {"$schema": 1, **SAMPLE},
        ]
        for dpa in bad:
            with self.subTest(dpa=json.dumps(dpa)[:60]):
                self.assertTrue(violations(dpa))
                self.assertTrue(list(self.validator.iter_errors(dpa)))


if __name__ == "__main__":
    unittest.main()
