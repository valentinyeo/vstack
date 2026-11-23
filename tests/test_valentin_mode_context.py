import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'skills/valentin-mode/context.py'
RESPONSIVE = ROOT / 'skills/responsive-mode/SKILL.md'
LAST = 'the push lands on the remote with no nudge.'


def module():
    spec = importlib.util.spec_from_file_location('valentin_mode_context', MODULE)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def ask(hook, payload, home):
    return json.dumps(hook.answer(payload, home=home))


class ValentinModeContext(unittest.TestCase):
    def test_its_self_test_passes(self):
        result = subprocess.run([sys.executable, str(MODULE), '--self-test'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('context self-test ok', result.stdout)

    def test_the_first_tool_call_carries_the_version_line_and_the_whole_body(self):
        hook = module()
        with tempfile.TemporaryDirectory() as home:
            answer = json.loads(ask(hook, {'session_id': 'sid'}, home))
        context = answer['hookSpecificOutput']['additionalContext']
        self.assertEqual(answer['hookSpecificOutput']['hookEventName'], 'PreToolUse')
        self.assertIn('valentin-mode v', context)
        self.assertIn('# Responsive mode', context)
        self.assertIn(LAST, context)

    def test_one_chat_gets_the_body_once(self):
        hook = module()
        with tempfile.TemporaryDirectory() as home:
            first = json.loads(ask(hook, {'session_id': 'sid'}, home))
            later = json.loads(ask(hook, {'session_id': 'sid'}, home))
        self.assertTrue(first['hookSpecificOutput']['additionalContext'])
        self.assertEqual(later, {}, 'every later tool call in the same chat says nothing')

    def test_unanswered_messages_remind_without_denying_before_and_after_rules_arrive(self):
        reminder = ("Valentin's newest message has no reply yet. Answer it directly, then continue the work. "
                    "No separate acknowledgment.")
        for human in ({'type': 'user', 'message': {'content': 'status?'}},
                      {'type': 'attachment', 'attachment': {'type': 'queued_command', 'prompt': 'status?'}}):
            with self.subTest(kind=human['type']), tempfile.TemporaryDirectory() as home:
                transcript = Path(home) / 'transcript.jsonl'
                transcript.write_text(json.dumps(human) + '\n')
                payload = json.dumps({'session_id': 'sid', 'transcript_path': str(transcript)})
                env = dict(os.environ, HOME=home, REPLY_CHECK_RETRIES='1')
                for step in range(3):
                    result = subprocess.run([sys.executable, str(MODULE)], input=payload,
                                            text=True, capture_output=True, env=env, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, '')
                    output = json.loads(result.stdout)
                    if step == 0:
                        hook = output['hookSpecificOutput']
                        self.assertEqual(set(hook), {'hookEventName', 'additionalContext'})
                        self.assertEqual(hook['hookEventName'], 'PreToolUse')
                        self.assertTrue(hook['additionalContext'].startswith(reminder + '\n\n'))
                        self.assertIn('valentin-mode v', hook['additionalContext'])
                        self.assertIn(LAST, hook['additionalContext'])
                    else:
                        self.assertEqual(output, {'hookSpecificOutput': {
                            'hookEventName': 'PreToolUse', 'additionalContext': reminder}})
                with transcript.open('a') as handle:
                    handle.write(json.dumps({'type': 'assistant',
                                             'message': {'content': 'Two of four done.'}}) + '\n')
                result = subprocess.run([sys.executable, str(MODULE)], input=payload,
                                        text=True, capture_output=True, env=env, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                self.assertEqual(json.loads(result.stdout), {})

    def test_another_chat_still_gets_its_rules(self):
        hook = module()
        with tempfile.TemporaryDirectory() as home:
            ask(hook, {'session_id': 'first'}, home)
            second = json.loads(ask(hook, {'session_id': 'second'}, home))
        self.assertIn('additionalContext', second['hookSpecificOutput'])

    def test_a_chat_without_a_session_id_is_tracked_by_its_transcript(self):
        hook = module()
        with tempfile.TemporaryDirectory() as home:
            payload = {'transcript_path': '/tmp/one.jsonl'}
            first = json.loads(ask(hook, payload, home))
            later = json.loads(ask(hook, payload, home))
        self.assertIn('additionalContext', first['hookSpecificOutput'])
        self.assertEqual(later, {})

    def test_the_body_starts_after_the_second_fence(self):
        hook = module()
        self.assertEqual(hook.body_after_frontmatter('---\nname: x\n---\n\n# Title\ntext\n'),
                         '# Title\ntext')
        self.assertEqual(hook.body_after_frontmatter('no fences here'), '')

    def test_main_prints_one_json_answer_and_fails_open(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home)
            first = subprocess.run([sys.executable, str(MODULE)], input='{"session_id": "sid"}',
                                   text=True, capture_output=True, env=env)
            later = subprocess.run([sys.executable, str(MODULE)], input='{"session_id": "sid"}',
                                   text=True, capture_output=True, env=env)
            broken = subprocess.run([sys.executable, str(MODULE)], input='not json',
                                    text=True, capture_output=True, env=env)
        self.assertIn('additionalContext', json.loads(first.stdout)['hookSpecificOutput'])
        self.assertEqual(json.loads(later.stdout), {})
        self.assertEqual(broken.returncode, 0)
        self.assertEqual(broken.stdout.strip(), '')

    def test_a_missing_body_puts_nothing_in_the_chat(self):
        hook = module()
        with tempfile.TemporaryDirectory() as home:
            original = hook.RESPONSIVE
            hook.RESPONSIVE = Path(home) / 'gone.md'
            try:
                answer = hook.answer({'session_id': 'sid'}, home=home)
            finally:
                hook.RESPONSIVE = original
        self.assertEqual(answer, {})


if __name__ == '__main__':
    unittest.main()
