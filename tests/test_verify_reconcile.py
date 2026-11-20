import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.claude/skills/verify-reconcile'
GRADE = SKILL / 'grade.py'
RUN = SKILL / 'run'
FIXTURES = ROOT / 'tests/fixtures/verify-reconcile'


class VerifyReconcileGrade(unittest.TestCase):
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

    def assert_line(self, output, verdict, check):
        expected = ('PASS ' if verdict == 'PASS' else 'FAIL ') + check + ':'
        self.assertTrue(
            any(line.startswith(expected) for line in output.splitlines()),
            'expected a %r line, got:\n%s' % (expected, output))

    def assert_check(self, output, verdict, check):
        self.assertIn('VERDICT ' + verdict, output.splitlines(), output)
        self.assert_line(output, verdict, check)

    def test_pass_dry_fixture_grades_pass(self):
        code, output, target = self.grade_fixture('pass-dry')
        self.assertEqual(code, 0, output)
        for check in ('finished', 'bus', 'unknown', 'calls', 'cases'):
            self.assert_check(output, 'PASS', check)
        self.assertFalse(any(line.startswith('FAIL ') for line in output.splitlines()), output)
        verdict = json.loads((target / 'verdict.json').read_text())
        self.assertEqual(verdict['verdict'], 'PASS')
        self.assertEqual(verdict['board'], 15)
        self.assertFalse(verdict['apply'])
        self.assertEqual(len(verdict['checks']), 5)
        self.assertEqual((target / 'verdict.txt').read_text(), output)

    def test_pass_apply_converged_fixture_grades_pass(self):
        code, output, _target = self.grade_fixture('pass-apply-converged')
        self.assertEqual(code, 0, output)
        for check in ('finished', 'bus', 'unknown', 'calls', 'cases',
                      'apply', 'settled', 'converged'):
            self.assert_check(output, 'PASS', check)
        self.assertIn('PASS converged: dry1 planned 2 moves, dry2 plans none', output)
        self.assertFalse(any(line.startswith('FAIL ') for line in output.splitlines()), output)

    def test_fail_unknown_fixture_fails_unknown(self):
        code, output, _target = self.grade_fixture('fail-unknown')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'unknown')
        self.assertIn('3 tickets were not read', output)
        self.assert_line(output, 'PASS', 'finished')
        self.assert_line(output, 'PASS', 'bus')

    def test_fail_bus_fixture_fails_bus(self):
        code, output, _target = self.grade_fixture('fail-bus')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'bus')
        self.assertIn('systemctl --user could not reach the session bus', output)

    def test_fail_calls_fixture_fails_calls(self):
        code, output, _target = self.grade_fixture('fail-calls')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'calls')
        self.assertIn('dry1 made 137 github calls, over budget 30', output)

    def test_fail_flipflop_fixture_fails_settled(self):
        code, output, _target = self.grade_fixture('fail-flipflop')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'settled')
        self.assertIn('HTPR-9387 moved in apply and is planned again in dry2', output)

    def test_fail_case_miss_fixture_fails_cases(self):
        code, output, _target = self.grade_fixture('fail-case-miss')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'cases')
        self.assertIn('HTPR-9387 ended in Todo, expected AI Review', output)

    def test_fail_lock_fixture_fails_finished(self):
        code, output, _target = self.grade_fixture('fail-lock')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'finished')
        self.assertIn('the board lock was held; another run owns this board', output)

    def test_apply_checks_only_appear_with_apply(self):
        _code, output, _target = self.grade_fixture('pass-dry')
        for check in ('apply', 'settled', 'converged'):
            self.assertFalse(any(line.split(':')[0].endswith(' ' + check) for line in output.splitlines()),
                             '%s must not be graded on a dry run:\n%s' % (check, output))

    def copy_fixture(self, case):
        target = self.temp_dir() / case
        shutil.copytree(FIXTURES / case, target)
        return target

    def test_empty_cases_file_is_not_a_failure(self):
        target = self.copy_fixture('pass-dry')
        (target / 'cases.json').write_text('[]\n')
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('PASS cases: no cases file, so no card columns to check', result.stdout)

    def test_malformed_cases_json_fails_cases(self):
        target = self.copy_fixture('pass-dry')
        (target / 'cases.json').write_text('[]\n[not json\n')
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL cases: cases.json is not valid JSON', result.stdout)

    def test_cases_json_that_is_not_a_list_fails_cases(self):
        target = self.copy_fixture('pass-dry')
        (target / 'cases.json').write_text('{"ticket": "HTPR-9514", "expect": "Verification Backlog"}\n')
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL cases: cases.json is not a list of cases', result.stdout)

    def test_cases_already_in_their_column_fail_cases(self):
        target = self.copy_fixture('pass-dry')
        (target / 'dry1.out').write_text(
            'KEEP HTPR-9387 AI Review -> AI Review | open PR checks green\n'
            'KEEP HTPR-9514 Verification Backlog -> Verification Backlog | kept\n'
            'DRY RUN board=15 tickets=366 unknown=0\n')
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL cases: every case was already in the column it belongs in '
                      'when the board was read, so no case proves the reconcile rule',
                      result.stdout)

    def test_cases_starting_outside_their_column_pass_cases(self):
        _code, output, _target = self.grade_fixture('pass-dry')
        self.assertIn('PASS cases: 2 cards in the expected columns in dry1, '
                      '1 of them started outside', output)

    def test_missing_dry2_fails_settled_and_converged(self):
        target = self.copy_fixture('pass-apply-converged')
        (target / 'dry2.out').unlink()
        (target / 'cases.json').write_text('[]\n')
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL settled: the second dry run wrote no summary line, '
                      'so settling cannot be read', result.stdout)
        self.assertIn('FAIL converged: the second dry run wrote no summary line, '
                      'so convergence cannot be read', result.stdout)
        self.assertNotIn('VERDICT PASS', result.stdout)

    def test_missing_apply_output_fails_settled_and_converged(self):
        target = self.copy_fixture('pass-apply-converged')
        (target / 'apply.out').unlink()
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL settled: the apply run wrote no PREVIEW summary, '
                      'so settling cannot be read', result.stdout)
        self.assertIn('FAIL converged: the apply run wrote no PREVIEW summary, '
                      'so convergence cannot be read', result.stdout)

    def test_board_mismatch_fails_finished(self):
        target = self.copy_fixture('pass-dry')
        meta = json.loads((target / 'meta.json').read_text())
        meta['board'] = 2060
        (target / 'meta.json').write_text(json.dumps(meta))
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL finished: the dry run read board 15, not board 2060', result.stdout)

    def test_missing_meta_exits_2(self):
        target = self.copy_fixture('pass-dry')
        (target / 'meta.json').unlink()
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_missing_evidence_dir_exits_2(self):
        missing = self.temp_dir() / 'does-not-exist'
        result = subprocess.run(
            [sys.executable, str(GRADE), str(missing)],
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_missing_dry_run_exits_2(self):
        temp = self.temp_dir()
        shutil.copytree(FIXTURES / 'pass-dry', temp / 'pass-dry')
        (temp / 'pass-dry' / 'dry1.out').unlink()
        result = subprocess.run(
            [sys.executable, str(GRADE), str(temp / 'pass-dry')],
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)


class VerifyReconcileDoctor(unittest.TestCase):
    """The doctor's lock step loads the real reconcile and reads its lock path."""

    RECONCILE = ROOT / 'skills/hypertask-work/reconcile'

    def lock_step_source(self):
        """The python program `run` feeds the lock step, read from `run` itself."""
        text = RUN.read_text()
        start = text.index('LOCK=$(python3 -')
        body_start = text.index('\n', start) + 1
        body_end = text.index('\nPY\n', body_start)
        return text[body_start:body_end]

    def run_lock_step(self, script, board):
        return subprocess.run(
            [sys.executable, '-', str(script), str(board)],
            input=self.lock_step_source(), capture_output=True, text=True, check=False)

    def test_lock_step_reads_the_lock_path_from_the_real_reconcile(self):
        result = self.run_lock_step(self.RECONCILE, 15)
        self.assertEqual(result.returncode, 0,
                         'the lock step could not load reconcile:\n%s' % result.stderr)
        self.assertEqual(result.stdout.strip(),
                         str(Path.home() / '.local/state/fleet/reconcile-15.lock'))

    def test_lock_step_fails_cleanly_when_the_script_is_missing(self):
        result = self.run_lock_step(self.RECONCILE.with_name('no-such-script'), 15)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '')


