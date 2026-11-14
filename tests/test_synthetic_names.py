"""Organisation names in structured synthetic data must come from an allowlist.

The bundled data is synthetic. A real organisation's name in a sample DPA, a fixture or a
committed packet would attach invented findings to a real company, so every organisation-name
field is checked against tests/fictional_organisations.json. Free-text prose and images are out of
scope here: the pull request template asks for a manual check of screenshots and images.
"""

import json
import unittest
from typing import Any, Iterator

from tests.helpers import ROOT, SAMPLE_PATH, load

ALLOWLIST_PATH = ROOT / "tests" / "fictional_organisations.json"
ALLOWLIST = frozenset(load(ALLOWLIST_PATH)["names"])

# Fields that hold an organisation's name in the input contract and its outputs.
ORGANISATION_KEYS = frozenset(
    {
        "controller",
        "processor",
        "name",
        "organisation",
        "organization",
        "company",
        "vendor",
        "importer",
        "exporter",
        "recipient_name",
    }
)

SCANNED_DIRECTORIES = ("data", "examples", "tests/fixtures")
SCANNED_FILES = ("tests/adequacy_cases.json",)


def organisation_names(payload: Any) -> Iterator[str]:
    """Every organisation name held in a structured field."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in ORGANISATION_KEYS and isinstance(value, str):
                yield value
        # Party nodes of the transfer evidence graph carry the name as a label.
        if payload.get("kind") == "party" and isinstance(payload.get("label"), str):
            yield payload["label"]
        for value in payload.values():
            yield from organisation_names(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from organisation_names(item)


def unlisted_names(payload: Any, allowlist: frozenset[str]) -> list[str]:
    return sorted({name for name in organisation_names(payload) if name not in allowlist})


def structured_files() -> list:
    files = [path for directory in SCANNED_DIRECTORIES for path in sorted((ROOT / directory).rglob("*.json"))]
    return files + [ROOT / name for name in SCANNED_FILES]


class SyntheticOrganisationNames(unittest.TestCase):
    def test_repository_data_uses_only_allowlisted_names(self) -> None:
        files = structured_files()
        self.assertGreater(len(files), 20, "no structured data found to scan")
        for path in files:
            with self.subTest(file=path.relative_to(ROOT).as_posix()):
                self.assertEqual(unlisted_names(json.loads(path.read_text(encoding="utf-8")), ALLOWLIST), [])

    def test_every_allowlisted_name_is_used(self) -> None:
        # A name nothing uses any more is removed, so the list stays a record of what the data holds.
        used = {name for path in structured_files() for name in organisation_names(load(path))}
        self.assertEqual(sorted(ALLOWLIST - used), [])

    def test_the_sample_dpa_is_actually_scanned(self) -> None:
        found = set(organisation_names(load(SAMPLE_PATH)))
        self.assertIn("Acme SaaS GmbH (synthetic)", found)
        self.assertIn("Support Tools LLC", found)

    def test_seeded_unknown_name_fails_the_check(self) -> None:
        # Seeded failing case: one name that is not on the allowlist, nested the way a sub-processor would be.
        seeded = {
            "controller": "Acme SaaS GmbH (synthetic)",
            "subprocessors": [{"name": "Unlisted Example Holdings", "country": "US"}],
        }
        self.assertEqual(unlisted_names(seeded, ALLOWLIST), ["Unlisted Example Holdings"])

    def test_seeded_unknown_graph_label_fails_the_check(self) -> None:
        seeded = {"nodes": [{"kind": "party", "label": "Unlisted Example Holdings"}]}
        self.assertEqual(unlisted_names(seeded, ALLOWLIST), ["Unlisted Example Holdings"])

    def test_allowlist_is_not_empty_and_sorted(self) -> None:
        names = load(ALLOWLIST_PATH)["names"]
        self.assertTrue(names)
        self.assertEqual(names, sorted(names))


if __name__ == "__main__":
    unittest.main()
