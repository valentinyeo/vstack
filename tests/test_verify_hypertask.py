import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.claude/skills/verify-vstack/tools/hypertask'
GRADE = SKILL / 'grade.py'
RUN = SKILL / 'run'
FIXTURES = ROOT / 'tests/fixtures/verify-hypertask'


class VerifyHypertaskGrade(unittest.TestCase):
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        return temp

    def grade_fixture(self, case):
        target = self.temp_dir() / case
        shutil.copytree(FIXTURES / case, target)
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        return result.returncode, result.stdout, target

    def assert_check(self, output, verdict, check):
        lines = output.splitlines()
        self.assertIn('VERDICT ' + verdict, lines, output)
        expected = ('PASS ' if verdict == 'PASS' else 'FAIL ') + check + ':'
        self.assertTrue(any(line.startswith(expected) for line in lines),
                        'expected a %r line, got:\n%s' % (expected, output))

    def failed(self, output):
        return [line for line in output.splitlines() if line.startswith('FAIL ')]

    def test_pass_fixture_grades_pass(self):
        code, output, target = self.grade_fixture('pass')
        self.assertEqual(code, 0, output)
        for check in ('read', 'login', 'view', 'board line', 'ticket', 'sync'):
            self.assert_check(output, 'PASS', check)
        self.assertFalse(self.failed(output), output)
        verdict = json.loads((target / 'verdict.json').read_text())
        self.assertEqual(verdict['verdict'], 'PASS')
        self.assertEqual(verdict['session_id'], 'sid-pass')
        self.assertEqual([check['name'] for check in verdict['checks']],
                         ['read', 'login', 'view', 'board line', 'ticket', 'sync'])
        self.assertEqual((target / 'verdict.txt').read_text(), output)

    def test_no_read_fixture_fails_only_read(self):
        code, output, _target = self.grade_fixture('no-read')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'read')
        self.assertIn('the chat never read skills/hypertask/SKILL.md', output)
        self.assertEqual(self.failed(output), ['FAIL read: the chat never read skills/hypertask/SKILL.md'])

    def test_valentin_login_fixture_fails_login(self):
        code, output, _target = self.grade_fixture('valentin-login')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'login')
        self.assertIn('board write by Valentin Yeo instead of VVM Test Agent', output)

    def test_no_view_fixture_fails_view(self):
        code, output, _target = self.grade_fixture('no-view')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'view')
        self.assertIn('no view created or found with label vvm-test', output)

    def test_no_board_line_fixture_fails_board_line(self):
        code, output, _target = self.grade_fixture('no-board-line')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'board line')
        self.assertIn('no Hypertask board: 2060 line in the project notes', output)

    def test_no_ticket_fixture_fails_ticket(self):
        code, output, _target = self.grade_fixture('no-ticket')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'ticket')
        self.assertIn('no ticket filed in label vvm-test', output)

    def test_apply_first_fixture_fails_sync(self):
        code, output, _target = self.grade_fixture('apply-first')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'sync')
        self.assertIn('apply ran before the dry run', output)

    def test_a_read_of_the_skill_passes_read_without_a_skill_call(self):
        target = self.temp_dir() / 'read'
        shutil.copytree(FIXTURES / 'no-read', target)
        events = [json.loads(line) for line in
                  (target / 'stream.jsonl').read_text().splitlines() if line.strip()]
        events.insert(1, {'type': 'assistant', 'session_id': 'sid-pass', 'message': {
            'content': [{'type': 'tool_use', 'id': 't-read', 'name': 'Read',
                         'input': {'file_path': '/x/skills/hypertask/SKILL.md'}}]}})
        (target / 'stream.jsonl').write_text(
            '\n'.join(json.dumps(event) for event in events) + '\n')
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('PASS read: the chat read skills/hypertask/SKILL.md', result.stdout)

    def test_a_label_override_must_match(self):
        target = self.temp_dir() / 'label'
        shutil.copytree(FIXTURES / 'pass', target)
        (target / 'notes.md').write_text('# Project\n\nHypertask board: 2060, label: other\n')
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('board line names label other instead of vvm-test', result.stdout)

    def test_an_explicit_matching_label_passes(self):
        target = self.temp_dir() / 'label-ok'
        shutil.copytree(FIXTURES / 'pass', target)
        (target / 'notes.md').write_text('# Project\n\nHypertask board: 2060, label: vvm-test\n')
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_apply_without_the_label_fails_sync(self):
        target = self.temp_dir() / 'no-label'
        shutil.copytree(FIXTURES / 'pass', target)
        text = (target / 'stream.jsonl').read_text().replace(
            '--board 2060 --label vvm-test --apply --limit 5',
            '--board 2060 --apply --limit 5')
        (target / 'stream.jsonl').write_text(text)
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('sync apply without --label vvm-test can move real tickets',
                      result.stdout)

    def test_missing_evidence_dir_exits_2(self):
        missing = self.temp_dir() / 'does-not-exist'
        result = subprocess.run([sys.executable, str(GRADE), str(missing)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_missing_stream_exits_2(self):
        temp = self.temp_dir()
        shutil.copytree(FIXTURES / 'pass', temp / 'pass')
        (temp / 'pass' / 'stream.jsonl').unlink()
        result = subprocess.run([sys.executable, str(GRADE), str(temp / 'pass')],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)


class VerifyHypertaskRunScript(unittest.TestCase):
    def test_run_script_parses(self):
        result = subprocess.run(['bash', '-n', str(RUN)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_run_script_never_drops_hooks_or_names_tools(self):
        text = RUN.read_text()
        self.assertNotIn('setting-sources', text, 'a run must never drop user hooks')
        self.assertNotIn('disallowedTools', text, 'the chat flags stay the same')
        self.assertNotIn('--label vvm-test\n', text.split('# 5. Prompt')[1].split('# 5b.')[0],
                         'the prompt must not hand the chat its own tool flags')

    def test_run_script_prompt_starts_with_the_skill(self):
        text = RUN.read_text()
        self.assertIn("printf '/hypertask Get me set up", text)
        self.assertNotIn('/valentin-mode', text)
        self.assertIn('SHIP_SESSION_NAME', text)

    def test_run_script_creates_an_empty_scratch_repo(self):
        text = RUN.read_text()
        self.assertIn('mktemp -d /tmp/vh-scratch.', text)
        self.assertNotIn('CLAUDE.md\n', text.split('git -C "$W" init')[0],
                         'the scratch repo starts with no project notes')

    def test_run_script_copies_the_installed_skill(self):
        text = RUN.read_text()
        self.assertIn('$HOME/.local/share/vstack/skills/hypertask/SKILL.md', text)
        self.assertIn('installed-hypertask.md', text)

    def test_grade_script_has_shebang(self):
        self.assertEqual(GRADE.read_text().splitlines()[0], '#!/usr/bin/env python3')

    def test_scripts_are_executable(self):
        self.assertTrue(GRADE.stat().st_mode & 0o111, '%s is not executable' % GRADE)
        self.assertTrue(RUN.stat().st_mode & 0o111, '%s is not executable' % RUN)


if __name__ == '__main__':
    unittest.main()
