"""Finish before starting (VSTA-206): a board over cap starts no new Todo work.

Valentin's order, 2026-11-24. While a board holds more than 10 cards in Checks plus
AI Review, `lease ... run` refuses a non-urgent Todo start with exit 75, and
drain-check fails `over cap` instead of asking the chat to start more Todo work.
"""
import contextlib
from datetime import datetime, timezone
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/board-drain'
NOW = 1800000000
LABEL = 'Board Drain Loop'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


wip = load('board_drain_wip_cap_test', SKILL / 'wip-cap')
drain = load('board_drain_check_cap', SKILL / 'drain-check')
lease = load('fleet_lease_cap', ROOT / 'skills/hypertask-work/lease')


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def busy(cards, column='Checks'):
    """Another chat's cards in a busy column: they count, and they carry no label."""
    return [{'ticketNumber': f'VSTA-{900 + index}', 'projectId': 13556, 'section': column,
             'labels': [], 'updatedAt': iso(NOW - 600)} for index in range(cards)]


def busy_rows(cards, column='Checks'):
    """Those cards as drain-check fixture rows."""
    return [{'task': task, 'comments': []} for task in busy(cards, column)]


def card(key, section='Todo', priority=None, age=3 * 3600):
    task = {'ticketNumber': key, 'projectId': 13556, 'section': section, 'status': 'Normal',
            'labels': [{'name': LABEL}], 'waitingOnUserId': None, 'blockerCommentId': None,
            'updatedAt': iso(NOW - age)}
    if priority is not None:
        task['priority'] = priority
    return {'task': task, 'comments': []}


URGENT = {'id': 'p1', 'priority_index': 1, 'Priority_Value': 'Urgent'}
MEDIUM = {'id': 'p3', 'priority_index': 3, 'Priority_Value': 'Medium'}


class CapRuleTest(unittest.TestCase):
    """The one function both call sites read."""

    def test_count_counts_only_the_two_busy_columns(self):
        rows = (busy(3) + busy(2, 'AI Review')
                + [card('VSTA-1')['task'], card('VSTA-2', 'Doing')['task']])
        self.assertEqual(wip.count(rows), 5)

    def test_at_cap_is_not_over_and_one_more_is(self):
        self.assertEqual(wip.over_cap(busy(10), 13556), (False, 10, 10))
        self.assertEqual(wip.over_cap(busy(11), 13556), (True, 11, 10))

    def test_a_board_with_no_row_of_its_own_takes_the_one_cap(self):
        self.assertEqual(wip.cap_for(13556), 10)
        self.assertEqual(wip.cap_for(999999), 10)

    def test_a_failed_board_read_fails_open_with_one_warning(self):
        said = io.StringIO()
        wip._warned.clear()

        def broken(_board_id):
            raise OSError('board unreadable')

        with contextlib.redirect_stderr(said):
            self.assertEqual(wip.board_over_cap(13556, broken), (False, 0, 10))
            self.assertEqual(wip.board_over_cap(13556, broken), (False, 0, 10))
        self.assertEqual(len(said.getvalue().splitlines()), 1, said.getvalue())
        self.assertIn('cap not enforced', said.getvalue())


