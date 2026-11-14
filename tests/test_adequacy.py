"""Adequacy cases written from the Official Journal snapshots, before the rule code (tests/adequacy_cases.json)."""

import json
import re
import unittest
from html.parser import HTMLParser

from tests.helpers import ROOT

CASES = json.loads((ROOT / "tests" / "adequacy_cases.json").read_text(encoding="utf-8"))["cases"]
MANIFEST = json.loads((ROOT / "sources" / "manifest.json").read_text(encoding="utf-8"))
SOURCE_FILES = {item["celex"]: ROOT / item["file"] for item in MANIFEST["sources"]}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


_TEXT_CACHE: dict[str, str] = {}


def snapshot_text(celex: str) -> str:
    """The text of a snapshot, without markup and with whitespace collapsed."""
    if celex not in _TEXT_CACHE:
        parser = _Text()
        parser.feed(SOURCE_FILES[celex].read_text(encoding="utf-8"))
        _TEXT_CACHE[celex] = _normalise(" ".join(parser.parts))
    return _TEXT_CACHE[celex]


class AdequacyCasesQuoteTheirSources(unittest.TestCase):
    def test_every_case_quotes_its_snapshot(self) -> None:
        for case in CASES:
            with self.subTest(case=case["id"]):
                source = case["source"]
                self.assertIn(source["celex"], SOURCE_FILES)
                self.assertIn(_normalise(source["quote"]), snapshot_text(source["celex"]))

    def test_case_ids_are_unique(self) -> None:
        ids = [case["id"] for case in CASES]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
