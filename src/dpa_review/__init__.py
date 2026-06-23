"""dpa_review — deterministic, cited first-pass review of a Data Processing
Agreement and its international data transfers. Produces a review packet with a
visible review state. Not legal advice; bundled data is synthetic."""

from dpa_review.review import build_packet, render_markdown, ReviewPacket
from dpa_review.checks import run_all_checks, Finding

__all__ = ["build_packet", "render_markdown", "ReviewPacket", "run_all_checks", "Finding"]
__version__ = "0.1.0"
