import importlib.machinery
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LINT = ROOT / 'skills/hypertask-work/board-lint'
FIXTURES = ROOT / 'tests/fixtures/board-lint'
BOARD = 99001


def roster_path(temp, text):
    path = Path(temp) / 'roster.txt'
    path.write_text(text or 'Board Drain Loop (live-a, claude, /tmp)\n')
    return path


def load_board_lint():
    loader = importlib.machinery.SourceFileLoader('board_lint_module', str(LINT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class BoardLintTests(unittest.TestCase):
    def run_lint(self, fixture, board=BOARD, extra_env=None, roster_text=None):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, BOARD_DRAIN_STATE_DIR=temp)
            if extra_env:
                env.update(extra_env)
            roster = roster_path(temp, roster_text)
            args = [str(LINT), '--board', str(board), '--fixture', str(FIXTURES / fixture),
                    '--roster', str(roster), '--skip-comments']
            return subprocess.run(args, capture_output=True, text=True, env=env)

    def assert_rule(self, output, rule, present=True):
        hit = any(f'| {rule} |' in line for line in output.splitlines())
        self.assertEqual(hit, present, output)

    def test_true_column_uses_merge_time_and_section_entry(self):
        data = json.loads((FIXTURES / 'clean.json').read_text())
        card = data['tasks'][0]
        key = card['ticketNumber']
        data['workers'] = {key: False}
        data['pulls'] = {key: [{'url': 'https://github.com/example/x/pull/1',
                               'state': 'MERGED', 'number': 1, 'passed': True,
                               'repository': {'nameWithOwner': 'example/x'}}]}
        for merged_at, should_move in (('2025-11-20T10:00:00Z', False),
                                       ('2025-11-21T11:00:00Z', True)):
            data['pulls'][key][0]['mergedAt'] = merged_at
            with self.subTest(merged_at=merged_at), tempfile.TemporaryDirectory() as temp:
                fixture = Path(temp) / 'merged.json'
                fixture.write_text(json.dumps(data))
                result = self.run_lint(fixture)
                self.assertNotEqual(result.returncode, 2, result.stderr)
                self.assert_rule(result.stdout, 'true-column', present=should_move)

    def test_clean_fixture_exits_zero(self):
        result = self.run_lint('clean.json')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('board-lint: clean', result.stdout)

    def test_stale_agent_from_board_sample(self):
        result = self.run_lint('stale-agent.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')

    def test_agent_assignee_accepts_closed_chat(self):
        result = self.run_lint('agent-closed-chat.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee', present=False)

    def test_agent_assignee_flags_name_no_chat_ever_had(self):
        result = self.run_lint('agent-unknown-chat.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assertIn('matches no Multibot chat ever', result.stdout)

    def test_agent_assignee_flags_revoked_agent(self):
        result = self.run_lint('agent-revoked.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assertIn('revoked', result.stdout)

    def test_agent_assignee_flags_person(self):
        result = self.run_lint('agent-person.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assertIn('is a person, not an agent', result.stdout)

    def test_agent_assignee_flags_doing_without_worker(self):
        result = self.run_lint('agent-doing-no-worker.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assertIn('Doing with no live worker', result.stdout)

    def test_agent_assignee_accepts_doing_with_worker(self):
        result = self.run_lint('agent-doing-with-worker.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee', present=False)

    def test_wrong_view_label_assignee(self):
        roster = ('Multi Bot Features (live-d, claude, /tmp)\n'
                  'Board Drain Loop (live-a, claude, /tmp)\n')
        result = self.run_lint('wrong-view.json', roster_text=roster)
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'label-assignee')

    def test_app_label_does_not_trigger_label_assignee(self):
        roster = 'Multi Bot Android Verifiy (live-v, claude, /tmp)\n'
        result = self.run_lint('app-label-ok.json', roster_text=roster)
        self.assert_rule(result.stdout, 'label-assignee', present=False)

    def test_waiting_ticket_skips_stale_agent(self):
        result = self.run_lint('waiting-skip-agent.json')
        self.assert_rule(result.stdout, 'agent-assignee', present=False)

    def test_unlinked_open_pr(self):
        result = self.run_lint('unlinked-pr.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'unlinked-work')

    def test_no_owner_label_todo(self):
        result = self.run_lint('no-label-todo.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'no-owner-label')

    def test_unnamed_identity(self):
        result = self.run_lint('unnamed-identity.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'unnamed-identity')

    def test_true_column_flags_plan(self):
        result = self.run_lint('wrong-column.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'true-column', present=True)
        self.assertNotIn('FACT-20 | true-column', result.stdout)

    def test_done_without_proof(self):
        result = self.run_lint('done-no-proof.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'done-proof')

    def test_done_with_merged_pr_needs_live_proof(self):
        fixture = json.loads((FIXTURES / 'done-with-proof.json').read_text())
        fixture.pop('comments', None)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'done-merged-only.json'
            path.write_text(json.dumps(fixture))
            roster = roster_path(temp, 'Board Drain Loop (live-a, claude, /tmp)\n')
            result = subprocess.run(
                [str(LINT), '--board', str(BOARD), '--fixture', str(path),
                 '--roster', str(roster), '--skip-comments'],
                capture_output=True, text=True,
                env=dict(os.environ, BOARD_DRAIN_STATE_DIR=temp))
            self.assertEqual(result.returncode, 1)
            self.assert_rule(result.stdout, 'done-proof')

    def test_done_with_merged_pr_and_comment_clean(self):
        result = self.run_lint('done-with-proof.json')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assert_rule(result.stdout, 'done-proof', present=False)

    def test_duplicate_title_suggestion(self):
        result = self.run_lint('duplicate-title.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'duplicate-title')

    def test_stale_idle_uses_section_changed_at(self):
        result = self.run_lint('stale-todo.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'stale-idle')
        self.assertIn('section change', result.stdout)

    def test_stale_idle_skips_waiting_on_valentin(self):
        result = self.run_lint('waiting-stale.json')
        self.assert_rule(result.stdout, 'stale-idle', present=False)

    def test_caller_login_wins_over_reconciler(self):
        module = load_board_lint()
        with tempfile.TemporaryDirectory() as temp:
            sessions = Path(temp) / '.config/hypertask-agents/credentials/sessions'
            sessions.mkdir(parents=True)
            (sessions / 'my-chat-agent-token').write_text('CHAT-TOKEN')
            (sessions / 'hypertask-reconciler-agent-token').write_text('RECONCILER-TOKEN')
            with mock.patch.dict(os.environ, {'HOME': temp, 'SHIP_SESSION_NAME': 'My Chat'}):
                os.environ.pop('HT_TOKEN', None)
                os.environ.pop('MULTIPROMPT_TAB', None)
                module.ensure_token()
                self.assertEqual(os.environ.get('HT_TOKEN'), 'CHAT-TOKEN')

    def test_reconciler_login_only_when_caller_has_none(self):
        module = load_board_lint()
        with tempfile.TemporaryDirectory() as temp:
            sessions = Path(temp) / '.config/hypertask-agents/credentials/sessions'
            sessions.mkdir(parents=True)
            (sessions / 'hypertask-reconciler-agent-token').write_text('RECONCILER-TOKEN')
            with mock.patch.dict(os.environ, {'HOME': temp}):
                os.environ.pop('HT_TOKEN', None)
                os.environ.pop('SHIP_SESSION_NAME', None)
                os.environ.pop('MULTIPROMPT_TAB', None)
                module.ensure_token()
                self.assertEqual(os.environ.get('HT_TOKEN'), 'RECONCILER-TOKEN')

    def test_expired_loop_not_armed_for_sync(self):
        with tempfile.TemporaryDirectory() as temp:
            state = {'name': 'Board Drain Loop', 'board': BOARD, 'label': 'Board Drain Loop',
                     'armed_at': '2020-01-01T00:00:00Z', 'expires_at': '2020-01-02T00:00:00Z',
                     'owner_pid': os.getpid(), 'host': socket.gethostname(),
                     'last_sync': {'at': '2020-01-01T00:00:00Z', 'ok': True, 'reason': ''}}
            states = Path(temp)
            (states / 'board-drain-loop.json').write_text(json.dumps(state))
            roster = roster_path(temp, 'Board Drain Loop (live-a, claude, /tmp)\n')
            env = dict(os.environ, BOARD_DRAIN_STATE_DIR=temp)
            result = subprocess.run(
                [str(LINT), '--board', str(BOARD), '--fixture', str(FIXTURES / 'clean.json'),
                 '--roster', str(roster), '--skip-comments'],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assert_rule(result.stdout, 'sync-record', present=False)

    def test_sync_stale_record(self):
        with tempfile.TemporaryDirectory() as temp:
            state = {'name': 'Board Drain Loop', 'board': BOARD, 'label': 'Board Drain Loop',
                     'armed_at': '2026-01-01T00:00:00Z', 'expires_at': '2099-01-01T00:00:00Z',
                     'owner_pid': os.getpid(), 'host': socket.gethostname(),
                     'last_sync': {'at': '2020-01-01T00:00:00Z', 'ok': True, 'reason': ''}}
            states = Path(temp)
            (states / 'board-drain-loop.json').write_text(json.dumps(state))
            roster = roster_path(temp, 'Board Drain Loop (live-a, claude, /tmp)\n')
            env = dict(os.environ, BOARD_DRAIN_STATE_DIR=temp)
            result = subprocess.run(
                [str(LINT), '--board', str(BOARD), '--fixture', str(FIXTURES / 'sync-stale.json'),
                 '--roster', str(roster), '--skip-comments'],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assert_rule(result.stdout, 'sync-record')

    VIEW_ROSTER = ('Multi Bot Features (live-f, claude, /tmp)\n'
                   'Board Drain Loop (live-a, claude, /tmp)\n')

    def run_view_lint(self, fixture):
        return self.run_lint(fixture, roster_text=self.VIEW_ROSTER)

    def test_view_filter_flags_missing_view(self):
        result = self.run_view_lint('view-missing.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-filter')
        self.assertIn('hypertask view create', result.stdout)

    def test_view_filter_flags_view_without_label_filter(self):
        result = self.run_view_lint('view-no-filter.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-filter')
        self.assertIn('no label filter', result.stdout)
        self.assertIn('hypertask view update v-empty --label "Multi Bot Features"', result.stdout)

    def test_view_filter_flags_filter_on_another_label(self):
        result = self.run_view_lint('view-other-label.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-filter')
        self.assertIn('another label', result.stdout)

    def test_view_filter_and_owner_clean(self):
        result = self.run_view_lint('view-ok.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'view-filter', present=False)
        self.assert_rule(result.stdout, 'view-owner', present=False)

    def test_view_owner_flags_person_owned_view(self):
        result = self.run_view_lint('view-owner-person.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-owner')
        self.assertIn('not the chat agent', result.stdout)
        self.assert_rule(result.stdout, 'view-filter', present=False)

    def test_human_board_write_on_board_15(self):
        fixture = {
            'now': 1763800800,
            'tasks': [{
                'ticketNumber': 'HTPR-9',
                'projectId': 15,
                'section': 'Backlog',
                'title': 'Sample product card',
                'updatedAt': '2025-11-22T00:00:00.000Z',
                'labels': [{'name': 'brain-medium'}],
            }],
            'comments': {
                'HTPR-9': [{
                    'kind': 'qa',
                    'text': 'Valentin typed this',
                    'creator': {'displayName': 'Valentin Yeo'},
                }]
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'board.json'
            path.write_text(json.dumps(fixture))
            roster = roster_path(temp, 'HT Product Lead (live-h, claude, /tmp)\n')
            result = subprocess.run(
                [str(LINT), '--board', '15', '--fixture', str(path), '--roster', str(roster),
                 '--skip-comments'],
                capture_output=True, text=True,
                env=dict(os.environ, BOARD_DRAIN_STATE_DIR=temp))
            self.assertEqual(result.returncode, 1)
            self.assert_rule(result.stdout, 'human-board-write')


if __name__ == '__main__':
    unittest.main()