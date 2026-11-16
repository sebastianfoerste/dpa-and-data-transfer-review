"""Snapshots under sources/oj are byte-exact records of the Official Journal texts.

A changed hash means the file was edited or replaced; a new retrieval needs a
new manifest entry, never a silent overwrite.
"""

import hashlib
import json
import unittest

from tests.helpers import ROOT

MANIFEST = json.loads((ROOT / "sources" / "manifest.json").read_text(encoding="utf-8"))
TIMESTAMP = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"


class SourceSnapshots(unittest.TestCase):
    def test_every_snapshot_matches_its_recorded_hash(self) -> None:
        for item in MANIFEST["sources"]:
            with self.subTest(celex=item["celex"]):
                data = (ROOT / item["file"]).read_bytes()
                self.assertEqual(len(data), item["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])

    def test_every_snapshot_file_is_listed(self) -> None:
        listed = {item["file"] for item in MANIFEST["sources"]}
        on_disk = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "sources" / "oj").iterdir()
            if path.is_file()
        }
        self.assertEqual(on_disk, listed)

    def test_every_entry_records_its_provenance(self) -> None:
        for item in MANIFEST["sources"]:
            with self.subTest(celex=item["celex"]):
                self.assertTrue(
                    item["requested_url"].startswith("https://publications.europa.eu/resource/celex/")
                )
                self.assertRegex(item["retrieved_at"], TIMESTAMP)
                self.assertTrue(item["oj_reference"].startswith("OJ L"))
                self.assertEqual(len(item["sha256"]), 64)

    def test_every_entry_was_rechecked_on_the_recheck_date(self) -> None:
        recheck = MANIFEST["recheck"]["date"]
        for item in MANIFEST["sources"]:
            with self.subTest(celex=item["celex"]):
                self.assertRegex(item["rechecked_at"], TIMESTAMP)
                self.assertEqual(item["rechecked_at"][:10], recheck)
                self.assertGreaterEqual(item["rechecked_at"], item["retrieved_at"])

    def test_texts_consulted_outside_the_journal_record_their_provenance(self) -> None:
        # Case law, EDPB guidance and the CCPA are cited but not snapshotted; the
        # manifest still says where each text came from and what was checked.
        consulted = MANIFEST["texts_consulted"]
        self.assertTrue(consulted)
        for item in consulted:
            with self.subTest(title=item["title"]):
                self.assertTrue(item["url"].startswith("https://"))
                self.assertRegex(item["retrieved_at"], TIMESTAMP)
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(item["pinpoints_checked"].strip())
                self.assertIn("not snapshotted", item["use"])
        guidance = [item for item in consulted if item["kind"].startswith("guidance")]
        self.assertEqual(len(guidance), 2)
        for item in guidance:
            self.assertEqual(item["kind"], "guidance, not law")


if __name__ == "__main__":
    unittest.main()
