"""scripts/wording-only: prose alone skips the verifier."""

import importlib.machinery
import importlib.util
from pathlib import Path
from typing import NamedTuple
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/wording-only'


def load_script():
    loader = importlib.machinery.SourceFileLoader('wording_only', str(SCRIPT))
    spec = importlib.util.spec_from_loader('wording_only', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PROSE = '# Servers\n\nThis line says where each host lives.\n'


class WordingOnlyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def classify(self, paths, changes=None, files=None, tests=None):
        files = files if files is not None else {path: PROSE for path in paths}
        return self.m.classify(paths, changes or {}, files.get, tests or {})

    def test_a_prose_paragraph_under_docs_is_wording_only(self):
        wording, reason = self.classify(['docs/servers.md'])
        self.assertTrue(wording, reason)

    def test_prose_under_skills_is_wording_only(self):
        wording, reason = self.classify(['skills/board-drain/notes.md'])
        self.assertTrue(wording, reason)

    def test_a_change_outside_skills_and_docs_is_not_wording_only(self):
        wording, reason = self.classify(['scripts/up-to-date'])
        self.assertFalse(wording)
        self.assertIn('not markdown under skills/ or docs/', reason)

    def test_a_fence_on_the_line_is_not_wording_only(self):
        changes = {'docs/servers.md': [('+', 3, '```sh')]}
        wording, reason = self.classify(['docs/servers.md'], changes)
        self.assertFalse(wording)
        self.assertIn('fenced code', reason)

    def test_a_line_inside_a_fenced_block_is_not_wording_only(self):
        files = {'docs/servers.md': '# Servers\n\n```\nssh host\n```\n'}
        changes = {'docs/servers.md': [('+', 4, 'ssh other-host')]}
        wording, reason = self.classify(['docs/servers.md'], changes, files)
        self.assertFalse(wording)
        self.assertIn('frontmatter or fenced code', reason)

    def test_skill_frontmatter_is_not_wording_only(self):
        files = {'skills/x/SKILL.md': '---\nname: x\ndescription: y\n---\n\nBody prose.\n'}
        changes = {'skills/x/SKILL.md': [('-', 3, 'description: y')]}
        wording, reason = self.classify(['skills/x/SKILL.md'], changes, files)
        self.assertFalse(wording)
        self.assertIn('frontmatter', reason)

    def test_a_rule_table_row_is_not_wording_only(self):
        files = {'docs/servers.md': '| host | role |\n| --- | --- |\n'}
        changes = {'docs/servers.md': [('+', 2, '| --- | --- |')]}
        wording, reason = self.classify(['docs/servers.md'], changes, files)
        self.assertFalse(wording)
        self.assertIn('rule table', reason)

    def test_a_file_a_test_reads_is_not_wording_only(self):
        tests = {'test_server_facts.py': "text = (ROOT / 'docs/servers.md').read_text()\n"}
        wording, reason = self.classify(['docs/servers.md'], tests=tests)
        self.assertFalse(wording)
        self.assertIn('tests/ parses docs/servers.md', reason)

    def test_a_skill_md_a_test_walks_is_not_wording_only(self):
        tests = {'test_lazy_skills.py': "text = (SKILLS / name / 'SKILL.md').read_text()\n"}
        files = {'skills/x/SKILL.md': '---\nname: x\n---\n\nBody prose.\n'}
        wording, reason = self.classify(['skills/x/SKILL.md'], files=files, tests=tests)
        self.assertFalse(wording)
        self.assertIn('tests/ parses', reason)

    def test_a_deleted_file_is_not_wording_only(self):
        files = {'docs/servers.md': None}
        wording, reason = self.classify(['docs/servers.md'], files=files)
        self.assertFalse(wording)
        self.assertIn('was deleted', reason)

    def test_the_diff_parser_numbers_changed_lines(self):
        diff = ('diff --git a/docs/servers.md b/docs/servers.md\n'
                '--- a/docs/servers.md\n'
                '+++ b/docs/servers.md\n'
                '@@ -1,2 +1,3 @@\n'
                ' # Servers\n'
                '-old line\n'
                '+new line\n'
                '+extra line\n')
        self.assertEqual(self.m.parse_diff(diff),
                         {'docs/servers.md': [('-', 2, 'old line'),
                                              ('+', 2, 'new line'),
                                              ('+', 3, 'extra line')]})

    def test_fences_and_frontmatter_are_located(self):
        self.assertEqual(self.m.fenced_lines(['```', 'x', '```']), {1, 2, 3})
        self.assertEqual(self.m.frontmatter_lines(['---', 'name: x', '---']), {1, 2, 3})
        self.assertEqual(self.m.frontmatter_lines(['# Servers']), set())

    def test_a_skill_md_read_with_double_quotes_still_counts(self):
        tests = {'test_skill_check.py': 'text = (SKILLS / name / "SKILL.md").read_text()\n'}
        files = {'skills/x/SKILL.md': '---\nname: x\n---\n\nBody prose.\n'}
        wording, reason = self.classify(['skills/x/SKILL.md'], files=files, tests=tests)
        self.assertFalse(wording)
        self.assertIn('tests/ parses', reason)


WORKFLOW = ROOT / '.github/workflows/pstack-sources.yml'
SUMMARY = 'wording-only change: no verifier per pstack autopilot-full step 4'
GUARD = "steps.classify.outputs.wording_only != 'true'"


class Step(NamedTuple):
    start: str
    text: str


def is_job_header(line):
    return bool(line.strip()) and line.startswith('  ') and not line.startswith('   ')


def verifier_block():
    lines, inside = [], False
    for line in WORKFLOW.read_text().splitlines():
        if line.startswith('  verifier:'):
            inside = True
        elif inside and is_job_header(line):
            break
        if inside:
            lines.append(line)
    return lines


def verifier_steps():
    steps = []
    for line in verifier_block():
        if line.startswith('      - '):
            steps.append([line.strip()[2:]])
        elif steps:
            steps[-1].append(line.strip())
    return [Step(step[0], '\n'.join(step)) for step in steps]


class VerifierWorkflowTest(unittest.TestCase):
    """The ruleset requires `verifier`, so the wording-only pass posts that same check."""

    def test_the_job_keeps_the_required_check_name(self):
        self.assertTrue(verifier_block())
        self.assertNotIn('name:', '\n'.join(verifier_block()[:1]))

    def test_the_classifier_runs_before_the_verifier_and_posts_the_summary(self):
        steps = verifier_steps()
        starts = [start for start, _ in steps]
        classify = [i for i, (_, text) in enumerate(steps) if 'id: classify' in text]
        self.assertEqual(len(classify), 1, starts)
        text = steps[classify[0]][1]
        self.assertIn('scripts/wording-only', text)
        self.assertIn(SUMMARY, text)
        self.assertIn('wording_only=false', text)
        checkouts = [i for i, start in enumerate(starts) if start.startswith('uses: actions/checkout@v4')]
        self.assertLess(checkouts[0], classify[0], 'the classifier needs the head checkout')
        drive = [i for i, start in enumerate(starts) if 'Verifier drives the changed files' in start]
        self.assertEqual(len(drive), 1, starts)
        self.assertLess(classify[0], drive[0])

    def test_every_expensive_step_is_skipped_on_a_wording_only_change(self):
        steps = verifier_steps()
        self.assertEqual(steps[0][0], 'uses: actions/checkout@v4')
        for start, text in steps[1:]:
            if 'id: classify' in text:
                continue
            if 'Post no-verdict notice' in start:
                self.assertIn('failure()', text, start)
                continue
            self.assertIn(GUARD, text, start)


if __name__ == '__main__':
    unittest.main()
