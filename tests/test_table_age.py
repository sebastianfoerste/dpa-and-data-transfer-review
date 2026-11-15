"""The table-age command, always with an explicit --today so no test reads the clock."""

import contextlib
import io
import json
import unittest

from dpa_review.checks import ADEQUACY, TABLE_AS_OF
from dpa_review.table_age import main


def _run(*argv: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


class TableAgeCommand(unittest.TestCase):
    def test_the_table_date(self) -> None:
        self.assertEqual(TABLE_AS_OF, "2026-11-14")

    def test_json_report(self) -> None:
        code, out = _run("--today", "2026-11-21", "--json")
        report = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(report["table_as_of"], "2026-11-14")
        self.assertEqual(report["age_days"], 7)
        self.assertEqual(report["decisions"], len(ADEQUACY) + 1)
        self.assertFalse(report["stale"])

    def test_threshold_boundary(self) -> None:
        # Table as at 2026-11-14 with a 7-day limit: 6 and 7 days pass, 8 days fail.
        self.assertEqual(_run("--today", "2026-11-20", "--max-age-days", "7")[0], 0)
        self.assertEqual(_run("--today", "2026-11-21", "--max-age-days", "7")[0], 0)
        code, out = _run("--today", "2026-11-22", "--max-age-days", "7")
        self.assertEqual(code, 1)
        self.assertIn("STALE", out)

    def test_text_report_names_the_date(self) -> None:
        code, out = _run("--today", "2026-11-14")
        self.assertEqual(code, 0)
        self.assertEqual(out, "Adequacy table as at 2026-11-14: 0 days old on 2026-11-14 (17 decisions).\n")

    def test_one_day_is_singular(self) -> None:
        out = _run("--today", "2026-11-15")[1]
        self.assertEqual(out, "Adequacy table as at 2026-11-14: 1 day old on 2026-11-15 (17 decisions).\n")

    def test_invalid_today_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["--today", "2026-13-01"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
