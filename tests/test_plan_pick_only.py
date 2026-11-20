import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/plan-pick-only.py'
FIXTURES = ROOT / 'tests/fixtures/valentin-mode'
LOADED = FIXTURES / 'command.jsonl'
PLAIN = FIXTURES / 'plain.jsonl'
MESSAGE = ('BLOCKED by plan-pick-only: workers start only through plan-pick, so every chat shares one live usage '
           'pick. Put the brief in brief.txt and run ~/.local/bin/plan-pick --run (reviews add --not-vendor '
           '<author vendor>). If no lane is free, plan-pick says when one frees: wait for it, never ask Valentin '
           'to pay.')


def run(args=(), payload=None):
    return subprocess.run([sys.executable, str(HOOK), *args], input=payload, text=True,
                          capture_output=True, cwd=str(ROOT))


def payload(tool, command=None, transcript=LOADED):
    body = {'tool_name': tool, 'tool_input': {'command': command}}
    if transcript is not None:
        body['transcript_path'] = str(transcript)
    return json.dumps(body)


class PlanPickOnly(unittest.TestCase):
    def test_self_test_runs_on_a_real_past_mistake(self):
        result = run(['--self-test'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('plan-pick-only self-test ok', result.stdout)

    def test_a_direct_worker_launch_is_blocked(self):
        result = run(payload=payload('Bash',
                                     'cd /tmp/x && nohup ~/.npm-global/bin/codex exec -C /tmp/x "$(cat b)" &'))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr.strip(), MESSAGE)

    def test_a_plan_pick_launch_passes(self):
        for command in ['~/.local/bin/plan-pick --run', 'plan-pick --run --not-vendor openai',
                        'lease SOFT-12 run -- timeout 3600 ~/.local/bin/plan-pick --run']:
            with self.subTest(command=command):
                result = run(payload=payload('Bash', command))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')

    def test_a_direct_launch_beside_plan_pick_is_blocked(self):
        self.assertEqual(run(payload=payload('Bash', '~/.local/bin/plan-pick --run && pi -p "$(cat b)"')).returncode,
                         2)

    def test_a_probe_passes_but_a_probe_with_a_brief_is_blocked(self):
        for command, expected in [('codex exec --help', 0), ('codex exec -h 2>&1', 0),
                                  ('codex exec --help "$(cat b)"', 2)]:
            with self.subTest(command=command):
                result = run(payload=payload('Bash', command))
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_other_tools_and_unreadable_input_pass(self):
        for body in [payload('Write', 'codex exec -C /tmp/x b'), 'not json', json.dumps({'tool_name': 'Bash'}),
                     payload('Bash', None, transcript=None), json.dumps('[1, 2]'),
                     json.dumps({'tool_name': 'Bash', 'tool_input': 'x',
                                 'transcript_path': str(LOADED)}),
                     json.dumps({'tool_name': 'Bash', 'tool_input': None,
                                 'transcript_path': str(LOADED)}),
                     payload('Bash', 42), payload('Bash', ['pi', '-p'])]:
            with self.subTest(payload=body):
                self.assertEqual(run(payload=body).returncode, 0)

    def test_a_chat_that_never_loaded_valentin_mode_is_not_gated(self):
        direct = ('cd /tmp/x && nohup ~/.npm-global/bin/codex exec -C /tmp/x "$(cat b)" &')
        for transcript in (PLAIN, FIXTURES / 'missing.jsonl', None):
            with self.subTest(transcript=transcript):
                result = run(payload=payload('Bash', direct, transcript=transcript))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')

    def test_a_skill_call_or_skill_body_loads_the_gate(self):
        direct = 'nohup codex exec -C /tmp/x "$(cat b)" &'
        for fixture in ('skill-call.jsonl', 'base-dir.jsonl'):
            with self.subTest(fixture=fixture):
                result = run(payload=payload('Bash', direct, transcript=FIXTURES / fixture))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stderr.strip(), MESSAGE)

    def test_a_plain_chat_mentioning_the_skill_is_not_gated(self):
        result = run(payload=payload('Bash', 'codex exec -C /tmp/x "$(cat b)"', transcript=PLAIN))
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
