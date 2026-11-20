"""The hand-moves count, proved on recorded board payloads.

Every fixture under fixtures/hand-moves/ is a real Hypertask response with the
people's names, emails, photo links and ids replaced.
"""
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/hand-moves'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


hm = load('hand_moves', ROOT / 'bin/hand-moves')

NOW = '2026-11-20T12:00:00Z'
ARGS = ['--board', '15', '--days', '1', '--now', NOW]


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class Board:
    """A board that answers from recorded pages, and remembers what was asked."""

    def __init__(self, task_pages=(), comment_pages=None):
        self.task_pages = list(task_pages)
        self.comment_pages = dict(comment_pages or {})
        self.asked = []
        self.task_page = 0
        self.comment_page = {}

    def __call__(self, args):
        self.asked.append(list(args))
        if args[:2] == ['task', 'list']:
            page = self.task_pages[self.task_page]
            self.task_page += 1
            return page
        if args[:2] == ['comment', 'list']:
            ticket = args[2]
            index = self.comment_page.get(ticket, 0)
            pages = self.comment_pages[ticket]
            self.comment_page[ticket] = index + 1
            return pages[index]
        raise AssertionError(f'unexpected command: {args}')

    def cursors(self):
        return [args[args.index('--cursor') + 1] for args in self.asked if '--cursor' in args]


def run(client, args=ARGS):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = hm.main(args, client=hm.Client(runner=client, sleep=lambda _: None))
    return code, out.getvalue(), err.getvalue()


def one_ticket(ticket, pages):
    return Board([{'success': True, 'tasks': [{'ticketNumber': ticket}], 'nextCursor': None}],
                 {ticket: pages})


class CountTest(unittest.TestCase):
    def test_reconcile_move_is_counted_as_reconcile(self):
        code, out, _ = run(one_ticket('HTPR-9501', [fixture('reconcile-move.json')]))
        self.assertEqual(code, 0)
        self.assertIn('board=15 day=2026-11-20 moves=1 reconcile=1 hand=0', out)
        self.assertNotIn('HTPR-9501', out)  # only hand moves are listed under the total

    def test_agent_move_by_hand_is_listed_with_the_agent_name(self):
        code, out, _ = run(one_ticket('HTPR-9502', [fixture('hand-move-agent.json')]))
        self.assertEqual(code, 0)
        self.assertIn('board=15 day=2026-11-20 moves=1 reconcile=0 hand=1', out)
        self.assertIn('  HTPR-9502 10:31 In Progress -> Verification Backlog by HT Product Lead', out)

    def test_person_move_is_listed_as_person(self):
        code, out, _ = run(one_ticket('HTPR-9503', [fixture('hand-move-person.json')]))
        self.assertEqual(code, 0)
        self.assertIn('  HTPR-9503 12:05 AI Review -> QA by person', out)

    def test_reconcile_line_five_minutes_later_is_not_this_move(self):
        code, out, _ = run(one_ticket('HTPR-9504', [fixture('reconcile-log-late.json')]))
        self.assertEqual(code, 0)
        self.assertIn('moves=1 reconcile=0 hand=1', out)
        self.assertIn('  HTPR-9504 09:00 In Progress -> AI Review by Hypertask Reconciler', out)

    def test_both_lists_are_read_across_pages(self):
        board = Board([fixture('tasks-page-1.json'), fixture('tasks-page-2.json')], {
            'HTPR-9501': [fixture('reconcile-move.json')],
            'HTPR-9502': [fixture('hand-move-agent.json')],
            'HTPR-9503': [fixture('hand-move-person.json')],
        })
        code, out, _ = run(board)
        self.assertEqual(code, 0)
        self.assertIn('c1', board.cursors())
        self.assertIn('board=15 day=2026-11-20 moves=3 reconcile=1 hand=2', out)
        self.assertIn('HTPR-9502 10:31', out)
        self.assertIn('HTPR-9503 12:05', out)

    def test_a_move_on_a_later_comment_page_still_matches_its_log(self):
        board = Board([{'success': True, 'tasks': [{'ticketNumber': 'HTPR-9505'}], 'nextCursor': None}],
                      {'HTPR-9505': [fixture('comments-page-1.json'), fixture('comments-page-2.json')]})
        code, out, _ = run(board)
        self.assertEqual(code, 0)
        self.assertIn('423906', board.cursors())
        self.assertIn('moves=1 reconcile=1 hand=0', out)

    def test_json_carries_the_row_fields_the_report_needs(self):
        code, out, _ = run(one_ticket('HTPR-9502', [fixture('hand-move-agent.json')]),
                           ARGS + ['--json'])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(list(data), ['success', 'since', 'now', 'rows', 'days'])
        self.assertEqual(list(data['rows'][0]),
                         ['board', 'day', 'ticket', 'at', 'from_column', 'to_column', 'mover', 'by_reconcile'])
        self.assertEqual(data['rows'][0]['mover'], 'HT Product Lead')
        self.assertFalse(data['rows'][0]['by_reconcile'])
        self.assertEqual(data['days'], [{'board': 15, 'day': '2026-11-19', 'moves': 0, 'reconcile': 0, 'hand': 0},
                                        {'board': 15, 'day': '2026-11-20', 'moves': 1, 'reconcile': 0, 'hand': 1}])

    def test_both_boards_are_asked_and_counted_separately(self):
        board = Board([{'success': True, 'tasks': [{'ticketNumber': 'HTPR-9502'}], 'nextCursor': None},
                       {'success': True, 'tasks': [{'ticketNumber': 'HTPR-9502'}], 'nextCursor': None}],
                      {'HTPR-9502': [fixture('hand-move-agent.json'), fixture('hand-move-agent.json')]})
        code, out, _ = run(board, ['--board', '2060', '--board', '15', '--days', '1', '--now', NOW])
        self.assertEqual(code, 0)
        self.assertEqual([args[args.index('--project') + 1] for args in board.asked
                          if args[:2] == ['task', 'list']], ['15', '2060'])
        self.assertIn('board=15 day=2026-11-20 moves=1 reconcile=0 hand=1', out)
        self.assertIn('board=2060 day=2026-11-20 moves=1 reconcile=0 hand=1', out)


