"""Replay the two SOFT-2608 incidents through the actual hook entrypoints."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/soft-2608'


def reply(text):
    with tempfile.NamedTemporaryFile('w') as f:
        f.write(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': text}]}}) + '\n')
        f.flush()
        r = subprocess.run([sys.executable, str(ROOT / 'hooks/pstack-reply.py')],
                           input=json.dumps({'transcript_path': f.name}), text=True, capture_output=True, check=True)
    return json.loads(r.stdout)


class Replay(unittest.TestCase):
    def test_short_status_with_command_is_exempt(self):
        for text in ["The command finished; I'll check the output.",
                     "I'll check the script output.",
                     "The tool finished. I will inspect the result."]:
            with self.subTest(text=text):
                self.assertEqual(reply(text), {})

    def test_real_merge_plan(self):
        result = reply((FIXTURES / 'merge-plan.txt').read_text())
        self.assertEqual(result.get('decision'), 'block', result)
        self.assertIn('shipping.md', result['reason'])
        self.assertIn('scripts/watch-pr', result['reason'])

    def test_shipping_citation(self):
        self.assertEqual(reply("I'll build a board sync tool.\npstack: Shipping\npstack has: Shipping"), {})

    def test_real_scope_add(self):
        text = (FIXTURES / 'scope-add.txt').read_text()
        import shlex
        r = subprocess.run([sys.executable, str(ROOT / 'hooks/plan-activity.py')],
                           input=json.dumps({'tool_name': 'Bash', 'tool_input': {
                               'command': 'hypertask activity add SOFT-2446 --text ' + shlex.quote(text)}}),
                           text=True, capture_output=True)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn('update the ticket description instead', r.stderr)


if __name__ == '__main__':
    unittest.main()
