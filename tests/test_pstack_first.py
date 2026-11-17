"""Replay the two SOFT-2608 incidents through the actual hook entrypoints."""
import json
import os
import shlex
import shutil
from unittest import mock
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
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        cache = home / '.claude/plugins/cache/cursor-plugins/pstack/0.15.43'
        for name in ['shipping', 'autonomous-run']:
            path = cache / f'skills/poteto-mode/playbooks/{name}.md'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# ' + name)
        watcher = cache / 'skills/poteto-mode/scripts/watch-pr/watch-pr'
        watcher.parent.mkdir(parents=True)
        watcher.write_text('# Watch pull requests.')
        checkout = home / 'checkout'
        for name in ['hooks', 'scripts', 'tests/fixtures']:
            shutil.copytree(ROOT / name, checkout / name)
        self.index = checkout / 'pstack-index.md'
        self.index.write_text('committed index must remain unchanged')
        for patch in [mock.patch(__name__ + '.ROOT', checkout),
                      mock.patch(__name__ + '.FIXTURES', checkout / 'tests/fixtures/soft-2608'),
                      mock.patch.dict(os.environ, HOME=str(home))]:
            patch.start()
            self.addCleanup(patch.stop)

    def test_stop_hook_does_not_rewrite_tracked_index(self):
        before = self.index.read_bytes()
        self.assertEqual(reply("The command finished; I'll check the output."), {})
        self.assertEqual(self.index.read_bytes(), before)

    def test_tool_replacement_plans_require_disclosure(self):
        for text in ["We should replace the script with our own.",
                     "I'll rewrite the watcher.", "Let's refactor the tool."]:
            with self.subTest(text=text):
                self.assertEqual(reply(text).get('decision'), 'block')
                self.assertEqual(reply(text + '\npstack has: Shipping'), {})

    def test_scope_guard_covers_mandated_ticket_helper(self):
        for command in ['bin/poteto-ticket log SOFT-1 "Scope: add X"',
                        '/tmp/vstack/bin/poteto-ticket log SOFT-1 "New plan: X"']:
            with self.subTest(command=command):
                result = subprocess.run([sys.executable, str(ROOT / 'hooks/plan-activity.py')],
                    input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}}),
                    text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stderr)

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
