"""A reply that says work is starting now must have started it, on any harness.

The Claude fixtures copy the shapes a 2.1.329 transcript writes; the Antigravity fixtures copy
transcript.jsonl's USER_INPUT and PLANNER_RESPONSE entries, including tool_calls whose args arrive
as JSON-encoded strings.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/said-started.py'
LINK = ROOT / 'skills/responsive-mode/said-started.py'
MESSAGE = ('This reply says work is starting now, but this turn started nothing: no worker launch, commit, '
           'push, file edit or loop. Start it now (launch the worker or make the change), then send one short '
           'line saying what started. If it cannot start now, send one line correcting the reply: say it is '
           'NOT started and why.')


def human(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}}


def bash(command):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 'toolu_1', 'name': 'Bash', 'input': {'command': command}}]}}


def say(text):
    return {'type': 'assistant', 'isSidechain': False,
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


def agy_human(text):
    return {'type': 'USER_INPUT', 'source': 'USER_EXPLICIT', 'status': 'DONE',
            'content': '<USER_REQUEST>\n' + text + '\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\n'
                       'The current local time is: 2026-11-26T15:39:46+01:00.\n</ADDITIONAL_METADATA>'}


def agy_reply(text, tool_calls=None):
    entry = {'type': 'PLANNER_RESPONSE', 'source': 'MODEL', 'status': 'DONE', 'content': text}
    if tool_calls:
        entry['tool_calls'] = tool_calls
    return entry


def agy_call(name, args):
    return {'name': name, 'args': args}


def agy_command(command, encoded=True):
    return agy_call('run_command', {'CommandLine': json.dumps(command) if encoded else command,
                                    'WaitMsBeforeAsync': '5000'})


def agy_system(content):
    return {'type': 'SYSTEM_MESSAGE', 'source': 'SYSTEM', 'status': 'DONE', 'content': content}


class SaidStarted(unittest.TestCase):
    def hook(self, entries):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        transcript = folder / 'transcript.jsonl'
        transcript.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
        payload = json.dumps({'hook_name': 'Stop', 'transcript_path': str(transcript)})
        return subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                              capture_output=True, check=False,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))

    def assert_blocked(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'decision': 'block', 'reason': MESSAGE})

    def assert_allowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '', 'a passing turn prints nothing: ' + result.stdout)

    def test_a_promise_with_no_work_blocks(self):
        self.assert_blocked(self.hook([agy_human('fix the gate'), agy_reply("Next, I'll have a worker do it.")]))

    def test_a_read_only_antigravity_command_blocks(self):
        entries = [agy_human('fix the gate'), agy_reply('', [agy_command('ls -la')]),
                   agy_reply("I'm fixing the gate now.")]
        self.assert_blocked(self.hook(entries))

    def test_an_antigravity_push_passes(self):
        entries = [agy_human('fix the gate'), agy_reply('', [agy_command('git commit -m x && git push')]),
                   agy_reply("I'm fixing the gate now.")]
        self.assert_allowed(self.hook(entries))

    def test_a_plain_string_antigravity_command_passes(self):
        entries = [agy_human('fix the gate'), agy_reply('', [agy_command('git push', encoded=False)]),
                   agy_reply('Building it now.')]
        self.assert_allowed(self.hook(entries))

    def test_an_antigravity_file_write_passes(self):
        entries = [agy_human('fix the gate'),
                   agy_reply('', [agy_call('write_file', {'Path': json.dumps('/tmp/x.py'),
                                                          'Content': json.dumps('x = 1')})]),
                   agy_reply("I'm fixing the gate now.")]
        self.assert_allowed(self.hook(entries))

    def test_an_antigravity_subagent_passes(self):
        entries = [agy_human('fix the gate'),
                   agy_reply('', [agy_call('invoke_subagent', {'Prompt': 'fix it'})]),
                   agy_reply("I'm launching the worker now.")]
        self.assert_allowed(self.hook(entries))

    def test_an_antigravity_workflow_passes(self):
        entries = [agy_human('fix the gate'), agy_reply('', [agy_call('run_workflow', {'Name': 'ship'})]),
                   agy_reply('Starting now.')]
        self.assert_allowed(self.hook(entries))

    def test_a_plan_pick_launch_passes(self):
        entries = [agy_human('fix the gate'),
                   agy_reply('', [agy_command('~/.local/bin/plan-pick --run < brief.txt')]),
                   agy_reply('Starting now.')]
        self.assert_allowed(self.hook(entries))

    def test_a_claude_bash_commit_still_passes(self):
        entries = [human('fix the gate'), bash('git commit -m x'), say("I'm fixing the gate now.")]
        self.assert_allowed(self.hook(entries))

    def test_a_claude_read_only_turn_still_blocks(self):
        entries = [human('fix the gate'), bash('ls'), say('Starting now.')]
        self.assert_blocked(self.hook(entries))

    def test_a_promise_in_an_earlier_turn_does_not_count(self):
        entries = [agy_human('first'), agy_reply("Next, I'll have a worker do it."),
                   agy_human('status?'), agy_reply('Nothing moved.')]
        self.assert_allowed(self.hook(entries))

    def test_harness_noise_after_the_reply_is_ignored(self):
        entries = [agy_human('fix the gate'), agy_system('<SYSTEM_MESSAGE>\nReminder: work efficiently.\n'
                                                        '</SYSTEM_MESSAGE>'),
                   agy_reply('Starting now.')]
        self.assert_blocked(self.hook(entries))

    def test_garbage_and_a_missing_transcript_allow(self):
        for payload in ('not json', '', '[1, 2, 3]', 'null', json.dumps({'cwd': '/tmp'})):
            with self.subTest(payload=payload):
                result = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                                        capture_output=True, check=False)
                self.assert_allowed(result)
        self.assert_allowed(self.hook([]))

    def test_self_test_passes(self):
        result = subprocess.run([sys.executable, str(HOOK), '--self-test'], text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('said-started self-test ok', result.stdout)

    def test_the_skill_runs_the_one_shared_hook(self):
        self.assertTrue(LINK.is_symlink())
        self.assertEqual(LINK.resolve(), HOOK.resolve())


if __name__ == '__main__':
    unittest.main()
