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
    def grade(self, records, spec=None, ran=(1,), pushed=(LINE,), loaded=True):
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
        if loaded:
            (evidence / 'transcript.jsonl').write_text(json.dumps(
                {'type': 'user', 'isMeta': True,
                 'message': {'content': MARKER + '\n...'}}) + '\n')
        (evidence / 'pushed-report.md').write_text(''.join(line + '\n' for line in pushed))
        result = subprocess.run([sys.executable, str(GRADE), str(evidence)],
                                capture_output=True, text=True, check=False)
        return result.returncode, result.stdout

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
        for check in ('loaded', 'reply 1', 'reply 2', 'separate', 'background',
                      'slow step 1 ran', 'pushed'):
            self.assert_passes(code, output, check)

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


if __name__ == '__main__':
    unittest.main()
