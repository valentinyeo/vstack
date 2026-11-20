import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/plan-pick-only.py'
MESSAGE = ('BLOCKED by plan-pick-only: workers start only through plan-pick, so every chat shares one live usage '
           'pick. Put the brief in brief.txt and run ~/.local/bin/plan-pick --run (reviews add --not-vendor '
           '<author vendor>). If no lane is free, plan-pick says when one frees: wait for it, never ask Valentin '
           'to pay.')


def run(args=(), payload=None):
    return subprocess.run([sys.executable, str(HOOK), *args], input=payload, text=True,
                          capture_output=True, cwd=str(ROOT))


class PlanPickOnly(unittest.TestCase):
    def test_self_test_runs_on_a_real_past_mistake(self):
        result = run(['--self-test'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('plan-pick-only self-test ok', result.stdout)

    def test_a_direct_worker_launch_is_blocked(self):
        payload = json.dumps({'tool_name': 'Bash', 'tool_input': {
            'command': 'cd /tmp/x && nohup ~/.npm-global/bin/codex exec -C /tmp/x "$(cat b)" &'}})
        result = run(payload=payload)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr.strip(), MESSAGE)

    def test_a_plan_pick_launch_passes(self):
        for command in ['~/.local/bin/plan-pick --run', 'plan-pick --run --not-vendor openai',
                        'lease SOFT-12 run -- timeout 3600 ~/.local/bin/plan-pick --run']:
            with self.subTest(command=command):
                result = run(payload=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}}))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')

    def test_a_direct_launch_beside_plan_pick_is_blocked(self):
        payload = json.dumps({'tool_name': 'Bash', 'tool_input': {
            'command': '~/.local/bin/plan-pick --run && pi -p "$(cat b)"'}})
        self.assertEqual(run(payload=payload).returncode, 2)

    def test_other_tools_and_unreadable_input_pass(self):
        for payload in [json.dumps({'tool_name': 'Write', 'tool_input': {'command': 'codex exec -C /tmp/x b'}}),
                        'not json', json.dumps({'tool_name': 'Bash'})]:
            with self.subTest(payload=payload):
                self.assertEqual(run(payload=payload).returncode, 0)


if __name__ == '__main__':
    unittest.main()
