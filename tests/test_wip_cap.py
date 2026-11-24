"""Finish before starting (VSTA-206): an agent at 5 open tickets starts no new work.

Valentin's rule, 2026-11-24. Each agent owns at most 5 open tickets at a time, one
worker each, and starts a new ticket only after one ships. So while the agent's label
carries 5 cards in Doing, Checks or AI Review, `lease ... run` refuses a non-urgent
Todo start with exit 75, and drain-check fails `over cap` instead of asking the chat
to start more.
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
OTHER = 'Responsive Mode'


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


def open_card(index, column='Checks', label=LABEL):
    """A card this label already owns, with a worker on it."""
    return {'ticketNumber': f'VSTA-{900 + index}', 'projectId': 13556, 'section': column,
            'labels': [{'name': label}],
            'assignees': [{'type': 'agent', 'displayName': f'{label} Agent'}],
            'updatedAt': iso(NOW - 600)}


def open_cards(cards, column='Checks', label=LABEL):
    return [open_card(index, column, label) for index in range(cards)]


def open_rows(cards, column='Checks', label=LABEL):
    """Those cards as drain-check fixture rows."""
    return [{'task': task, 'comments': []} for task in open_cards(cards, column, label)]


def card(key, section='Todo', priority=None, age=3 * 3600):
    task = {'ticketNumber': key, 'projectId': 13556, 'section': section, 'status': 'Normal',
            'labels': [{'name': LABEL}], 'waitingOnUserId': None, 'blockerCommentId': None,
            'updatedAt': iso(NOW - age)}
    if priority is not None:
        task['priority'] = priority
    return {'task': task, 'comments': []}


URGENT = {'id': 'p1', 'priority_index': 1, 'Priority_Value': 'Urgent'}
MEDIUM = {'id': 'p3', 'priority_index': 3, 'Priority_Value': 'Medium'}
HELD = ('label Board Drain Loop has 5 open tickets in Doing+Checks+AI Review (cap 5); '
        'ship one first')


class CapRuleTest(unittest.TestCase):
    """The one function both call sites read."""

    def test_count_counts_the_working_columns_of_one_label(self):
        rows = (open_cards(2) + open_cards(2, 'AI Review') + open_cards(1, 'Doing')
                + open_cards(3, label=OTHER)
                + [card('VSTA-1')['task'], card('VSTA-2', 'Done')['task']])
        self.assertEqual(wip.count(rows, LABEL), 5)

    def test_four_open_is_not_full_and_five_is(self):
        self.assertEqual(wip.at_cap(open_cards(4), LABEL), (False, 4, 5))
        self.assertEqual(wip.at_cap(open_cards(5), LABEL), (True, 5, 5))

    def test_a_label_with_no_row_of_its_own_takes_the_one_cap(self):
        self.assertEqual(wip.cap_for(LABEL), 5)
        self.assertEqual(wip.cap_for('a chat nobody configured'), 5)

    def test_a_generic_label_is_never_counted(self):
        self.assertEqual(wip.agent_labels({'labels': [{'name': 'Bug'}, {'name': 'brain-light'},
                                                       {'name': LABEL}]}), [LABEL])

    def test_a_failed_board_read_fails_open_with_one_warning(self):
        said = io.StringIO()
        wip._warned.clear()

        def broken(_board_id):
            raise OSError('board unreadable')

        with contextlib.redirect_stderr(said):
            self.assertIsNone(wip.read_held(13556, [LABEL], broken))
            self.assertIsNone(wip.read_held(13556, [LABEL], broken))
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
        # This class tests the cap; the checkout here is the shared one, and
        # tests/test_hypertask_work.py proves the shared-checkout refusal (VSTA-259).
        checkout = patch.object(lease, 'shared_refusal', return_value=None)
        checkout.start()
        self.addCleanup(checkout.stop)
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

    def test_a_todo_start_on_a_label_at_cap_is_refused(self):
        task = card('VSTA-206', priority=MEDIUM)['task']
        code, said, started, written = self.run_lease(task, open_cards(5))
        self.assertEqual(code, 75, said)
        self.assertIn(f'lease: VSTA-206 held: {HELD}', said)
        started.assert_not_called()
        written.assert_not_called()

    def test_a_todo_start_at_four_open_is_allowed(self):
        code, said, started, _written = self.run_lease(card('VSTA-206')['task'], open_cards(4))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_another_labels_cards_do_not_count(self):
        code, said, started, _written = self.run_lease(card('VSTA-206')['task'],
                                                      open_cards(5, label=OTHER))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_an_urgent_todo_start_is_allowed(self):
        code, said, started, _written = self.run_lease(card('VSTA-206', priority=URGENT)['task'],
                                                      open_cards(5))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_a_doing_resume_is_allowed(self):
        code, said, started, _written = self.run_lease(card('VSTA-206', section='Doing')['task'],
                                                      open_cards(5))
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
    """drain-check says the label is full instead of asking for another start."""

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

    def test_five_open_on_the_label_fails_and_stops_asking_for_a_start(self):
        code, out = self.run_check(open_rows(5) + [card('VSTA-206')])
        self.assertEqual(code, 1, out)
        self.assertIn(f'over cap: {HELD}', out)
        self.assertNotIn('loop off', out)
        self.assertNotIn('stale:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_four_open_still_reports_the_idle_loop(self):
        code, out = self.run_check(open_rows(4) + [card('VSTA-206')])
        self.assertEqual(code, 1, out)
        self.assertNotIn('over cap', out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)
        self.assertIn('stale: VSTA-206 workable in Todo for 3h.', out)
        self.assertIn('drain-check: FAIL (2 findings)', out)

    def test_another_labels_cards_do_not_make_it_fail(self):
        code, out = self.run_check(open_rows(5, label=OTHER) + [card('VSTA-206')])
        self.assertEqual(code, 1, out)
        self.assertNotIn('over cap', out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)
        self.assertIn('drain-check: FAIL (2 findings)', out)

    def test_an_urgent_card_still_gets_its_nudge_at_cap(self):
        code, out = self.run_check(open_rows(5) + [card('VSTA-206', priority=URGENT, age=1800)])
        self.assertEqual(code, 1, out)
        self.assertIn(f'over cap: {HELD}', out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)
        self.assertIn('drain-check: FAIL (2 findings)', out)


if __name__ == '__main__':
    unittest.main()