class FailureTest(unittest.TestCase):
    def test_a_board_it_cannot_read_exits_2_with_one_line(self):
        board = Board([{'success': False, 'error': 'Task not found or access denied'}])
        code, out, err = run(board)
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertEqual(len(err.strip().splitlines()), 2)  # the token note, then the one fault line
        self.assertIn('hand-moves: cannot read:', err)
        self.assertIn('Task not found or access denied', err)

    def test_rows_missing_from_a_page_stop_the_run(self):
        board = Board([{'success': True, 'nextCursor': None}])
        code, _, err = run(board)
        self.assertEqual(code, 2)
        self.assertIn('hand-moves: cannot read:', err)

    def test_a_cursor_that_repeats_stops_the_run(self):
        page = {'success': True, 'tasks': [{'ticketNumber': 'HTPR-9502'}], 'nextCursor': 'same'}
        board = Board([page, page])
        code, _, err = run(board)
        self.assertEqual(code, 2)
        self.assertIn('pagination cursor repeats', err)

    def test_a_rate_limit_backs_off_and_the_next_attempt_is_read(self):
        answer = fixture('hand-move-agent.json')
        calls = []

        class Done:
            def __init__(self, code, stdout, stderr=''):
                self.returncode, self.stdout, self.stderr = code, stdout, stderr

        def fake_run(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                return Done(1, '', 'Error: Rate limit exceeded. Try again in 30s.')
            return Done(0, json.dumps(answer))

        slept = []
        client = hm.Client(sleep=slept.append)
        with patch.object(hm.subprocess, 'run', fake_run):
            data = client.command(['comment', 'list', 'HTPR-9502', '--include-activity'])
        self.assertEqual(data['success'], True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(slept, [hm.BACKOFF_SECONDS[0]])

    def test_the_token_is_passed_in_the_environment_and_never_on_the_command_line(self):
        seen = {}

        class Done:
            returncode, stdout, stderr = 0, '{"success": true}', ''

        def fake_run(command, **kwargs):
            seen['command'] = command
            seen['env'] = kwargs.get('env') or {}
            return Done()

        with patch.dict(os.environ, {'HT_TOKEN': 'secret-token'}), \
                patch.object(hm.subprocess, 'run', fake_run):
            hm.Client().command(['task', 'list', '--project', '15'])
        self.assertNotIn('secret-token', ' '.join(seen['command']))
        self.assertEqual(seen['env']['HT_TOKEN'], 'secret-token')

    def test_a_board_flag_is_required(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            hm.main([], client=hm.Client(runner=Board()))
        self.assertEqual(raised.exception.code, 2)


class MoverTest(unittest.TestCase):
    def test_agent_object_names_the_mover_when_the_payload_has_no_from_agent(self):
        entry = {'agent': {'displayName': 'Vstack Maintainer'},
                 'activity': {'type': 'TaskMove', 'data': {}}}
        self.assertEqual(hm.mover(entry), 'Vstack Maintainer')

    def test_no_agent_anywhere_means_a_person(self):
        entry = {'agent': None, 'agent_display_name': None,
                 'activity': {'type': 'TaskMove', 'data': {'fromUserDisplayName': 'Board Owner'}}}
        self.assertEqual(hm.mover(entry), 'person')

    def test_a_non_move_activity_is_not_a_move(self):
        page = {'success': True, 'nextCursor': None, 'agent_activity': [], 'comments': [
            {'id': 1, 'createdAt': '2026-11-20T11:00:00.000Z', 'type': 'activity',
             'activity': {'type': 'TaskPullRequest', 'data': {'action': 'linked'}}}]}
        code, out, _ = run(one_ticket('HTPR-9506', [page]))
        self.assertEqual(code, 0)
        self.assertIn('board=15 day=2026-11-20 moves=0 reconcile=0 hand=0', out)


if __name__ == '__main__':
    unittest.main()
