"""Who a chat's board login is: its tab's name, else SHIP_SESSION_NAME."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'session_login_under_test', ROOT / 'skills/hypertask-work/session_login.py')
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)


class LoginForSession(unittest.TestCase):
    """A temp HOME only: no real roster, chat-name file, token store or /proc."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def env(self, **values):
        return {'HOME': str(self.home), **values}

    def token(self, name):
        path = session.token_path(self.home, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('secret\n')
        return path

    def roster(self, tab, name):
        path = session.roster_path(self.home)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'rows': [{'tmux': tab, 'multibot': name}]}))

    def test_no_tab_uses_ship_session_name_token(self):
        path = self.token('HT Test Agent')
        login = session.login_for_session(self.env(SHIP_SESSION_NAME='HT Test Agent'))
        self.assertEqual(login, ('HT Test Agent', path))
        self.assertEqual(login[1].name, 'ht-test-agent-agent-token')

    def test_no_tab_and_a_persons_name_refuses(self):
        for name in ('Valentins Claude Code', 'Valentin Yeo', "Valentin's Chat"):
            with self.subTest(name=name):
                self.token(name)
                self.assertIsNone(session.login_for_session(self.env(SHIP_SESSION_NAME=name)))

    def test_a_tab_wins_over_ship_session_name(self):
        self.roster('live-test', 'Test Chat')
        tab_token = self.token('Test Chat')
        self.token('HT Other')
        login = session.login_for_session(
            self.env(MULTIPROMPT_TAB='live-test', SHIP_SESSION_NAME='HT Other'))
        self.assertEqual(login, ('Test Chat', tab_token))

    def test_a_tab_wins_even_when_ship_session_name_is_a_persons(self):
        self.roster('live-test', 'Test Chat')
        login = session.login_for_session(
            self.env(MULTIPROMPT_TAB='live-test', SHIP_SESSION_NAME='Valentins Claude Code'))
        self.assertEqual(login, ('Test Chat', session.token_path(self.home, 'Test Chat')))

    def test_no_tab_and_no_name_is_none(self):
        self.assertIsNone(session.login_for_session(self.env()))
        self.assertIsNone(session.login_for_session(self.env(MULTIPROMPT_TAB='', SHIP_SESSION_NAME='  ')))

    def test_a_name_with_no_token_is_none(self):
        self.assertIsNone(session.login_for_session(self.env(SHIP_SESSION_NAME='No Token Chat')))


if __name__ == '__main__':
    unittest.main()
