import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.claude/skills/verify-vstack/tools/valentin-subskills'
GRADE = SKILL / 'grade.py'
HANDOVER_FIRST = ('If valentin-mode is not loaded in this chat, read '
                  '~/.claude/skills/valentin-mode/SKILL.md in full first, then run /board-drain.')


def use(name, **tool_input):
    return {'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'id': 't%d' % len(tool_input), 'name': name, 'input': tool_input}]}}


def bash(command):
    return use('Bash', command=command)


def read(path):
    return use('Read', file_path=path)


def write(path):
    return use('Write', file_path=path, content='x')


def stream(*events, session='sid-sub'):
    init = {'type': 'system', 'subtype': 'init', 'session_id': session}
    return [init] + list(events)


class VerifyValentinSubskills(unittest.TestCase):
    def evidence(self, scenario, events, home=None):
        where = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, where, ignore_errors=True)
        target = where / 'run'
        target.mkdir()
        (target / 'scenario.txt').write_text(scenario + '\n')
        (target / 'stream.jsonl').write_text(
            '\n'.join(json.dumps(event) for event in events) + '\n')
        return target, where

    def grade(self, target, home=None):
        env = dict(os.environ)
        if home is not None:
            env['HOME'] = str(home)
        return subprocess.run([sys.executable, str(GRADE), str(target)],
                              capture_output=True, text=True, check=False, env=env)

    def assert_verdict(self, result, verdict):
        lines = result.stdout.splitlines()
        self.assertIn('VERDICT ' + verdict, lines, result.stdout)
        self.assertEqual(result.returncode, 0 if verdict == 'PASS' else 1, result.stdout)

    def test_plain_words_passes_only_when_unjargon_comes_first(self):
        target, _ = self.evidence('plain-words', stream(
            read('/home/x/.claude/skills/unjargon/SKILL.md'),
            bash('hypertask --json comment add SOFT-2849 --body "done"')))
        self.assert_verdict(self.grade(target), 'PASS')

    def test_a_comment_written_without_reading_unjargon_fails(self):
        target, _ = self.evidence('plain-words', stream(
            bash('hypertask --json comment add SOFT-2849 --body "done"')))
        result = self.grade(target)
        self.assert_verdict(result, 'FAIL')
        self.assertIn("the rule's source was never read before the step", result.stdout)

    def test_reading_unjargon_after_the_comment_fails(self):
        target, _ = self.evidence('plain-words', stream(
            bash('hypertask --json comment add SOFT-2849 --body "done"'),
            bash('cat ~/.claude/skills/unjargon/SKILL.md')))
        self.assert_verdict(self.grade(target), 'FAIL')

    def test_report_passes_when_report_page_is_read_before_the_html(self):
        target, _ = self.evidence('report', stream(
            read('/home/x/.claude/skills/report-page/SKILL.md'),
            write('/tmp/vvs-scratch.x/report.html')))
        self.assert_verdict(self.grade(target), 'PASS')

    def test_a_report_page_written_without_its_skill_fails(self):
        target, _ = self.evidence('report', stream(write('/tmp/vvs-scratch.x/report.html')))
        self.assert_verdict(self.grade(target), 'FAIL')

    def test_a_new_ask_with_no_ticket_fails(self):
        target, _ = self.evidence('ticket', stream(
            write('/tmp/vvs-scratch.x/CONTRIBUTING.md')))
        result = self.grade(target)
        self.assert_verdict(result, 'FAIL')
        self.assertIn('no ticket was created for the ask', result.stdout)

    def test_a_ticket_before_the_work_passes(self):
        target, _ = self.evidence('ticket', stream(
            bash('hypertask --json task create --project 2060 --title "one-line CONTRIBUTING.md"'),
            write('/tmp/vvs-scratch.x/CONTRIBUTING.md')))
        self.assert_verdict(self.grade(target), 'PASS')

    def test_a_ticket_after_the_work_fails(self):
        target, _ = self.evidence('ticket', stream(
            write('/tmp/vvs-scratch.x/CONTRIBUTING.md'),
            bash('hypertask --json task create --project 2060 --title "one-line CONTRIBUTING.md"')))
        result = self.grade(target)
        self.assert_verdict(result, 'FAIL')
        self.assertIn('the ticket came after the work', result.stdout)

    def test_handover_with_the_required_first_line_passes(self):
        target, home = self.evidence('handover', stream(
            read('/home/x/.claude/skills/long-chat/SKILL.md'),
            write('/home/x/.local/state/long-chat/sid-sub.md')))
        state = home / '.local' / 'state' / 'long-chat'
        state.mkdir(parents=True)
        (state / 'sid-sub.md').write_text(HANDOVER_FIRST + '\n\nGoal: the check.\n')
        self.assert_verdict(self.grade(target, home), 'PASS')

    def test_handover_with_its_own_first_line_fails(self):
        target, home = self.evidence('handover', stream(
            write('/home/x/.local/state/long-chat/sid-sub.md')))
        state = home / '.local' / 'state' / 'long-chat'
        state.mkdir(parents=True)
        (state / 'sid-sub.md').write_text('Handover\n\nGoal: the check.\n')
        result = self.grade(target, home)
        self.assert_verdict(result, 'FAIL')
        self.assertIn("first line is not the required sentence", result.stdout)

    def test_no_handover_file_fails(self):
        target, home = self.evidence('handover', stream(read('/home/x/.claude/skills/long-chat/SKILL.md')))
        self.assert_verdict(self.grade(target, home), 'FAIL')

    def test_pr_queue_with_mine_passes(self):
        target, _ = self.evidence('prs', stream(
            bash('~/.claude/skills/pr-housekeeping/pr-queue --mine "VVM Test Agent"')))
        self.assert_verdict(self.grade(target), 'PASS')

    def test_pr_queue_without_mine_fails(self):
        target, _ = self.evidence('prs', stream(
            bash('~/.claude/skills/pr-housekeeping/pr-queue')))
        result = self.grade(target)
        self.assert_verdict(result, 'FAIL')
        self.assertIn('no pr-queue run with --mine', result.stdout)

    def test_a_break_run_removes_the_rule_and_the_skill_it_needs(self):
        with tempfile.TemporaryDirectory() as where:
            skills = Path(where) / 'skills'
            shutil.copytree(ROOT / 'skills/valentin-mode', skills / 'valentin-mode')
            shutil.copytree(ROOT / 'skills/unjargon', skills / 'unjargon')
            result = subprocess.run([sys.executable, str(GRADE), '--break', 'plain-words',
                                     '--skills', str(skills)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('unjargon', result.stdout)
            text = (skills / 'valentin-mode/SKILL.md').read_text()
            self.assertNotIn('read ../unjargon/SKILL.md', text,
                             'the chat has no rule to follow after the break')
            self.assertFalse((skills / 'unjargon').exists())

    def test_each_scenario_names_a_job(self):
        for scenario in ('plain-words', 'report', 'ticket', 'handover', 'prs'):
            with self.subTest(scenario=scenario):
                result = subprocess.run([sys.executable, str(GRADE), '--job', scenario],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(result.stdout.strip(), 'a job line')

    def test_an_unknown_scenario_is_a_usage_error(self):
        result = subprocess.run([sys.executable, str(GRADE), '--job', 'nope'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        with tempfile.TemporaryDirectory() as where:
            target = Path(where)
            (target / 'scenario.txt').write_text('nope\n')
            (target / 'stream.jsonl').write_text('')
            result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn('unknown scenario', result.stdout)


if __name__ == '__main__':
    unittest.main()
