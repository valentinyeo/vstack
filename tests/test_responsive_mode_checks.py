"""What a chat observes with responsive-mode loaded: an unanswered message prompts a reminder without
blocking tools, and a chat that says work started must have started it.

The fixtures are hand-written JSONL that copies the shapes found in a real 2.1.329 transcript. No private
text is copied here.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/responsive-mode'
CHECK = SKILL / 'reply-check.py'
REMINDER = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "additionalContext": ("Valentin's newest message has no reply yet. Answer it "
                                                        "directly, then continue the work. "
                                                        "No separate acknowledgment.")}}
MERGE_REMINDER_TEXT = ("This reply asks Valentin to merge, ship, approve or review a pull request. "
                       "The fix: merge it yourself per pstack shipping; ask him only a product question. "
                       "Carry it through babysit until it is green and mergeable, merge it, prove it live "
                       "on the real case, then report that. Ask him only a product question.")


def human(text):
    """Typed while the chat was idle: a user entry carrying the text."""
    return {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}}


def human_string(text):
    """Sometimes the same message is stored as a plain string."""
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def queued(text):
    """Typed mid-turn: an attachment entry, written where the next tool result lands."""
    return {'type': 'attachment', 'attachment': {
        'type': 'queued_command', 'prompt': [{'type': 'text', 'text': text}], 'hostsOwnTurn': True},
        'rendered': [{'content': [{'type': 'text', 'text': '<system-reminder>\nThe user sent a new message while '
                                                          'you were working:\n' + text + '\n</system-reminder>'}]}],
        'renderedRole': 'system'}


def say(text):
    return {'type': 'assistant', 'isSidechain': False,
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


def tool_call(name='Bash'):
    return {'type': 'assistant', 'isSidechain': False,
            'message': {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': 'toolu_1', 'name': name, 'input': {'command': 'ls'}}]}}


def tool_result():
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': 'ok'}]}}


def meta(text):
    """isMeta entries: skill body expansions and harness notes. Only a human message is not meta."""
    return {'type': 'user', 'isMeta': True, 'message': {'role': 'user',
                                                        'content': [{'type': 'text', 'text': text}]}}


def notification():
    return human('<task-notification>\n<task-id>bjt9kgygt</task-id>\n<output-file>/tmp/x.txt</output-file>\n'
                 '</task-notification>')


def skill_body():
    return meta('Base directory for this skill: /home/x/.claude/skills/responsive-mode\n\n# Responsive mode\n')


def system_reminder():
    return human('<system-reminder>noted</system-reminder>')


def slash(name, args=None):
    text = f'<command-message>{name}</command-message>\n<command-name>/{name}</command-name>'
    if args is not None:
        text += f'\n<command-args>{args}</command-args>'
    return human(text)


def tempdir(test):
    folder = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, folder, ignore_errors=True)
    return Path(folder)


class ReplyCheck(unittest.TestCase):
    def hook(self, entries=None, transcript=None, payload=None, env=None):
        if transcript is None:
            transcript = str(tempdir(self) / 'transcript.jsonl')
            Path(transcript).write_text(''.join(json.dumps(entry) + '\n' for entry in entries or []))
        if payload is None:
            payload = json.dumps({'hook_name': 'PreToolUse', 'tool_name': 'Bash',
                                  'transcript_path': transcript})
        run_env = os.environ.copy()
        run_env.setdefault('REPLY_CHECK_RETRIES', '3')
        run_env.setdefault('REPLY_CHECK_DELAY_MS', '1')
        if env:
            run_env.update(env)
        return subprocess.run([sys.executable, str(CHECK)], input=payload, text=True,
                              capture_output=True, check=False, env=run_env)

    def assert_reminded(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), REMINDER)
        self.assertEqual(result.stderr, '')

    def assert_allowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '', 'a passing call prints nothing: ' + result.stdout)

    def test_an_unanswered_message_reminds_without_blocking(self):
        self.assert_reminded(self.hook([human('push it once the tests pass'), tool_call()]))

    def test_a_message_sent_mid_turn_reminds_without_blocking(self):
        entries = [human('do the ticket'), tool_call(), tool_result(), queued('is it reliable?'), tool_call()]
        self.assert_reminded(self.hook(entries))

    def test_each_step_reminds_until_a_reply_exists(self):
        entries = [human('status?'), tool_call()]
        for _ in range(3):
            self.assert_reminded(self.hook(entries))
            entries.extend([tool_result(), tool_call()])
        entries.append(say('Two of four done.'))
        self.assert_allowed(self.hook(entries))

    def test_a_plain_string_message_counts(self):
        self.assert_reminded(self.hook([human_string('doyou want me to paste these promptps?'), tool_call()]))

    def test_a_reply_before_the_tool_step_passes(self):
        entries = [human('push it'), say('Pushed. Watching CI.'), tool_call()]
        self.assert_allowed(self.hook(entries))

    def test_a_reply_to_the_mid_turn_message_passes(self):
        entries = [human('do the ticket'), tool_call(), tool_result(),
                   queued('is it reliable?'), say('Every change is judged by its test.'), tool_call()]
        self.assert_allowed(self.hook(entries))

    def test_a_reply_after_the_last_tool_step_passes(self):
        entries = [human('status?'), tool_call(), tool_result(), say('Two of four done.')]
        self.assert_allowed(self.hook(entries))

    def test_a_task_notification_is_not_him_talking(self):
        entries = [human('ship it'), say('On it.'), tool_call(), tool_result(), notification(), tool_call()]
        self.assert_allowed(self.hook(entries))

    def test_automated_messages_do_not_demand_an_acknowledgment(self):
        for text in ('<teammate-message teammate_id="peer">No change.</teammate-message>',
                     '[Message from session peer] No change.',
                     '[Cross-session message from peer] No change.',
                     '[from peer] No change.',
                     "The user hasn't heard from you in a while",
                     'The user hasn’t heard from you in a while'):
            with self.subTest(text=text):
                self.assert_allowed(self.hook([human('ship it'), say('On it.'), human(text), tool_call()]))
                self.assert_allowed(self.hook([say('On it.'), queued(text), tool_call()]))
                self.assert_reminded(self.hook([human('status?'), human(text), tool_call()]))

    def test_a_tool_result_is_not_him_talking(self):
        entries = [human('ship it'), say('On it.'), tool_call(), tool_result(), tool_call()]
        self.assert_allowed(self.hook(entries))

    def test_a_skill_body_expansion_is_not_him_talking(self):
        entries = [human('/responsive-mode be fast'), say('On.'), tool_call(), tool_result(),
                   skill_body(), tool_call()]
        self.assert_allowed(self.hook(entries))

    def test_a_system_reminder_does_not_answer_him(self):
        entries = [human('ship it'), tool_call(), tool_result(), system_reminder(), tool_call()]
        self.assert_reminded(self.hook(entries))

    def test_a_slash_command_with_args_counts(self):
        self.assert_reminded(self.hook([slash('responsive-mode', 'no thats what the skill should ask for'),
                                      tool_call()]))

    def test_a_slash_command_without_args_does_not_count(self):
        self.assert_allowed(self.hook([slash('pstack:create-verification-skill'), tool_call()]))

    def test_no_human_message_at_all_passes(self):
        self.assert_allowed(self.hook([tool_call(), tool_result(), notification(), skill_body()]))

    def test_garbage_input_passes(self):
        for payload in ('not json at all', '', '[1, 2, 3]', 'null', json.dumps({'tool_name': 'Bash'})):
            with self.subTest(payload=payload):
                self.assert_allowed(self.hook(payload=payload))

    def test_a_missing_or_unreadable_transcript_passes(self):
        self.assert_allowed(self.hook(transcript='/nonexistent/transcript.jsonl'))
        garbage = tempdir(self) / 'transcript.jsonl'
        garbage.write_text('{oops\n\n[1,2]\n"a string"\n')
        self.assert_allowed(self.hook(transcript=str(garbage)))

    def test_a_final_reply_that_hands_him_the_pr_gets_a_reminder(self):
        entries = [human('do the ticket'),
                   say('Finished and green. Ready for your review: '
                       'https://github.com/valentinyeo/multiprompt-android/pull/524')]
        result = self.hook(entries, payload=json.dumps({'hook_event_name': 'Stop',
                                                       'transcript_path': self.transcript(entries)}))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output, {'hookSpecificOutput': {'hookEventName': 'Stop',
                                                        'additionalContext': MERGE_REMINDER_TEXT}})
        self.assertNotIn('permissionDecision', output['hookSpecificOutput'])
        self.assertNotIn('decision', output)

    def test_a_final_reply_asking_for_his_ship_gets_a_reminder(self):
        entries = [human('do the ticket'),
                   say("The change is finished and green. Say ship and I'll merge it.")]
        result = self.hook(entries, payload=json.dumps({'hook_event_name': 'Stop',
                                                       'transcript_path': self.transcript(entries)}))
        self.assertIn('merge it yourself per pstack shipping', json.loads(result.stdout)
                      ['hookSpecificOutput']['additionalContext'])

    def test_a_product_question_at_stop_passes(self):
        entries = [human('do the ticket'), say('Should the button be blue or green?')]
        result = self.hook(entries, payload=json.dumps({'hook_event_name': 'Stop',
                                                       'transcript_path': self.transcript(entries)}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '')

    def test_a_finished_merge_report_at_stop_passes(self):
        entries = [human('do the ticket'), say('Merged PR #524 and proved it live on the phone.')]
        result = self.hook(entries, payload=json.dumps({'hook_event_name': 'Stop',
                                                       'transcript_path': self.transcript(entries)}))
        self.assertEqual(result.stdout.strip(), '')

    def transcript(self, entries):
        path = tempdir(self) / 'transcript.jsonl'
        path.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
        return str(path)

    def test_self_test_passes(self):
        result = subprocess.run([sys.executable, str(CHECK), '--self-test'], text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('reply-check self-test ok', result.stdout)

    def test_late_transcript_reply_is_allowed_after_retry(self):
        """Mimics Claude Code appending the assistant text line after the hook starts."""
        folder = tempdir(self)
        transcript = folder / 'transcript.jsonl'
        transcript.write_text(json.dumps(human('wait for me')) + '\n' + json.dumps(tool_call()) + '\n')

        def append_reply():
            time.sleep(0.5)
            with transcript.open('a') as handle:
                handle.write(json.dumps(say('On it.')) + '\n')

        threading.Thread(target=append_reply, daemon=True).start()
        fast = {'REPLY_CHECK_RETRIES': '12', 'REPLY_CHECK_DELAY_MS': '100'}
        self.assert_allowed(self.hook(transcript=str(transcript), env=fast))

    def test_still_unanswered_reminds_after_retries(self):
        fast = {'REPLY_CHECK_RETRIES': '3', 'REPLY_CHECK_DELAY_MS': '10'}
        started = time.monotonic()
        self.assert_reminded(self.hook([human('no answer coming'), tool_call()], env=fast))
        self.assertGreaterEqual(time.monotonic() - started, 0.02)

    def test_existing_reply_allows_without_waiting(self):
        slow = {'REPLY_CHECK_RETRIES': '8', 'REPLY_CHECK_DELAY_MS': '250'}
        started = time.monotonic()
        entries = [human('ship it'), say('Pushed.'), tool_call()]
        self.assert_allowed(self.hook(entries, env=slow))
        # Seven sleeps would take 1.75s; a hit on the first read must finish well before that.
        self.assertLess(time.monotonic() - started, 1.0)


class SkillWiring(unittest.TestCase):
    """Loading the skill is what switches both checks on, so the wiring is the feature."""

    def setUp(self):
        self.text = (SKILL / 'SKILL.md').read_text()

    def test_the_frontmatter_registers_the_checks(self):
        for line in ('  PreToolUse:', '    - matcher: "*"', '  Stop:',
                     'command: python3 "$CLAUDE_PLUGIN_ROOT/reply-check.py"',
                     'command: python3 "$CLAUDE_PLUGIN_ROOT/said-started.py"'):
            self.assertIn(line, self.text, 'the skill lost ' + line.strip())

    def test_both_scripts_sit_beside_the_skill(self):
        for name in ('reply-check.py', 'said-started.py'):
            self.assertTrue((SKILL / name).exists(), name + ' is missing from the skill folder')

    def test_said_started_is_the_one_shared_copy(self):
        link = SKILL / 'said-started.py'
        self.assertTrue(link.is_symlink(), 'said-started.py must be a symlink to the shared hook')
        self.assertEqual(link.resolve().name, 'said-started.py')
        self.assertEqual(link.resolve().parent, ROOT / 'hooks')

    def test_the_body_names_the_checks(self):
        self.assertIn('Loading this skill turns on four checks in this chat', self.text)


if __name__ == '__main__':
    unittest.main()
