import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.claude/skills/verify-responsive-mode'
GRADE = SKILL / 'grade.py'
RUN = SKILL / 'run'

LINE = 'report abc123'
HOOKED_SKILL = """---
name: responsive-mode
description: test skill
hooks:
  PreToolUse:
    - matcher: "*"
      hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/reply-check.py"
  Stop:
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/said-started.py"
---

# Responsive mode
"""
PLAIN_SKILL = """---
name: responsive-mode
description: test skill
---

# Responsive mode
"""
LINE2 = 'published def456'
MARKER = '# Responsive mode'
TRACKED = {'command': './slow-report.sh', 'run_in_background': True}
QUESTIONS = ((25, 'Side question: what is 17 + 25?', '42'),
             (40, 'Another one: what is the capital of France?', 'Paris'))
HARD_QUESTIONS = ((100, 'And how many days are in a leap year?', '366'),
                  (150, 'Last one: what colour do you get mixing blue and yellow?', 'green'))


def sent(t, text):
    return {'t': t, 'sent': text}


def say(t, text, message_id=None):
    message = {'content': [{'type': 'text', 'text': text}]}
    if message_id:
        message['id'] = message_id
    return {'t': t, 'ev': {'type': 'assistant', 'message': message}}


def hook_run(event, command, kind='hook_success'):
    """One hook attachment entry, shaped like the ones a real transcript logs."""
    return {'type': 'attachment',
            'attachment': {'type': kind, 'hookName': event + ':Bash',
                           'hookEvent': event, 'command': command, 'exitCode': 0}}


def ran_hooks(prefix='/tmp/vrm-scratch/.claude/skills/responsive-mode-under-test'):
    return (hook_run('PreToolUse', 'python3 "%s/reply-check.py"' % prefix),
            hook_run('Stop', 'python3 "%s/said-started.py"' % prefix))


