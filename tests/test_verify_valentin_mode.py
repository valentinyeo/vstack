import json
import os
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

SCRATCH = '/tmp/vvm-scratch/.claude/skills/valentin-mode'
HOOKED_VALENTIN = """---
name: valentin-mode
description: test skill
disable-model-invocation: true
hooks:
  PreToolUse:
    - matcher: "*"
      hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/reply-check.py"
  Stop:
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/said-started.py"
---

# Valentin mode

## Three tools
"""


def hook_line(event, name, folder=SCRATCH, matcher=''):
    """One hook line from the debug file, shaped like a live probe."""
    path = '%s/../responsive-mode/%s' % (folder, name)
    return ('2026-11-20T13:34:13.605Z [DEBUG] Hooks: %s%s '
            '[python3 "%s"] finished with status 0 (131ms)\n'
            % (event, ':' + matcher if matcher else '', path))


def ran_valentin_hooks():
    return hook_line('PreToolUse', 'reply-check.py', matcher='Bash') + hook_line(
        'Stop', 'said-started.py')


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
        self.assert_check(output, 'PASS', 'responsive')
        self.assert_check(output, 'PASS', 'session')
        self.assert_check(output, 'PASS', 'login')
        self.assert_check(output, 'PASS', 'pacer')
        self.assert_check(output, 'PASS', 'task')
        self.assert_check(output, 'PASS', 'board sync')
        self.assertIn('PASS loaded: the chat was started with /valentin-mode '
                      '(three tools version, no self-start)', output)
        self.assertFalse(any(line.startswith('FAIL ') for line in output.splitlines()), output)
        verdict = json.loads((target / 'verdict.json').read_text())
        self.assertEqual(verdict['verdict'], 'PASS')
        self.assertEqual(verdict['session_id'], 'sid-pass')
        self.assertEqual(len(verdict['checks']), 8)
        self.assertEqual([check['name'] for check in verdict['checks']][:3],
                         ['loaded', 'responsive', 'checks loaded'])
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

    def test_one_command_fixture_grades_pass(self):
        code, output, _target = self.grade_fixture('one-command')
        self.assertEqual(code, 0, output)
        self.assert_check(output, 'PASS', 'board sync')
        self.assertIn('PASS board sync: dry run then apply, apply clean', output)
        self.assertFalse(any(line.startswith('FAIL ') for line in output.splitlines()), output)

    def test_var_path_fixture_grades_pass(self):
        """A reconcile called through a shell variable is still a board sync."""
        code, output, _target = self.grade_fixture('var-path')
        self.assertEqual(code, 0, output)
        self.assert_check(output, 'PASS', 'board sync')
        self.assertIn('PASS board sync: dry run then apply, apply clean', output)
        self.assertFalse(any(line.startswith('FAIL ') for line in output.splitlines()), output)

    def test_no_responsive_fixture_fails_only_responsive(self):
        code, output, _target = self.grade_fixture('no-responsive')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'responsive')
        self.assertIn('FAIL responsive: responsive mode not loaded', output)
        failed = [line for line in output.splitlines() if line.startswith('FAIL ')]
        self.assertEqual(failed, ['FAIL responsive: responsive mode not loaded'], output)

    def test_responsive_slash_command_prompt_grades_pass(self):
        """A user prompt starting with /responsive-mode is the other accepted way in."""
        target = self.temp_dir() / 'slash'
        shutil.copytree(FIXTURES / 'no-responsive', target)
        events = [json.loads(line) for line in
                  (target / 'stream.jsonl').read_text().splitlines() if line.strip()]
        events.insert(1, {'type': 'user', 'session_id': 'sid-no-responsive',
                          'message': {'content': [{'type': 'text',
                                                   'text': '/responsive-mode stay responsive'}]}})
        (target / 'stream.jsonl').write_text(
            '\n'.join(json.dumps(event) for event in events) + '\n')
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assert_check(result.stdout, 'PASS', 'responsive')
        self.assertIn('PASS responsive: responsive mode started by /responsive-mode',
                      result.stdout)

    def grade_with_user_text(self, text):
        """Grade the no-responsive fixture with one user event carrying `text`."""
        target = self.temp_dir() / 'pasted'
        shutil.copytree(FIXTURES / 'no-responsive', target)
        stream = target / 'stream.jsonl'
        events = [json.loads(line) for line in stream.read_text().splitlines() if line.strip()]
        events.insert(1, {'type': 'user', 'session_id': 'sid-no-responsive',
                          'message': {'content': [{'type': 'text', 'text': text}]}})
        stream.write_text('\n'.join(json.dumps(event) for event in events) + '\n')
        return subprocess.run([sys.executable, str(GRADE), str(target)],
                              capture_output=True, text=True, check=False)

    def responsive_body(self):
        """responsive mode's text below its frontmatter, as the load line prints it."""
        return (ROOT / 'skills/responsive-mode/SKILL.md').read_text().split('---', 2)[2]

    def test_whole_paste_from_the_load_line_grades_pass(self):
        """valentin-mode pastes responsive mode's body at load, so that counts as loaded."""
        result = self.grade_with_user_text(
            '## Responsive mode (pasted in when this skill loads)\n\n' + self.responsive_body())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('PASS responsive: responsive mode pasted in by /valentin-mode',
                      result.stdout)

    def test_unexpanded_load_line_fails_responsive(self):
        """The shell line on its own means the body never arrived."""
        result = self.grade_with_user_text(
            '## Responsive mode (pasted in when this skill loads)\n\n'
            '!`awk \'c>=2{print} /^---$/{c++}\' "x/../responsive-mode/SKILL.md"`')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL responsive: responsive mode not loaded', result.stdout)

    def test_paste_stopped_after_the_first_sentence_fails_responsive(self):
        """A paste cut off before the last sentence loses the end-of-turn rule."""
        result = self.grade_with_user_text(
            '## Responsive mode (pasted in when this skill loads)\n\n'
            'The main chat talks. Background agents work.')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL responsive: responsive mode not loaded', result.stdout)

    def test_valentin_mode_keeps_the_paste_block(self):
        """The skill carries the heading and the line that prints responsive mode's body."""
        text = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
        self.assertIn('## Responsive mode (pasted in when this skill loads)', text)
        self.assertIn('"${CLAUDE_SKILL_DIR}/../responsive-mode/SKILL.md"', text)
        responsive = (ROOT / 'skills/responsive-mode/SKILL.md').read_text()
        self.assertIn('The main chat talks. Background agents work.', responsive)
        self.assertIn('the push lands on the remote with no nudge.', responsive,
                      'the graded last sentence must be the body\'s last sentence')

    def test_not_loaded_fixture_fails_loaded(self):
        code, output, _target = self.grade_fixture('not-loaded')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'loaded')
        self.assertIn('the chat was not told /valentin-mode', output)
        self.assertFalse(any(line.startswith('FAIL loaded: the chat started')
                             for line in output.splitlines()), output)

    def test_self_start_fixture_fails_loaded(self):
        code, output, _target = self.grade_fixture('self-start')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'loaded')
        self.assertIn('the chat started valentin mode by itself', output)
        self.assertFalse(any(line.startswith('FAIL loaded: the chat was not told')
                             for line in output.splitlines()), output)
        self.assertFalse(any(line.startswith('FAIL loaded: valentin-mode is not')
                             for line in output.splitlines()), output)
        self.assertFalse(any(line.startswith('FAIL loaded: installed valentin-mode')
                             for line in output.splitlines()), output)

    def test_old_version_fixture_fails_loaded(self):
        code, output, _target = self.grade_fixture('old-version')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'loaded')
        self.assertIn('installed valentin-mode lacks the Three tools section', output)
        self.assertFalse(any(line.startswith('FAIL loaded: the chat started')
                             for line in output.splitlines()), output)
        self.assertFalse(any(line.startswith('FAIL loaded: installed valentin-mode can')
                             for line in output.splitlines()), output)

    def test_auto_start_on_fixture_fails_loaded(self):
        code, output, _target = self.grade_fixture('auto-start-on')
        self.assertEqual(code, 1, output)
        self.assert_check(output, 'FAIL', 'loaded')
        self.assertIn('installed valentin-mode can still start by itself', output)
        self.assertFalse(any(line.startswith('FAIL loaded: the chat started')
                             for line in output.splitlines()), output)
        self.assertFalse(any(line.startswith('FAIL loaded: installed valentin-mode lacks')
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

    def grade_checks_loaded(self, installed_text, debug_text):
        target = self.temp_dir() / 'hooks'
        shutil.copytree(FIXTURES / 'pass', target)
        (target / 'installed-valentin-mode.md').write_text(installed_text)
        if debug_text is not None:
            (target / 'debug.log').write_text(debug_text)
        return subprocess.run([sys.executable, str(GRADE), str(target)],
                              capture_output=True, text=True, check=False)

    def test_checks_loaded_both_hook_lines_pass(self):
        result = self.grade_checks_loaded(HOOKED_VALENTIN, ran_valentin_hooks())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('PASS checks loaded:', result.stdout)
        self.assertIn('reply-check.py', result.stdout)
        self.assertIn('said-started.py', result.stdout)

    def test_checks_loaded_stop_missing_fails(self):
        debug = hook_line('PreToolUse', 'reply-check.py', matcher='Bash')
        result = self.grade_checks_loaded(HOOKED_VALENTIN, debug)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL checks loaded:', result.stdout)
        self.assertIn('said-started.py (Stop)', result.stdout)

    def test_checks_loaded_unexpanded_root_fails(self):
        debug = ('2026-11-20T13:34:13.605Z [DEBUG] Hooks: PreToolUse:Bash '
                 '[python3 "/../responsive-mode/reply-check.py"] finished with status 0 (131ms)\n'
                 '2026-11-20T13:34:13.605Z [DEBUG] Hooks: Stop '
                 '[python3 "/../responsive-mode/said-started.py"] finished with status 0 (131ms)\n')
        result = self.grade_checks_loaded(HOOKED_VALENTIN, debug)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('FAIL checks loaded:', result.stdout)


class VerifyValentinModeSelfAudit(unittest.TestCase):
    """The planted extra gate is the only finding, and removing it clears the repo."""

    FIXTURE = SKILL / 'fixtures/extra-gate'
    TOOL = ROOT / 'skills/pstack-diff/pstack-diff'
    PSTACK = ROOT / 'tests/fixtures/pstack-diff/pstack'

    def test_planted_gate_then_clean_without_it(self):
        holder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, holder, ignore_errors=True)
        repo = holder / 'extra-gate'
        shutil.copytree(self.FIXTURE, repo)
        env = os.environ.copy()
        env['PSTACK_DIFF_PSTACK'] = str(self.PSTACK)

        before = subprocess.run([sys.executable, str(self.TOOL), str(repo)],
                                capture_output=True, text=True, env=env, check=False)
        self.assertEqual(before.returncode, 1, before.stdout + before.stderr)
        self.assertIn('EXTRA workflow: .github/workflows/ci.yml job scorecard', before.stdout)
        self.assertEqual([line for line in before.stdout.splitlines()
                          if line.startswith('EXTRA ')],
                         ['EXTRA workflow: .github/workflows/ci.yml job scorecard'])

        workflow = repo / '.github/workflows/ci.yml'
        workflow.write_text(workflow.read_text().split('  scorecard:')[0])
        after = subprocess.run([sys.executable, str(self.TOOL), str(repo)],
                               capture_output=True, text=True, env=env, check=False)
        self.assertEqual(after.returncode, 0, after.stdout + after.stderr)
        self.assertNotIn('EXTRA ', after.stdout)


class VerifyValentinModeRunScript(unittest.TestCase):
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        return temp

    def test_run_script_parses(self):
        result = subprocess.run(['bash', '-n', str(RUN)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def break_branch(self):
        lines = RUN.read_text().splitlines()
        starts = [i for i, line in enumerate(lines)
                  if line.strip() == 'if [ -n "$BREAK" ]; then']
        self.assertEqual(len(starts), 1, 'expected one break branch in run')
        ends = [i for i in range(starts[0] + 1, len(lines))
                if lines[i].strip() in ('else', 'fi')]
        self.assertTrue(ends, 'the break branch is never closed')
        return lines[starts[0] + 1:ends[0]]

    def test_run_script_never_blocks_the_skill_or_drops_hooks(self):
        text = RUN.read_text()
        self.assertNotIn('setting-sources', text, 'a run must never drop user hooks')
        self.assertNotIn('disallowedTools', text,
                         'both runs must use the same claude flags')
        self.assertNotIn('Skill(valentin-mode)', text,
                         'the chat itself must prove it cannot start valentin mode')

    def test_run_script_builds_both_prompts(self):
        text = RUN.read_text()
        self.assertEqual(text.count("printf '/valentin-mode %s\\n' \"$JOB\""), 1,
                         'the normal run must start the prompt with /valentin-mode')
        branch = '\n'.join(self.break_branch())
        self.assertIn("printf '%s\\n' \"$JOB\"", branch,
                      'the break must build the job-only prompt')
        self.assertNotIn('/valentin-mode', branch,
                         'the break must never tell the chat /valentin-mode')

    def test_run_script_copies_the_installed_skill(self):
        text = RUN.read_text()
        self.assertIn('INSTALLED="$VSTACK_SKILLS/valentin-mode/SKILL.md"', text)
        self.assertIn('installed-valentin-mode.md', text)
        self.assertNotIn('$HOME/.local/share/vstack/skills', text,
                         'every skill path must come from one VSTACK_DIR root')

    def test_run_script_names_a_missing_skill_folder(self):
        text = RUN.read_text()
        self.assertIn('echo "run: skill folder missing: $VSTACK_SKILLS/$skill" >&2', text)

    def vstack_root_lines(self):
        lines = RUN.read_text().splitlines()
        starts = [i for i, line in enumerate(lines) if line.startswith('VSTACK_ROOT=')]
        self.assertEqual(len(starts), 1, 'expected one VSTACK_ROOT line in run')
        return lines[starts[0]:starts[0] + 2]

    def installed_copy_lines(self):
        lines = RUN.read_text().splitlines()
        starts = [i for i, line in enumerate(lines) if line.startswith('INSTALLED=')]
        self.assertEqual(len(starts), 1, 'expected one INSTALLED line in run')
        ends = [i for i in range(starts[0], len(lines)) if lines[i].strip() == 'fi']
        self.assertTrue(ends, 'the installed copy block is never closed')
        return lines[starts[0]:ends[0] + 1]

    def test_installed_copy_comes_from_the_vstack_dir_tree(self):
        tree = self.temp_dir()
        skill = tree / 'skills/valentin-mode'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('# valentin mode from the temp tree\n')
        evidence = tree / 'evidence'
        evidence.mkdir()
        home = tree / 'home'
        home.mkdir()
        script = '\n'.join(self.vstack_root_lines() + self.installed_copy_lines())
        result = subprocess.run(
            ['bash', '-c', script],
            env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(home),
                 'VSTACK_DIR': str(tree), 'E': str(evidence)},
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        copied = (evidence / 'installed-valentin-mode.md').read_text()
        self.assertEqual(copied, '# valentin mode from the temp tree\n',
                         'the evidence copy must come from $VSTACK_DIR, not $HOME')

    def test_run_script_copies_both_skills_into_scratch(self):
        text = RUN.read_text()
        self.assertIn('cp -rL "$VSTACK_SKILLS/valentin-mode" "$W/.claude/skills/valentin-mode"', text)
        self.assertIn('cp -rL "$VSTACK_SKILLS/responsive-mode" "$W/.claude/skills/responsive-mode"', text)

    def test_run_script_passes_debug_file(self):
        text = RUN.read_text()
        self.assertIn('--debug-file "$E/debug.log"', text)

    def test_grade_script_has_shebang(self):
        self.assertEqual(GRADE.read_text().splitlines()[0], '#!/usr/bin/env python3')

    def test_scripts_are_executable(self):
        self.assertTrue(GRADE.stat().st_mode & 0o111, '%s is not executable' % GRADE)
        self.assertTrue(RUN.stat().st_mode & 0o111, '%s is not executable' % RUN)


if __name__ == '__main__':
    unittest.main()
