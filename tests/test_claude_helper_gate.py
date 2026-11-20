import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/claude-helper-gate.py'


def stub(where, code, output):
    path = Path(where, f'plan-pick-exit-{code}')
    path.write_text(f"#!/bin/sh\necho '{output}'\nexit {code}\n")
    path.chmod(0o755)
    return str(path)


def run_hook(args=(), picker=None, chat=None, tool='Agent'):
    env = {'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', '/tmp')}
    for key in ('MULTIPROMPT_TAB', 'TMUX'):
        env.pop(key, None)
    if chat:
        env[chat] = 'tab-1'
    if picker:
        env['PLAN_PICK_BIN'] = picker
    return subprocess.run([sys.executable, str(HOOK), *args], input=json.dumps({'tool_name': tool, 'tool_input': {}}),
                          text=True, capture_output=True, env=env, cwd=str(ROOT))


class ClaudeHelperGate(unittest.TestCase):
    def test_its_self_test_passes(self):
        result = run_hook(['--self-test'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('claude-helper-gate self-test ok', result.stdout)

    def test_plan_pick_refusing_blocks_the_helper_in_a_chat(self):
        with tempfile.TemporaryDirectory() as where:
            picker = stub(where, 3, 'Claude helper: refused. Why: Claude is pace 1.40x is above 1.1x.')
            result = run_hook(picker=picker, chat='MULTIPROMPT_TAB')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(payload['permissionDecision'], 'deny')
        why = payload['permissionDecisionReason']
        self.assertIn('claude-helper-gate', why)
        self.assertIn('plan-pick --run', why)
        self.assertIn('Claude helper: refused', why)
        self.assertNotIn('codex exec', why)
        self.assertNotIn('pi -p', why)

    def test_plan_pick_allowing_lets_the_helper_start(self):
        with tempfile.TemporaryDirectory() as where:
            picker = stub(where, 0, 'Claude helper: allowed. Why: Claude is under its pace.')
            for tab in ('MULTIPROMPT_TAB', 'TMUX'):
                with self.subTest(tab=tab):
                    result = run_hook(picker=picker, chat=tab)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), {})

    def test_a_broken_picker_never_stops_work(self):
        with tempfile.TemporaryDirectory() as where:
            for picker in (stub(where, 1, 'plan-pick: cannot read pool state'),
                           stub(where, 4, 'plan-pick: unexpected exit'),
                           str(Path(where, 'missing-plan-pick'))):
                with self.subTest(picker=picker):
                    result = run_hook(picker=picker, chat='MULTIPROMPT_TAB')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), {})

    def test_no_chat_env_passes_even_when_plan_pick_refuses(self):
        with tempfile.TemporaryDirectory() as where:
            picker = stub(where, 3, 'Claude helper: refused. Why: Claude is ahead.')
            result = run_hook(picker=picker)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})


if __name__ == '__main__':
    unittest.main()