def tool(t, name, args):
    return {'t': t, 'ev': {'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'name': name, 'input': args}]}}}


def chat(delays=(4, 3), answers=('42.', 'Paris.'), slow=None, extra=()):
    """A passing chat: the job goes out, the slow step is tracked, each side
    question gets its own quick reply, then the push lands."""
    records = [sent(0, '/responsive-mode-under-test job'),
               tool(5, 'Bash', slow or TRACKED)]
    for (at, question, _), delay, answer in zip(QUESTIONS, delays, answers):
        records += [sent(at, question), say(at + delay, answer)]
    for at, question, answer in extra:
        records += [sent(at, question), say(at + 4, answer)]
    records += [tool(max(r.get('t', 0) for r in records) + 10, 'Bash',
                     {'command': 'git push origin main'}),
                say(max(r.get('t', 0) for r in records) + 12, 'Pushed REPORT.md.')]
    return records


def hard_chat():
    return chat(extra=[(at, question, answer + '.') for at, question, answer in HARD_QUESTIONS])


class VerifyResponsiveModeGrade(unittest.TestCase):
    def evidence(self, records, spec=None, ran=(1,), pushed=(LINE,), loaded=True,
                 skill_md=None, hooks=()):
        """A run's evidence folder, built the way run leaves one behind."""
        evidence = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, evidence, ignore_errors=True)
        (evidence / 'chat.jsonl').write_text(
            ''.join(json.dumps(record) + '\n' for record in records))
        (evidence / 'spec.json').write_text(json.dumps(spec or {
            'skill_marker': MARKER,
            'answers': ['42', 'Paris'],
            'slow_step': 'slow-report',
            'expected_lines': [LINE],
        }))
        for index in ran:
            (evidence / f'ran{index if index > 1 else ""}.txt').write_text('done\n')
        if skill_md is not None:
            (evidence / 'skill-under-test').mkdir()
            (evidence / 'skill-under-test/SKILL.md').write_text(skill_md)
        transcript = ([{'type': 'user', 'isMeta': True,
                        'message': {'content': MARKER + '\n...'}}] if loaded else [])
        (evidence / 'transcript.jsonl').write_text(
            ''.join(json.dumps(record) + '\n' for record in transcript + list(hooks)))
        (evidence / 'pushed-report.md').write_text(''.join(line + '\n' for line in pushed))
        return evidence

    def grade_folder(self, evidence):
        result = subprocess.run([sys.executable, str(GRADE), str(evidence)],
                                capture_output=True, text=True, check=False)
        return result.returncode, result.stdout

    def grade(self, records, **kwargs):
        return self.grade_folder(self.evidence(records, **kwargs))

    def assert_fails(self, output, check):
        self.assertIn('VERDICT FAIL', output.splitlines(), output)
        self.assertTrue(any(line.startswith('FAIL ' + check + ':') for line in output.splitlines()),
                        'expected a FAIL %r line, got:\n%s' % (check, output))

    def assert_passes(self, code, output, check):
        self.assertEqual(code, 0, output)
        self.assertIn('VERDICT PASS', output.splitlines(), output)
        self.assertTrue(any(line.startswith('PASS ' + check + ':') for line in output.splitlines()),
                        'expected a PASS %r line, got:\n%s' % (check, output))

    def test_good_run_passes(self):
        self.assert_passes(*self.grade(chat()), 'loaded')

    def test_every_check_reports(self):
        code, output = self.grade(chat())
        self.assertEqual(code, 0, output)
        for check in ('loaded', 'checks loaded', 'reply 1', 'reply 2', 'separate', 'background',
                      'slow step 1 ran', 'pushed'):
            self.assert_passes(code, output, check)

    def test_skill_with_no_hooks_passes_checks_loaded(self):
        code, output = self.grade(chat(), skill_md=PLAIN_SKILL)
        self.assert_passes(code, output, 'checks loaded')
        self.assertIn('turns no hooks on', output)

    def test_hooks_block_with_no_transcript_hook_runs_fails(self):
        self.assert_fails(self.grade(chat(), skill_md=HOOKED_SKILL)[1], 'checks loaded')

    def test_hooks_that_ran_in_the_transcript_pass(self):
        code, output = self.grade(chat(), skill_md=HOOKED_SKILL, hooks=ran_hooks())
        self.assert_passes(code, output, 'checks loaded')
        line = next(line for line in output.splitlines() if line.startswith('PASS checks loaded:'))
        self.assertIn('reply-check.py', line)
        self.assertIn('said-started.py', line)

    def test_a_foreign_pretooluse_hook_does_not_count(self):
        """The box runs other PreToolUse hooks. Only the skill's own files count."""
        hooks = (hook_run('PreToolUse', 'python3 /home/valentin/.claude/hooks/chromescribe-link.py'),)
        self.assert_fails(self.grade(chat(), skill_md=HOOKED_SKILL, hooks=hooks)[1], 'checks loaded')

    def test_one_declared_hook_never_running_fails(self):
        output = self.grade(chat(), skill_md=HOOKED_SKILL, hooks=ran_hooks()[:1])[1]
        self.assert_fails(output, 'checks loaded')
        self.assertIn('said-started.py', output)

    def test_a_hook_named_in_chat_text_only_fails(self):
        """The chat saying a hook ran is not the hook running."""
        message = {'type': 'user', 'isMeta': True,
                   'message': {'content': 'reply-check.py said-started.py ran'}}
        self.assert_fails(self.grade(chat(), skill_md=HOOKED_SKILL, hooks=(message,))[1],
                          'checks loaded')

    def test_old_evidence_without_skill_text_passes_checks_loaded(self):
        code, output = self.grade(chat())
        self.assert_passes(code, output, 'checks loaded')
        self.assertIn('no skill text in evidence', output)

    def test_a_run_holding_only_the_single_file_reads_its_hooks(self):
        """A run made before the folder copy has skill-under-test.md alone, and
        its hooks block still counts, so old evidence regrades the same way."""
        evidence = self.evidence(chat())
        (evidence / 'skill-under-test.md').write_text(HOOKED_SKILL)
        self.assert_fails(self.grade_folder(evidence)[1], 'checks loaded')

    def test_slow_reply_fails(self):
        self.assert_fails(self.grade(chat(delays=(95, 3)))[1], 'reply 1')

    def test_missing_reply_fails(self):
        records = [record for record in chat() if record.get('t') not in (43,)]
        self.assert_fails(self.grade(records)[1], 'reply 2')

    def test_merged_answers_fail(self):
        records = [record for record in chat() if record.get('t') not in (29, 43)]
        records.append(say(45, '42, and Paris.'))
        self.assert_fails(self.grade(records)[1], 'separate')

    def test_two_blocks_of_one_message_fail_separate(self):
        records = [record for record in chat() if record.get('t') not in (29, 43)]
        records += [say(45, '42.', 'msg_one'), say(45, 'Paris.', 'msg_one')]
        self.assert_fails(self.grade(records)[1], 'separate')

    def test_string_false_background_flag_fails(self):
        records = chat(slow={'command': './slow-report.sh', 'run_in_background': 'false'})
        self.assert_fails(self.grade(records)[1], 'background')

    def test_foreground_slow_step_fails(self):
        records = chat(slow={'command': './slow-report.sh && echo hi'})
        self.assert_fails(self.grade(records)[1], 'background')

    def test_nohup_slow_step_fails(self):
        self.assert_fails(
            self.grade(chat(slow={'command': 'nohup ./slow-report.sh > out.txt'}))[1], 'background')

    def test_ampersand_slow_step_fails(self):
        self.assert_fails(
            self.grade(chat(slow={'command': './slow-report.sh > out.txt &'}))[1], 'background')

    def test_tmux_slow_step_fails(self):
        self.assert_fails(
            self.grade(chat(slow={'command': 'tmux new -d ./slow-report.sh'}))[1], 'background')

    def test_job_not_pushed_fails(self):
        self.assert_fails(self.grade(chat(), pushed=())[1], 'pushed')

    def test_another_runs_report_line_fails(self):
        """The flaw this check was written for: two runs at once shared a /tmp
        file and one graded PASS on the other run's line. The grade ignores
        nothing, so a foreign line never passes."""
        self.assert_fails(self.grade(chat(), pushed=('report fedcba',))[1], 'pushed')

    def test_slow_step_never_finished_fails(self):
        self.assert_fails(self.grade(chat(), ran=())[1], 'slow step 1 ran')

    def test_skill_not_loaded_fails(self):
        self.assert_fails(self.grade(chat(), loaded=False)[1], 'loaded')

    def test_spec_with_one_expected_line_passes(self):
        code, output = self.grade(chat(), spec={'skill_marker': MARKER, 'answers': ['42', 'Paris'],
                                                'slow_step': 'slow-report',
                                                'expected_line': LINE})
        self.assert_passes(code, output, 'pushed')

    def test_hard_run_passes(self):
        spec = {'skill_marker': MARKER, 'answers': ['42', 'Paris', '366', 'green'],
                'slow_step': 'slow-report', 'expected_lines': [LINE, LINE2]}
        code, output = self.grade(hard_chat(), spec=spec, ran=(1, 2), pushed=(LINE, LINE2))
        self.assert_passes(code, output, 'slow step 2 ran')

    def test_hard_run_missing_second_line_fails(self):
        spec = {'skill_marker': MARKER, 'answers': ['42', 'Paris', '366', 'green'],
                'slow_step': 'slow-report', 'expected_lines': [LINE, LINE2]}
        self.assert_fails(
            self.grade(hard_chat(), spec=spec, ran=(1, 2), pushed=(LINE,))[1], 'pushed')

    def test_no_evidence_is_a_usage_error(self):
        evidence = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, evidence, ignore_errors=True)
        result = subprocess.run([sys.executable, str(GRADE), str(evidence)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)


class VerifyResponsiveModeRun(unittest.TestCase):
    """run is never launched here: it starts a paid chat. Its own text is checked."""

    def setUp(self):
        self.text = RUN.read_text()

    def test_job_keeps_each_runs_temp_files_in_its_own_folder(self):
        # Both job shapes carry the rule: two runs at once must not share a path.
        self.assertEqual(self.text.count('Keep every temporary file inside this working folder'), 2)

    def test_job_forbids_tmp(self):
        self.assertEqual(self.text.count('never in /tmp'), 2)

    def test_run_has_no_shared_report_path(self):
        self.assertNotIn('/tmp/vrm-report', self.text)

    def test_run_keeps_the_flags(self):
        for flag in ('--skill', '--hard', '--break', '--keep'):
            self.assertIn(flag + ')', self.text, 'run lost ' + flag)
            self.assertIn(flag, self.text, 'run lost ' + flag)

    def test_break_takes_one_value(self):
        self.assertIn('no-responsive-mode', self.text)

    def test_run_takes_the_skill_folder_from_the_skill_path(self):
        self.assertIn('SKILL_DIR=$(dirname "$SKILL")', self.text)
        self.assertIn('cp -rL "$SKILL_DIR" "$W/.claude/skills/$NAME"', self.text)
        self.assertNotIn('mkdir -p "$W/.claude/skills/$NAME"', self.text,
                         'a bare mkdir would leave the hooks behind')

    def test_run_saves_the_whole_folder_in_the_evidence(self):
        self.assertIn('cp -rL "$SKILL_DIR" "$E/skill-under-test"', self.text)
        self.assertIn('cp "$SKILL" "$E/skill-under-test.md"', self.text,
                      'the single evidence file stays as it was')


class VerifyResponsiveModeCopy(unittest.TestCase):
    """The copy steps of run, run for real on a small skill folder. No chat
    starts: only the two commands that put the folder in the scratch project."""

    def setUp(self):
        self.text = RUN.read_text()
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def fixture(self):
        """A skill folder whose hook is a symlink, like skills/responsive-mode."""
        real = self.work / 'hooks'
        real.mkdir()
        (real / 'said-started.py').write_text('# said-started\n')
        folder = self.work / 'skills/responsive-mode'
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text('---\nname: responsive-mode\n---\n\n# Responsive mode\n')
        (folder / 'reply-check.py').write_text('# reply-check\n')
        (folder / 'said-started.py').symlink_to('../../hooks/said-started.py')
        return folder

    def copy_block(self):
        """The real lines from run, with the scratch project's parent as $W."""
        lines = self.text.splitlines()
        cp = next(i for i, line in enumerate(lines)
                  if line.startswith('cp -rL "$SKILL_DIR" "$W/.claude/skills/$NAME"'))
        sed = next(i for i, line in enumerate(lines)
                   if line.startswith('sed "s/^name: responsive-mode$'))
        return '\n'.join([lines[cp]] + lines[sed:sed + 3])

    def test_copy_brings_every_hook_file_and_renames_the_skill(self):
        proj = self.work / 'project'
        proj.mkdir()
        env = {'PATH': '/usr/bin:/bin', 'W': str(proj), 'NAME': 'responsive-mode-under-test',
               'SKILL_DIR': str(self.fixture())}
        script = 'set -euo pipefail\nmkdir -p "$W/.claude/skills"\n' + self.copy_block() + '\n'
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                check=False, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        copied = proj / '.claude/skills/responsive-mode-under-test'
        for name in ('SKILL.md', 'reply-check.py', 'said-started.py'):
            self.assertTrue((copied / name).is_file(), 'copy lost ' + name)
        self.assertFalse((copied / 'said-started.py').is_symlink(),
                         'the hook symlink was not followed')
        self.assertEqual((copied / 'said-started.py').read_text(), '# said-started\n')
        self.assertTrue((copied / 'SKILL.md').read_text().splitlines()[1]
                        == 'name: responsive-mode-under-test')
        self.assertFalse((copied / 'SKILL.md.renamed').exists(), 'the renamed file was left behind')


if __name__ == '__main__':
    unittest.main()
