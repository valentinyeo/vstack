import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'hooks/pacer-guard.py'
FIXTURES = ROOT / 'tests/fixtures/valentin-mode'
LOADED = FIXTURES / 'command.jsonl'
PLAIN = FIXTURES / 'plain.jsonl'
WORKER_MESSAGE = 'BLOCKED by pacer-guard: this chat talks to Valentin, so it hands work to workers'
CODE_MESSAGE = 'BLOCKED by pacer-guard: this chat talks to Valentin, so it never writes code'


def run(payload=None, env=None):
    base = {'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', '/tmp')}
    if env:
        base.update(env)
    return subprocess.run([sys.executable, str(GUARD)], input=payload, text=True,
                          capture_output=True, env=base, cwd=str(ROOT))


def payload(command, transcript=LOADED, agent_id=None, agent_type=None):
    body = {'tool_name': 'Bash', 'tool_input': {'command': command}}
    if transcript is not None:
        body['transcript_path'] = str(transcript)
    if agent_id is not None:
        body['agent_id'] = agent_id
    if agent_type is not None:
        body['agent_type'] = agent_type
    return json.dumps(body)


def tool_payload(tool_name, tool_input, transcript=LOADED, agent_id=None, agent_type=None):
    body = {'tool_name': tool_name, 'tool_input': tool_input}
    if transcript is not None:
        body['transcript_path'] = str(transcript)
    if agent_id is not None:
        body['agent_id'] = agent_id
    if agent_type is not None:
        body['agent_type'] = agent_type
    return json.dumps(body)


class PacerGuardPace(unittest.TestCase):
    def test_self_test_runs(self):
        result = subprocess.run([sys.executable, str(GUARD), '--self-test'],
                                capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('pacer-guard self-test ok', result.stdout)

    def test_valentin_mode_blocks_a_test_run(self):
        result = run(payload=payload('python3 -m unittest discover -s tests'))
        self.assertEqual(result.returncode, 2)
        self.assertIn(WORKER_MESSAGE, result.stderr)

    def test_sub_bash_clone(self):
        heavy = 'git clone https://github.com/x/y /tmp/y && gh pr checkout 13'
        result = run(payload=payload(heavy, agent_id='agent-def456', agent_type='general-purpose'))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_main_bash_clone(self):
        heavy = 'git clone https://github.com/x/y /tmp/y && gh pr checkout 13'
        result = run(payload=payload(heavy))
        self.assertEqual(result.returncode, 2)
        self.assertIn(WORKER_MESSAGE, result.stderr)

    def test_sub_write_code(self):
        body = tool_payload('Write', {'file_path': 'x.py', 'content': 'print(1)\n'},
                            agent_id='agent-def456', agent_type='general-purpose')
        result = run(payload=body, env={'MULTIPROMPT_TAB': 'tab-1'})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(CODE_MESSAGE, result.stderr)

    def test_sub_edit_code(self):
        body = tool_payload('Edit', {'file_path': 'hooks/x.py', 'old_string': 'a', 'new_string': 'b'},
                            agent_id='agent-def456', agent_type='general-purpose')
        result = run(payload=body, env={'MULTIPROMPT_TAB': 'tab-1'})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(CODE_MESSAGE, result.stderr)

    def test_main_write_code(self):
        body = tool_payload('Write', {'file_path': 'x.py', 'content': 'print(1)\n'})
        result = run(payload=body, env={'MULTIPROMPT_TAB': 'tab-1'})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(CODE_MESSAGE, result.stderr)

    def test_reads_pass_in_valentin_mode(self):
        for command in ('git status', 'git log -1', 'cat README.md', 'gh pr view 42'):
            with self.subTest(command=command):
                result = run(payload=payload(command))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_plan_pick_passes_in_valentin_mode(self):
        for command in ('~/.local/bin/plan-pick --run',
                        'lease SOFT-12 run -- plan-pick --run'):
            with self.subTest(command=command):
                result = run(payload=payload(command))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_override_passes_heavy_bash(self):
        result = run(payload=payload('python3 -m unittest discover -s tests'),
                     env={'PACER_GUARD_INLINE': 'off'})
        self.assertEqual(result.returncode, 0)

    def test_plain_chat_is_not_worker_gated(self):
        result = run(payload=payload('python3 -m unittest discover -s tests', transcript=PLAIN))
        self.assertEqual(result.returncode, 0)

    def test_valentin_mode_allows_text_that_mentions_loops_or_tests(self):
        cases = [
            'grep -n "while true" hooks/x.py',
            'cat > brief.txt <<EOF\nwhile true; do drain; done\nEOF',
            '~/.local/bin/plan-pick --run --brief "while true; do sync; done"',
            'git commit -m "handle while true loop"',
            'grep -r "npm test" .',
            "cat > brief.txt <<'EOF'\nrun pytest\nEOF",
            'lease X run -- ~/.local/bin/plan-pick --run',
        ]
        for command in cases:
            with self.subTest(command=command):
                result = run(payload=payload(command))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_valentin_mode_blocks_heavy_commands(self):
        blocked = (
            'pytest -q',
            'timeout 600 npm test',
            'bash -c "npm test"',
            'while true; do sleep 1; done',
        )
        for command in blocked:
            with self.subTest(command=command):
                result = run(payload=payload(command))
                self.assertEqual(result.returncode, 2, command)
                self.assertIn(WORKER_MESSAGE, result.stderr)


if __name__ == '__main__':
    unittest.main()