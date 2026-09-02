"""The licence file and the README licence claim must agree.

The README previously stated MIT while LICENSE reserved all rights, which
GitHub surfaced as NOASSERTION. A published licence claim that the licence
file contradicts is a trust defect, so it is asserted here.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MIT_MARKERS = (
    "MIT License",
    "Permission is hereby granted, free of charge",
    'THE SOFTWARE IS PROVIDED "AS IS"',
)


class LicenceConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_licence_file_is_mit(self) -> None:
        for marker in MIT_MARKERS:
            self.assertIn(marker, self.licence, f"LICENSE missing MIT marker: {marker!r}")

    def test_licence_file_reserves_no_rights(self) -> None:
        lowered = self.licence.lower()
        self.assertNotIn("all rights reserved", lowered)
        self.assertNotIn("no license is granted", lowered)

    def test_readme_claim_matches_the_licence_file(self) -> None:
        self.assertIn("MIT", self.readme, "README no longer states a licence")
        self.assertIn("MIT License", self.licence)


if __name__ == "__main__":
    unittest.main()
