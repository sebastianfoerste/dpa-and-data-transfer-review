"""The version and licence that the package, pyproject.toml and CITATION.cff publish must agree,
so that a release cannot bump one of them and leave the others behind."""

import re
import unittest

from dpa_review import __version__
from tests.helpers import ROOT


def field(path, pattern):
    text = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{path} has no line matching {pattern!r}")
    return match.group(1)


class Metadata(unittest.TestCase):
    def test_versions_agree(self):
        self.assertEqual(field("pyproject.toml", r'^version = "([^"]+)"$'), __version__)
        self.assertEqual(field("CITATION.cff", r"^version: (\S+)$"), __version__)

    def test_licence_is_mit_everywhere(self):
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text(encoding="utf-8"))
        self.assertEqual(field("CITATION.cff", r"^license: (\S+)$"), "MIT")
        self.assertIn('"MIT"', field("pyproject.toml", r"^license = (.+)$"))

    def test_citation_names_this_repository(self):
        self.assertEqual(
            field("CITATION.cff", r'^repository-code: "([^"]+)"$'),
            "https://github.com/sebastianfoerste/dpa-and-data-transfer-review",
        )


if __name__ == "__main__":
    unittest.main()
