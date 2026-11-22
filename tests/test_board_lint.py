import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINT = ROOT / 'skills/hypertask-work/board-lint'
FIXTURES = ROOT / 'tests/fixtures/board-lint'
BOARD = 99001


def roster_path(temp, text):
    path = Path(temp) / 'roster.txt'
    path.write_text(text or 'Board Drain Loop (live-a, claude, /tmp)\n')
    return path


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

    def test_clean_fixture_exits_zero(self):
        result = self.run_lint('clean.json')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('board-lint: clean', result.stdout)

    def test_stale_agent_from_board_sample(self):
        result = self.run_lint('stale-agent.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')

    def test_wrong_view_label_assignee(self):
        result = self.run_lint('wrong-view.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'label-assignee')

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

    def test_done_with_merged_pr_clean(self):
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