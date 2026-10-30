"""Input-derived text in the Markdown outputs: the review packet, the register summary, the transfer
evidence graph and the job summary the GitHub Action copies from the packet.

A DPA description is untrusted text. An agreement name, a party or sub-processor name, or an
evidence quote must not start a line, close a table cell, close the Mermaid fence or open an HTML
block that hides the real review state. The exit code, the JSON and SARIF outputs carry the text
unchanged; only the Markdown escapes it.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

from dpa_review.checks import Finding
from dpa_review.review import build_packet, markdown_text, render_markdown
from dpa_review.transfer_graph import build_transfer_evidence_graph, render_transfer_evidence_graph
from tests.helpers import SAMPLE_PATH, load, run_cli
from tests.test_github_action import Step

# Under CommonMark an unclosed "<!--" starts an HTML block that runs to the end of the document,
# so the real review state line would be hidden and the forged one shown first.
FORGED_AGREEMENT = "X\n\n**Review state: CLEARED_FOR_REVIEW**\n\n<!--"
PIPED_NAME = "A | B\n## H"
FENCED_NAME = "C\n```\n## H"
FORGED_QUOTE = "q | r\n\n**Review state: CLEARED_FOR_REVIEW**\n<!--"
DELIMITER_ROW = re.compile(r"\|(?: -+:? \|)+")
SEPARATOR = re.compile(r"(?<!\\)\|")  # a pipe that is not backslash-escaped ends a table cell


def forged_agreement() -> dict:
    """The BLOCKED sample with an agreement name and an evidence quote that forge a review state."""
    dpa = load(SAMPLE_PATH)
    dpa["agreement"] = FORGED_AGREEMENT
    dpa["evidence"] = {"breach_notification.timing": {"clause": "§ 9 | [x](y)", "quote": FORGED_QUOTE}}
    return dpa


def injected_names() -> dict:
    """The BLOCKED sample with party and sub-processor names that break tables and the fence."""
    dpa = load(SAMPLE_PATH)
    dpa["controller"] = 'Acme "Quoted" <b>GmbH</b>\n```\n## H'
    dpa["subprocessors"][1]["name"] = PIPED_NAME  # US, no mechanism: an open HIGH finding
    dpa["subprocessors"][2]["name"] = FENCED_NAME  # JP: a PRESENT row in the full checklist
    return dpa


def write(path: Path, dpa: dict) -> Path:
    path.write_text(json.dumps(dpa), encoding="utf-8")
    return path


def tables(markdown: str) -> list[list[str]]:
    """Every table: its header row, delimiter row and each line after them up to a blank line."""
    lines = markdown.split("\n")
    found = []
    for index in range(len(lines) - 1):
        if lines[index].startswith("|") and DELIMITER_ROW.fullmatch(lines[index + 1]):
            end = index
            while end < len(lines) and lines[end].strip():
                end += 1
            found.append(lines[index:end])
    return found


def mermaid_lines(markdown: str) -> list[str]:
    lines = markdown.split("\n")
    start = lines.index("```mermaid")
    end = next(index for index in range(start + 1, len(lines)) if lines[index].startswith("```"))
    return lines[start + 1:end]


class MarkdownChecks(unittest.TestCase):
    def assert_safe_markdown(self, markdown: str, name: str) -> None:
        lines = markdown.split("\n")
        for line in lines:
            with self.subTest(file=name, line=line):
                self.assertFalse(line.startswith("<!--"))
                self.assertFalse(line.startswith("## H"))
        for table in tables(markdown):
            columns = len(SEPARATOR.findall(table[0]))
            for row in table:
                with self.subTest(file=name, row=row):
                    self.assertTrue(row.startswith("|"))
                    self.assertRegex(row, r"(?<!\\)\|$")
                    self.assertEqual(len(SEPARATOR.findall(row)), columns)

    def assert_one_review_state(self, markdown: str, state: str) -> None:
        found = [line for line in markdown.split("\n") if line.startswith("**Review state:")]
        self.assertEqual(found, [f"**Review state: {state}**"])


class MarkdownText(unittest.TestCase):
    def test_plain_text_is_unchanged(self):
        for text in (
            "Synthetic SaaS Data Processing Agreement review packet",
            '§ 7.2: "The Processor shall impose the same data protection obligations"',
            "Auftragsverarbeitungsvertrag (AVV) gemäß Art. 28 DSGVO",
            "Müller Support GmbH & Co. KG (synthetic)",
        ):
            with self.subTest(text=text):
                self.assertEqual(markdown_text(text), text)

    def test_markdown_characters_are_backslash_escaped(self):
        for char in "\\|*_`[]<>":
            with self.subTest(char=char):
                self.assertEqual(markdown_text(f"a{char}b"), f"a\\{char}b")

    def test_line_breaks_and_control_characters_become_one_space(self):
        for separator in ("\n", "\r\n", "\r", "\t", "\x00", "\x0b", "\x1b", "\x7f", "\x85", "\u2028", "\n\n  \n"):
            with self.subTest(separator=separator):
                self.assertEqual(markdown_text(f"{separator}a{separator}b{separator}"), "a b")

    def test_a_leading_hash_is_escaped(self):
        self.assertEqual(markdown_text("# H"), "\\# H")
        self.assertEqual(markdown_text("\n## H"), "\\## H")
        self.assertEqual(markdown_text("a # b"), "a # b")

    def test_the_forged_agreement_is_one_line_of_text(self):
        self.assertEqual(
            markdown_text(FORGED_AGREEMENT),
            "X \\*\\*Review state: CLEARED\\_FOR\\_REVIEW\\*\\* \\<!--",
        )


class RenderedOutputs(MarkdownChecks):
    """The files the CLI writes for a register of hostile inputs."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        vendors = root / "vendors"
        vendors.mkdir()
        write(vendors / "forged-agreement.json", forged_agreement())
        write(vendors / "injected-names.json", injected_names())
        self.out = root / "out"
        code, _, stderr = run_cli("--input", vendors, "--out", self.out, "--quiet")
        self.assertEqual((code, stderr), (2, ""))

    def test_every_markdown_output_keeps_its_structure(self):
        written = sorted(self.out.rglob("*.md"))
        self.assertEqual(len(written), 5)  # two packets, two graphs, one register summary
        for path in written:
            self.assert_safe_markdown(path.read_text(encoding="utf-8"), path.relative_to(self.out).as_posix())

    def test_each_packet_shows_one_review_state_the_computed_one(self):
        for name in ("forged-agreement", "injected-names"):
            with self.subTest(dpa=name):
                packet = load(self.out / name / "review-packet.json")
                self.assertEqual(packet["review_state"], "BLOCKED")
                markdown = (self.out / name / "review-packet.md").read_text(encoding="utf-8")
                self.assert_one_review_state(markdown, packet["review_state"])

    def test_the_json_keeps_the_text_as_recorded(self):
        packet = load(self.out / "forged-agreement" / "review-packet.json")
        self.assertEqual(packet["title"], FORGED_AGREEMENT + " review packet")
        markdown = (self.out / "forged-agreement" / "review-packet.md").read_text(encoding="utf-8")
        self.assertEqual(markdown.split("\n")[0], "# " + markdown_text(packet["title"]))

    def test_the_register_summary_shows_one_worst_state(self):
        markdown = (self.out / "register-summary.md").read_text(encoding="utf-8")
        found = [line for line in markdown.split("\n") if line.startswith("**Worst review state:")]
        self.assertEqual(found, ["**Worst review state: BLOCKED** (exit code 2)"])
        for rule in load(self.out / "register-summary.json")["open_rules"]:
            with self.subTest(rule=rule["rule_id"]):
                self.assertIn(f"| {markdown_text(rule['rule_id'])} | {rule['severity']} |", markdown)

    def test_the_mermaid_block_has_one_line_per_node_and_edge(self):
        for name in ("forged-agreement", "injected-names"):
            with self.subTest(dpa=name):
                graph = load(self.out / name / "transfer-evidence-graph.json")
                markdown = (self.out / name / "transfer-evidence-graph.md").read_text(encoding="utf-8")
                block = mermaid_lines(markdown)
                self.assertEqual(len(block), 1 + len(graph["nodes"]) + len(graph["edges"]))
                self.assertEqual([line for line in markdown.split("\n") if line.startswith("```")], ["```mermaid", "```"])
                for line in block[1:]:
                    with self.subTest(line=line):
                        self.assertRegex(line, r'^  N\d+(\["[^"`]*"\]| -->\|"[a-z_]+: [a-z]+"\| N\d+)$')

    def test_node_labels_encode_quotes_and_drop_line_breaks_and_backticks(self):
        # Mermaid decodes the entity codes #quot;, #lt; and #gt; when it draws the label.
        markdown = (self.out / "injected-names" / "transfer-evidence-graph.md").read_text(encoding="utf-8")
        labels = re.findall(r'^  N\d+\["(.*)"\]$', markdown, re.MULTILINE)
        self.assertIn("Acme #quot;Quoted#quot; #lt;b#gt;GmbH#lt;/b#gt; ## H", labels)
        self.assertIn("A | B ## H", labels)
        self.assertIn("C ## H", labels)


