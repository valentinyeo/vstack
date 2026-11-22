import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / 'hooks/agent-identity-guard.py'
WRITE = 'hypertask task create --project 2060 --title x'


# The command the live test chat ran on 22 Nov 20:46 and the guard blocked. It carries the chat's
# own login token under the name the hypertask skill documents, skills/hypertask/references/cli.md.
LIVE_WRITE = ('export PATH=$HOME/.local/bin:$PATH HYPERTASKS_JWT_TOKEN=$(cat $S/vvm-test-agent-agent-token) '
              'SHIP_SESSION_NAME="VVM Test Agent"; hypertask --json comment add SOFT-2849 --kind done --text x')


class AgentIdentityGuard(unittest.TestCase):
    def run_guard(self, command, name=None, ship_name=None, token=None):
        with tempfile.TemporaryDirectory() as home:
            env = {'PATH': os.environ['PATH'], 'HOME': home}
            if name:
                state = Path(home, '.local/state/multiprompt')
                state.mkdir(parents=True)
                (state / 'chat-names.json').write_text(json.dumps({'tab-1': {'name': name}}))
                env['MULTIPROMPT_TAB'] = 'tab-1'
            if ship_name:
                env['SHIP_SESSION_NAME'] = ship_name
            if token:
                logins = Path(home, '.config/hypertask-agents/credentials/sessions')
                logins.mkdir(parents=True)
                (logins / token).write_text('tok')
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

    def test_a_write_with_the_documented_token_env_var_passes(self):
        """cli.md tells a chat to pass HYPERTASKS_JWT_TOKEN, so that write carries its own login."""
        for command in ('HYPERTASKS_JWT_TOKEN="$T" ' + WRITE, LIVE_WRITE):
            for name in (None, 'Poteto'):
                with self.subTest(command=command, name=name):
                    self.assertEqual(self.run_guard(command, name), (0, ''))

    def test_a_headless_chat_is_named_by_its_ship_session_name(self):
        """A run with no tab takes its name from SHIP_SESSION_NAME, as the lease and the Stop hook do."""
        code, why = self.run_guard(WRITE, ship_name='VVM Test Agent', token='vvm-test-agent-agent-token')
        self.assertEqual(code, 2)
        self.assertIn('VVM Test Agent', why)
        self.assertIn('own board login', why)

    def test_a_chat_with_no_tab_and_no_ship_name_keeps_its_own_rules(self):
        code, why = self.run_guard(WRITE)
        self.assertEqual(code, 2)
        self.assertIn('no name', why)

    def test_reads_pass(self):
        self.assertEqual(self.run_guard('hypertask task list --project 2060'), (0, ''))


if __name__ == '__main__':
    unittest.main()
