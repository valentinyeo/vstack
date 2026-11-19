import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.claude/skills/verify-valentin-mode'
GRADE = SKILL / 'grade.py'
RUN = SKILL / 'run'
FIXTURES = ROOT / 'tests/fixtures/verify-valentin-mode'


class VerifyValentinModeGrade(unittest.TestCase):
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        return temp

    def grade_fixture(self, case):
        """Copy a fixture to a temp dir, grade it, and return (exit code, output, dir)."""
        target = self.temp_dir() / case
        shutil.copytree(FIXTURES / case, target)
        result = subprocess.run(
            [sys.executable, str(GRADE), str(target)],
            capture_output=True, text=True, check=False)
        return result.returncode, result.stdout, target

    def assert_check(self, output, verdict, check):
        lines = output.splitlines()
        self.assertIn('VERDICT ' + verdict, lines, output)
        expected = ('PASS ' if verdict == 'PASS' else 'FAIL ') + check + ':'
        self.assertTrue(
            any(line.startswith(expected) for line in lines),
            'expected a %r line, got:\n%s' % (expected, output))

    def test_pass_fixture_grades_pass(self):
        code, output, target = self.grade_fixture('pass')
        self.assertEqual(code, 0, output)
        self.assert_check(output, 'PASS', 'loaded')
        self.assert_check(output, 'PASS', 'session')
        self.assert_check(output, 'PASS', 'login')
        self.assert_check(output, 'PASS', 'pacer')
        self.assert_check(output, 'PASS', 'task')
        self.assert_check(output, 'PASS', 'board sync')
        self.assertIn('PASS loaded: the chat invoked the valentin-mode skill '
                      '(three tools version)', output)
        self.assertFalse(any(line.startswith('FAIL ') for line in output.splitlines()), output)
        verdict = json.loads((target / 'verdict.json').read_text())
        self.assertEqual(verdict['verdict'], 'PASS')
        self.assertEqual(verdict['session_id'], 'sid-pass')
        self.assertEqual(len(verdict['checks']), 6)
        self.assertEqual((target / 'verdict.txt').read_text(), output)

    def test_no_plan_pick_fixture_fails_pacer(self):
        code, output, _target = self.grade_fixture('no-plan-pick')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'pacer')
        self.assertIn('the chat never started a worker through plan-pick --run', output)

    def test_human_login_fixture_fails_login(self):
        code, output, _target = self.grade_fixture('human-login')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'login')
        self.assertIn('board write by Valentin Yeo instead of VVM Test Agent', output)

    def test_apply_first_fixture_fails_board_sync(self):
        code, output, _target = self.grade_fixture('apply-first')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'board sync')
        self.assertIn('apply ran before the dry run', output)

    def test_not_loaded_fixture_fails_loaded(self):
        code, output, _target = self.grade_fixture('not-loaded')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'loaded')
        self.assertIn('the chat never invoked the valentin-mode skill', output)

    def test_blocked_skill_fixture_fails_loaded(self):
        code, output, _target = self.grade_fixture('blocked')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'loaded')
        self.assertIn('the valentin-mode skill call was blocked or failed', output)
        self.assertFalse(any(line.startswith('FAIL loaded: the chat never')
                             for line in output.splitlines()), output)
        self.assertFalse(any(line.startswith('FAIL loaded: valentin-mode loaded')
                             for line in output.splitlines()), output)

    def test_old_version_fixture_fails_loaded(self):
        code, output, _target = self.grade_fixture('old-version')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'loaded')
        self.assertIn('valentin-mode loaded without the Three tools section', output)
        self.assertFalse(any(line.startswith('FAIL loaded: the chat never')
                             for line in output.splitlines()), output)

    def test_apply_no_label_fixture_fails_board_sync(self):
        code, output, _target = self.grade_fixture('apply-no-label')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'board sync')
        self.assertIn(
            'board sync apply without --label <label> can move real tickets', output)

    def test_agent_worker_fixture_fails_pacer(self):
        code, output, _target = self.grade_fixture('agent-worker')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'pacer')
        self.assertIn('code worker ran on Claude via the Agent tool', output)

    def test_lane_null_fixture_passes_with_no_lane_reason(self):
        code, output, _target = self.grade_fixture('lane-null')
        self.assertEqual(code, 0, output)
        self.assert_check(output, 'PASS', 'pacer')
        self.assertIn('PASS pacer: plan-pick ran, no lane left', output)

    def test_missing_evidence_dir_exits_2(self):
        missing = self.temp_dir() / 'does-not-exist'
        result = subprocess.run(
            [sys.executable, str(GRADE), str(missing)],
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_missing_stream_exits_2(self):
        temp = self.temp_dir()
        shutil.copytree(FIXTURES / 'pass', temp / 'pass')
        (temp / 'pass' / 'stream.jsonl').unlink()
        result = subprocess.run(
            [sys.executable, str(GRADE), str(temp / 'pass')],
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)


class VerifyValentinModeRunScript(unittest.TestCase):
    def test_run_script_parses(self):
        result = subprocess.run(['bash', '-n', str(RUN)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_run_script_blocks_only_the_valentin_mode_skill(self):
        text = RUN.read_text()
        lines = text.splitlines()
        self.assertNotIn('setting-sources', text, 'the break must not drop user hooks')
        self.assertEqual(
            text.count('Skill(valentin-mode)'), 1,
            'the only blocked tool must be the valentin-mode skill')
        tool_lines = [i for i, line in enumerate(lines) if 'disallowedTools' in line]
        self.assertEqual(len(tool_lines), 1, 'expected exactly one disallowedTools flag in run')
        self.assertIn("--disallowedTools 'Skill(valentin-mode)'", lines[tool_lines[0]])
        break_lines = [i for i, line in enumerate(lines)
                       if line.strip() == 'if [ -n "$BREAK" ]; then']
        self.assertEqual(len(break_lines), 1, 'expected one break branch in run')
        self.assertGreater(tool_lines[0], break_lines[0],
                           'the tool block must sit inside the break branch')

    def test_grade_script_has_shebang(self):
        self.assertEqual(GRADE.read_text().splitlines()[0], '#!/usr/bin/env python3')

    def test_scripts_are_executable(self):
        self.assertTrue(GRADE.stat().st_mode & 0o111, '%s is not executable' % GRADE)
        self.assertTrue(RUN.stat().st_mode & 0o111, '%s is not executable' % RUN)


if __name__ == '__main__':
    unittest.main()
