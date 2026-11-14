"""Report how old the adequacy table is.

    dpa-review-table-age [--today YYYY-MM-DD] [--max-age-days N] [--json]
    python -m dpa_review.table_age ...   (or: make table-age)

The age runs from checks.TABLE_AS_OF, the date the table was last checked as a whole: every
Official Journal text under sources/oj re-fetched and found unchanged, and the Publications
Office's Cellar searched for later adequacy acts. With --max-age-days the command exits 1 once
the table is older than that, so a scheduled job can open an issue; the job is planned in another
repository, because GitHub disables schedules in a repository that changes rarely.

This is the only place in the package that reads the clock, and only when --today is absent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from dpa_review.checks import table_age


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO date (YYYY-MM-DD): {value}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dpa-review-table-age", description="Report the age of the GDPR adequacy table."
    )
    parser.add_argument(
        "--today", type=_iso_date, default=None, help="Reference date; defaults to the system date."
    )
    parser.add_argument(
        "--max-age-days", type=int, default=None, help="Exit 1 when the table is older than this."
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON report.")
    args = parser.parse_args(argv)

    report = table_age(args.today or date.today())
    stale = args.max_age_days is not None and report["age_days"] > args.max_age_days
    report["max_age_days"] = args.max_age_days
    report["stale"] = stale

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Adequacy table as at {report['table_as_of']}: {report['age_days']} days old "
            f"on {report['today']} ({report['decisions']} decisions)."
        )
        if stale:
            print(
                f"STALE: older than {args.max_age_days} days. Re-check the Official Journal for new, amended "
                "or repealed adequacy decisions, then update sources/ and src/dpa_review/checks.py "
                "(sources/README.md)."
            )
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
