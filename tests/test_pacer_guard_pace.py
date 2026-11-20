import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'hooks/pacer-guard.py'
FIXTURES = ROOT / 'tests/fixtures/valentin-mode'
LOADED = FIXTURES / 'command.jsonl'
PLAIN = FIXTURES / 'plain.jsonl'
PACE_MESSAGE = ('BLOCKED by pacer-guard: Claude is ahead of pace')


def run(payload=None, env=None):
    base = {'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', '/tmp')}
    if env:
        base.update(env)
    return subprocess.run([sys.executable, str(GUARD)], input=payload, text=True,
                          capture_output=True, env=base, cwd=str(ROOT))


def payload(command, transcript=LOADED):
    body = {'tool_name': 'Bash', 'tool_input': {'command': command}}
    if transcript is not None:
        body['transcript_path'] = str(transcript)
    return json.dumps(body)


class PacerGuardPace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pace_file = Path(self.temp.name) / 'pace.json'
        self.pace_file.write_text(json.dumps({'pace_ratio': 1.21, 'fetched_at': time.time()}))
        self.env = {'PACER_GUARD_PACE_FILE': str(self.pace_file)}

    def test_self_test_runs(self):
        result = run(env=self.env, payload=None)
        result = subprocess.run([sys.executable, str(GUARD), '--self-test'],
                                capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('pacer-guard self-test ok', result.stdout)

    def test_ahead_blocks_a_test_run(self):
        result = run(payload=payload('python3 -m unittest discover -s tests'), env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn(PACE_MESSAGE, result.stderr)

    def test_on_pace_allows_a_test_run(self):
        self.pace_file.write_text(json.dumps({'pace_ratio': 0.9, 'fetched_at': time.time()}))
        result = run(payload=payload('python3 -m unittest discover -s tests'), env=self.env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '')

    def test_reads_pass_when_ahead(self):
        for command in ('git status', 'git log -1', 'cat README.md', 'gh pr view 42'):
            with self.subTest(command=command):
                result = run(payload=payload(command), env=self.env)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_plan_pick_passes_when_ahead(self):
        for command in ('~/.local/bin/plan-pick --run',
                        'lease SOFT-12 run -- plan-pick --run'):
            with self.subTest(command=command):
                result = run(payload=payload(command), env=self.env)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_override_passes_when_ahead(self):
        env = dict(self.env)
        env['PACER_GUARD_PACE'] = 'off'
        result = run(payload=payload('python3 -m unittest discover -s tests'), env=env)
        self.assertEqual(result.returncode, 0)

    def test_unreadable_pace_passes(self):
        self.pace_file.write_text('not json')
        broken = Path(self.temp.name) / 'broken'
        broken.write_text('#!/bin/sh\nexit 1\n')
        broken.chmod(0o755)
        env = dict(self.env)
        env['PLAN_PICK_BIN'] = str(broken)
        env['TOKEN_LADDER_BIN'] = str(broken)
        result = run(payload=payload('npm test'), env=env)
        self.assertEqual(result.returncode, 0)

    def test_plain_chat_is_not_pace_gated(self):
        result = run(payload=payload('python3 -m unittest discover -s tests', transcript=PLAIN), env=self.env)
        self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()