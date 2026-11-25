"""The shared login resolver the tools read (skills/hypertask-work/session_login.py)."""
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

    def test_a_tab_does_not_beat_ship_session_name(self):
        self.roster('live-test', 'HT Mobile Design')
        self.token('HT Mobile Design')
        ship_token = self.token('Mobile Designer')
        login = session.login_for_session(
            self.env(MULTIPROMPT_TAB='live-test', SHIP_SESSION_NAME='Mobile Designer'))
        self.assertEqual(login, ('Mobile Designer', ship_token))

    def test_a_tab_with_no_token_still_yields_to_ship_session_name(self):
        self.roster('live-test', 'HT Mobile Design')
        ship_token = self.token('Mobile Designer')
        login = session.login_for_session(
            self.env(MULTIPROMPT_TAB='live-test', SHIP_SESSION_NAME='Mobile Designer'))
        self.assertEqual(login, ('Mobile Designer', ship_token))

    def test_the_tab_names_the_login_when_ship_session_name_is_unset(self):
        self.roster('live-test', 'Test Chat')
        tab_token = self.token('Test Chat')
        login = session.login_for_session(self.env(MULTIPROMPT_TAB='live-test'))
        self.assertEqual(login, ('Test Chat', tab_token))

    def test_a_tab_still_names_the_login_when_ship_session_name_is_a_persons(self):
        self.roster('live-test', 'Test Chat')
        login = session.login_for_session(
            self.env(MULTIPROMPT_TAB='live-test', SHIP_SESSION_NAME='Valentins Claude Code'))
        self.assertEqual(login, ('Test Chat', session.token_path(self.home, 'Test Chat')))

    def test_a_token_file_wins_over_ship_session_name_and_the_tab(self):
        self.roster('live-test', 'Test Chat')
        self.token('Test Chat')
        self.token('Mobile Designer')
        explicit = self.home / 'given-agent-token'
        explicit.write_text('secret\n')
        found = session.login(self.env(MULTIPROMPT_TAB='live-test',
                                       SHIP_SESSION_NAME='Mobile Designer',
                                       HYPERTASK_AGENT_TOKEN_FILE=str(explicit)))
        self.assertEqual(found, ('Mobile Designer', explicit, 'HYPERTASK_AGENT_TOKEN_FILE'))
        self.assertEqual(session.login_for_session(
            self.env(HYPERTASK_AGENT_TOKEN_FILE=str(explicit))), ('given', explicit))

    def test_a_token_file_names_itself_from_its_own_file_name(self):
        explicit = self.token('Mobile Designer')
        found = session.login(self.env(HYPERTASK_AGENT_TOKEN_FILE=str(explicit)))
        self.assertEqual(found, ('mobile designer', explicit, 'HYPERTASK_AGENT_TOKEN_FILE'))

    def test_a_missing_token_file_is_still_the_answer(self):
        missing = self.home / 'gone-agent-token'
        found = session.login(self.env(HYPERTASK_AGENT_TOKEN_FILE=str(missing)))
        self.assertEqual(found, ('gone', missing, 'HYPERTASK_AGENT_TOKEN_FILE'))

    def test_a_persons_shortcut_name_never_names_a_token_file(self):
        explicit = self.token('Mobile Designer')
        found = session.login(self.env(HYPERTASK_AGENT_TOKEN_FILE=str(explicit),
                                       SHIP_SESSION_NAME='Valentin Yeo'))
        self.assertEqual(found, ('mobile designer', explicit, 'HYPERTASK_AGENT_TOKEN_FILE'))

    def test_the_source_names_where_the_login_came_from(self):
        path = self.token('HT Test Agent')
        self.assertEqual(session.login(self.env(SHIP_SESSION_NAME='HT Test Agent')),
                         ('HT Test Agent', path, 'SHIP_SESSION_NAME'))
        self.roster('live-test', 'Test Chat')
        self.assertEqual(session.login(self.env(MULTIPROMPT_TAB='live-test'))[2], 'MULTIPROMPT_TAB')
        self.assertIsNone(session.login(self.env()))

    def test_no_tab_and_no_name_is_none(self):
        self.assertIsNone(session.login_for_session(self.env()))
        self.assertIsNone(session.login_for_session(self.env(MULTIPROMPT_TAB='', SHIP_SESSION_NAME='  ')))

    def test_a_name_with_no_token_is_none(self):
        self.assertIsNone(session.login_for_session(self.env(SHIP_SESSION_NAME='No Token Chat')))

    def test_name_login_names_a_chat_with_no_token(self):
        self.assertEqual(session.name_login(self.env(SHIP_SESSION_NAME='No Token Chat')),
                         'No Token Chat')
        self.roster('live-test', 'Test Chat')
        self.assertEqual(session.name_login(self.env(MULTIPROMPT_TAB='live-test')), 'Test Chat')
        self.assertEqual(session.name_login(self.env()), '')

    def test_name_login_never_names_a_person(self):
        self.assertEqual(session.name_login(self.env(SHIP_SESSION_NAME='Valentin Yeo')), '')
        self.roster('live-test', 'Valentins Claude Code')
        self.assertEqual(session.name_login(self.env(MULTIPROMPT_TAB='live-test')), '')


class BorrowedLogin(unittest.TestCase):
    """VSTA-306: a chat never acts as a login the environment names for another chat."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        path = session.roster_path(self.home)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'rows': [{'tmux': 'live-htf', 'multibot': 'HT Features'}]}))

    def env(self, **values):
        return {'HOME': str(self.home), **values}

    def token(self, name):
        path = session.token_path(self.home, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('secret\n')
        return path

    def test_another_chats_ship_session_name_is_borrowed(self):
        self.assertEqual(session.borrowed(self.env(MULTIPROMPT_TAB='live-htf',
                                                  SHIP_SESSION_NAME='HT Product Lead')),
                         ('HT Product Lead', 'HT Features'))

    def test_another_chats_token_file_is_borrowed_by_its_own_name(self):
        path = self.token('HT Product Lead')
        self.assertEqual(session.borrowed(self.env(MULTIPROMPT_TAB='live-htf',
                                                  HYPERTASK_AGENT_TOKEN_FILE=str(path))),
                         ('ht product lead', 'HT Features'))

    def test_the_tabs_own_login_is_never_borrowed(self):
        for values in ({'SHIP_SESSION_NAME': 'HT Features'},
                       {'SHIP_SESSION_NAME': 'ht-features'},
                       {}):
            with self.subTest(values=values):
                self.assertIsNone(session.borrowed(self.env(MULTIPROMPT_TAB='live-htf', **values)))

    def test_no_tab_known_keeps_todays_order(self):
        self.assertIsNone(session.borrowed(self.env(SHIP_SESSION_NAME='HT Product Lead')))
        self.assertIsNone(session.borrowed(
            self.env(MULTIPROMPT_TAB='live-unknown', SHIP_SESSION_NAME='HT Product Lead')))

    def test_a_login_is_still_resolved_the_way_it_was(self):
        path = self.token('HT Product Lead')
        ship = self.env(MULTIPROMPT_TAB='live-htf', SHIP_SESSION_NAME='HT Product Lead')
        self.assertEqual(session.login_for_session(ship), ('HT Product Lead', path),
                         'the resolver still names the environment login; the lease refuses it')


if __name__ == '__main__':
    unittest.main()
