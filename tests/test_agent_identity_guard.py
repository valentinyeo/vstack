import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / 'hooks/agent-identity-guard.py'
WRITE = 'hypertask task create --project 2060 --title x'


class AgentIdentityGuard(unittest.TestCase):
    def run_guard(self, command, name=None):
        with tempfile.TemporaryDirectory() as home:
            env = {'PATH': os.environ['PATH'], 'HOME': home}
            if name:
                state = Path(home, '.local/state/multiprompt')
                state.mkdir(parents=True)
                (state / 'chat-names.json').write_text(json.dumps({'tab-1': {'name': name}}))
                env['MULTIPROMPT_TAB'] = 'tab-1'
            payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}})
            result = subprocess.run([sys.executable, str(GUARD)], input=payload, text=True,
                                    capture_output=True, env=env)
        return result.returncode, result.stderr

    def test_a_write_as_valentin_from_a_nameless_chat_is_refused(self):
        code, why = self.run_guard(WRITE)
        self.assertEqual(code, 2)
        self.assertIn('no name', why)

    def test_a_write_as_valentin_from_a_named_chat_is_refused(self):
        code, why = self.run_guard(WRITE, name='Poteto')
        self.assertEqual(code, 2)
        self.assertIn('/hypertask', why)

    def test_a_write_with_an_agent_login_passes(self):
        for command in ('HT_TOKEN="$T" ' + WRITE, 'hypertask --token "$T" task create --project 2060 --title x'):
            for name in (None, 'Poteto'):
                with self.subTest(command=command, name=name):
                    self.assertEqual(self.run_guard(command, name), (0, ''))

    def test_reads_pass(self):
        self.assertEqual(self.run_guard('hypertask task list --project 2060'), (0, ''))


if __name__ == '__main__':
    unittest.main()
