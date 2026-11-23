#!/usr/bin/env python3
"""A chat that fails a handover or fresh start files exactly one ticket on board 13556.

The fake hypertask below is the only board in these tests: nothing here talks to the live
board, and no script messages another chat.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'skills/long-chat/failed-handover'
FAKE = (ROOT / 'tests/test_vstack_feedback.py').read_text().split("FAKE = '''", 1)[1].split("'''", 1)[0]
CHAT = 'Demo Chat'
SENTINEL = 'the secret handover text that must never reach a ticket'


class FailedHandover(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.write_token()
        binary = self.home / 'bin' / 'hypertask'
        binary.parent.mkdir(parents=True)
        binary.write_text(FAKE)
        binary.chmod(0o755)
        self.state = self.home / 'state.json'
        self.state.write_text(json.dumps({'calls': [], 'tasks': []}))
        self.runtime(self.home / '.multiprompt-runtime', 7137577663559762)
        self.env = dict(
            os.environ,
            HOME=str(self.home),
            PATH=f'{binary.parent}:{os.environ.get("PATH", "")}',
            FAKE_STATE=str(self.state),
            SHIP_SESSION_NAME=CHAT,
            MULTIPROMPT_TAB='',
        )

    def write_token(self):
        token = (self.home / '.config/hypertask-agents/credentials/sessions'
                 / 'demo-chat-agent-token')
        token.parent.mkdir(parents=True)
        token.write_text('agent-test-token')

    def runtime(self, folder, generation):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'active.json').write_text(json.dumps(
            {'protocol': 1, 'generation': generation, 'sha256': 'a' * 64}))

    def run_tool(self, *args, success=True):
        r = subprocess.run([str(TOOL), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode == 0, success, r.stdout + r.stderr)
        self.assertNotIn('agent-test-token', r.stdout + r.stderr)
        return r

    def data(self):
        return json.loads(self.state.read_text())

    def creates(self):
        return [c for c in self.data()['calls'] if c[:2] == ['task', 'create']]

    def opt(self, call, name):
        return call[call.index(name) + 1] if name in call else None

    def description(self):
        return self.opt(self.creates()[0], '--description')

    def test_failure_files_one_ticket_with_the_facts(self):
        self.run_tool('--step', 'save', '--error', 'Could not save the handover.')
        self.assertEqual(len(self.creates()), 1)
        create = self.creates()[0]
        self.assertEqual(self.opt(create, '--project'), '13556')
        self.assertEqual(self.opt(create, '--labels'), 'Long Chat Handover,brain-medium')
        title = self.opt(create, '--title')
        self.assertIn('save', title)
        self.assertIn(CHAT, title)
        description = self.opt(create, '--description')
        for line in ('Problem', 'Fix', 'Done when', 'Risk', 'Decision'):
            self.assertIn(f'<strong>{line}</strong>', description)
        self.assertIn(f'<li>Chat: {CHAT}</li>', description)
        self.assertIn('<li>Failed step: save</li>', description)
        self.assertIn('Could not save the handover.', description)
        self.assertIn('Runtime generation: 7137577663559762', description)
        self.assertIn('Seen 1 times.', description)

    def test_second_identical_failure_bumps_the_count(self):
        first = self.run_tool('--step', 'read', '--error', 'Could not read the saved handover.')
        second = self.run_tool('--step', 'read', '--error', 'Could not read the saved handover.')
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(self.data()['updated'], 1)
        self.assertIn('Seen 2 times.', self.data()['tasks'][0]['description'])
        self.assertIn('bumped', second.stdout)
        self.assertIn(first.stdout.strip(), second.stdout)

    def test_handover_text_never_reaches_the_ticket(self):
        handover = self.home / '.local/state/long-chat/sess-demo.md'
        handover.parent.mkdir(parents=True)
        handover.write_text(SENTINEL + '\n')
        self.run_tool('--step', 'capture', '--error', 'The handover did not finish.')
        calls = self.data()['calls']
        self.assertEqual(len(self.creates()), 1)
        flatten = json.dumps(calls)
        self.assertNotIn(SENTINEL, flatten)
        self.assertNotIn('sess-demo', flatten)

    def test_unknown_generation_still_files(self):
        (self.home / '.multiprompt-runtime/active.json').unlink()
        self.run_tool('--step', 'resume', '--error', 'Could not deliver the saved handover.')
        self.assertIn('Runtime generation: unknown', self.description())

    def test_runtime_reason_sentence_picks_the_step(self):
        self.run_tool('--error', 'The handover is saved, but reading it failed.')
        self.assertIn('<li>Failed step: read</li>', self.description())

    def test_mp_fresh_reason_slug_picks_the_step(self):
        self.run_tool('--reason', 'handover_write_failed')
        self.assertIn('<li>Failed step: save</li>', self.description())
        self.assertIn('handover_write_failed', self.description())

    def test_busy_is_not_a_failure(self):
        self.run_tool('--reason', 'busy')
        self.assertEqual(self.data()['calls'], [])

    def test_no_chat_login_files_nothing(self):
        env = dict(self.env, SHIP_SESSION_NAME='Missing Agent')
        r = subprocess.run([str(TOOL), '--step', 'save', '--error', 'x'],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('no agent token', r.stderr)
        self.assertEqual(self.data()['calls'], [])

    def test_bad_step_is_refused(self):
        r = subprocess.run([str(TOOL), '--step', 'nonsense', '--error', 'x'],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.data()['calls'], [])


if __name__ == '__main__':
    unittest.main()