class VerifyReconcileSkill(unittest.TestCase):
    def test_run_script_parses(self):
        result = subprocess.run(['bash', '-n', str(RUN)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_grade_script_has_shebang(self):
        self.assertEqual(GRADE.read_text().splitlines()[0], '#!/usr/bin/env python3')

    def test_scripts_are_executable(self):
        self.assertTrue(GRADE.stat().st_mode & 0o111, '%s is not executable' % GRADE)
        self.assertTrue(RUN.stat().st_mode & 0o111, '%s is not executable' % RUN)

    def test_run_script_starts_with_apply_off(self):
        text = RUN.read_text()
        self.assertIn('APPLY=0', text, 'a run must start as a dry run')

    def test_run_script_reads_the_lock_path_from_the_script(self):
        text = RUN.read_text()
        self.assertIn('lock_path', text, 'the lock path must come from reconcile itself')
        self.assertNotIn("state/fleet/reconcile-", text, 'the lock path must not be hardcoded')

    def test_run_script_never_deletes_evidence(self):
        text = RUN.read_text()
        self.assertNotIn('rm -rf "$E"', text, 'a run must keep its evidence')
        self.assertNotIn('rm -rf "$HOME/.local/state/verify-reconcile', text)

    def test_run_script_rejects_zero_limit_and_budget(self):
        for flag in ('--limit', '--call-budget'):
            for value in ('0', '-1', 'x'):
                result = subprocess.run(
                    [str(RUN), '--board', '15', flag, value],
                    capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 2,
                                 '%s %s must be refused:\n%s' % (flag, value, result.stdout))
                self.assertNotIn('dry run 1', result.stdout)

    def test_no_live_cases_file_is_shipped(self):
        self.assertFalse((SKILL / 'cases').exists(),
                         'cases are written per report, so the skill ships none')

    def test_skill_has_frontmatter_naming_the_script(self):
        text = (SKILL / 'SKILL.md').read_text()
        self.assertTrue(text.startswith('---\nname: verify-reconcile\n'), text[:80])
        self.assertIn('skills/hypertask-work/reconcile', text)

    def test_feature_map_names_every_file(self):
        features = sorted(path.name for path in (SKILL / 'features').glob('*.md')
                          if path.name != 'README.md')
        self.assertEqual(features, ['apply-converges.md', 'call-budget.md', 'dry-run.md',
                                    'real-cards.md', 'user-bus.md'])
        readme = (SKILL / 'features' / 'README.md').read_text()
        for name in features:
            self.assertIn('(%s)' % name, readme)


if __name__ == '__main__':
    unittest.main()