class LeaseRefusalTest(unittest.TestCase):
    """The lease refuses the start, and only the start it should refuse."""

    def setUp(self):
        wip._warned.clear()

    def run_lease(self, task, cards, read_error=None):
        """Run one `lease run` against these card facts, with the child stubbed."""
        popping = patch.object(lease.subprocess, 'Popen')
        started = popping.start()
        self.addCleanup(popping.stop)
        started.return_value.poll.return_value = 0
        started.return_value.returncode = 0
        board = (patch.object(lease, 'board_tasks', side_effect=read_error) if read_error
                 else patch.object(lease, 'board_tasks', return_value=cards))
        said = io.StringIO()
        with patch.object(lease.reconcile, 'read_ticket', return_value=task), board, \
                patch.object(lease, 'write') as written, \
                patch.object(lease, 'sync_card'), \
                patch.object(sys, 'argv', ['lease', task['ticketNumber'], 'run', '--', 'true']), \
                contextlib.redirect_stderr(said):
            code = lease.main()
        return code, said.getvalue(), started, written

    def test_a_todo_start_on_a_full_board_is_refused(self):
        task = card('VSTA-206', priority=MEDIUM)['task']
        code, said, started, written = self.run_lease(task, busy(11))
        self.assertEqual(code, 75, said)
        self.assertIn('lease: VSTA-206 held: board 13556 has 11 cards in Checks+AI Review '
                      '(cap 10); finish those first', said)
        started.assert_not_called()
        written.assert_not_called()

    def test_an_urgent_todo_start_is_allowed(self):
        code, said, started, _written = self.run_lease(card('VSTA-206', priority=URGENT)['task'],
                                                      busy(11))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_a_doing_resume_is_allowed(self):
        code, said, started, _written = self.run_lease(card('VSTA-206', section='Doing')['task'],
                                                      busy(11))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_a_start_at_the_cap_is_allowed(self):
        code, said, started, _written = self.run_lease(card('VSTA-206')['task'], busy(10))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_a_board_read_that_fails_starts_the_worker_with_one_warning(self):
        code, said, started, _written = self.run_lease(card('VSTA-206')['task'], [],
                                                       read_error=OSError('board unreadable'))
        self.assertEqual(code, 0, said)
        self.assertEqual(said.count('cap not enforced'), 1, said)
        self.assertIn('wip-cap: board 13556 read failed (board unreadable); cap not enforced', said)
        started.assert_called_once()


class DrainCheckCapTest(unittest.TestCase):
    """drain-check says the board is full instead of asking for another start."""

    def setUp(self):
        wip._warned.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for patcher in (patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.directory)}),
                        patch.object(drain.loop_state, 'timer_enabled', return_value=True),
                        patch.object(drain, 'open_pull_rows', return_value=[])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_check(self, rows):
        fixture = self.directory / 'fixture.json'
        fixture.write_text(json.dumps(rows))
        out = io.StringIO()
        argv = ['--board', '13556', '--label', LABEL, '--fixture', str(fixture),
                '--now', iso(NOW)]
        with patch.object(drain, 'probe_load', return_value=(0, 'ADD worker, ADD chat')), \
                patch.object(drain, 'probe_lane', return_value=None), \
                patch.object(drain.reconcile, 'worker_alive', return_value=False), \
                contextlib.redirect_stdout(out):
            code = drain.main(argv)
        return code, out.getvalue()

    def test_over_cap_fails_and_stops_asking_for_a_start(self):
        code, out = self.run_check(busy_rows(11) + [card('VSTA-206')])
        self.assertEqual(code, 1, out)
        self.assertIn('over cap: 11 cards in Checks+AI Review (cap 10); finish before starting', out)
        self.assertNotIn('loop off', out)
        self.assertNotIn('stale:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_at_cap_still_reports_the_idle_loop(self):
        code, out = self.run_check(busy_rows(10) + [card('VSTA-206')])
        self.assertEqual(code, 1, out)
        self.assertNotIn('over cap', out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)
        self.assertIn('stale: VSTA-206 workable in Todo for 3h.', out)
        self.assertIn('drain-check: FAIL (2 findings)', out)

    def test_an_urgent_card_still_gets_its_nudge_over_cap(self):
        code, out = self.run_check(busy_rows(11) + [card('VSTA-206', priority=URGENT, age=1800)])
        self.assertEqual(code, 1, out)
        self.assertIn('over cap: 11 cards in Checks+AI Review (cap 10); finish before starting', out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)
        self.assertIn('drain-check: FAIL (2 findings)', out)


if __name__ == '__main__':
    unittest.main()
