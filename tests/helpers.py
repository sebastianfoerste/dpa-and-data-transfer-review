"""Shared helpers: run the CLI in-process and capture what it prints."""

import contextlib
import io
import json
from pathlib import Path

from dpa_review.cli import main

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "data" / "sample_dpa.json"
FIXTURES = ROOT / "tests" / "fixtures"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_cli(*args):
    """(exit code, stdout, stderr) of `dpa-review *args`, run in this process."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(arg) for arg in args])
    return code, out.getvalue(), err.getvalue()