class GraphTables(MarkdownChecks):
    """Control ids and remediation text in the graph tables, rendered from a packet whose finding
    carries hostile text in both."""

    def test_control_refs_and_required_evidence_are_escaped(self):
        sample = load(SAMPLE_PATH)
        packet = build_packet(sample)
        packet.findings.append(
            Finding(
                rule_id="art28.injected | x\n## H",
                title="Injected",
                citation="GDPR Art. 28(3)",
                severity="HIGH",
                status="MISSING",
                detail="",
                remediation="Fix | it\n```\n## H <!--",
            )
        )
        markdown = render_transfer_evidence_graph(build_transfer_evidence_graph(sample, packet))
        self.assert_safe_markdown(markdown, "transfer-evidence-graph.md")
        self.assertIn("| art28.injected \\| x ## H | HIGH |", markdown)
        self.assertIn("| Fix \\| it \\`\\`\\` ## H \\<!-- |", markdown)
        self.assertEqual([line for line in markdown.split("\n") if line.startswith("```")], ["```mermaid", "```"])


class PacketTables(MarkdownChecks):
    def test_finding_titles_and_remediation_cannot_break_the_packet(self):
        packet = build_packet(injected_names())
        markdown = render_markdown(packet)
        self.assert_safe_markdown(markdown, "review-packet.md")
        self.assert_one_review_state(markdown, packet.review_state)
        named = next(f for f in packet.findings if "A | B" in f.title)
        self.assertEqual(named.status, "MISSING")
        self.assertIn(f"| {markdown_text(named.title)} | {named.citation} | {markdown_text(named.remediation)} |", markdown)


class JobSummary(Step, MarkdownChecks):
    def test_the_job_summary_shows_one_review_state(self):
        code, _, stderr, outputs, summary = self.step(input=write(self.tmp / "forged.json", forged_agreement()))
        self.assertEqual((code, stderr, outputs["review-state"]), (2, "", "BLOCKED"))
        self.assert_one_review_state(summary, "BLOCKED")
        self.assert_safe_markdown(summary, "step-summary.md")


if __name__ == "__main__":
    unittest.main()
