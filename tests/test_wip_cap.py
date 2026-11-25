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
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/board-drain'
NOW = 1800000000
LABEL = 'Board Drain Loop'
OTHER = 'Responsive Mode'
PRODUCT = 'Multiprompt'
OWN = 'Multi Bot Verification'


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


DEBT_BOARD = 13734
DEBT_LABEL = 'Multiprompt Android'


def debt_card(index, column='Checks', board=DEBT_BOARD):
    return {'ticketNumber': f'MUBO-{900 + index}', 'projectId': board, 'section': column,
            'labels': [{'name': DEBT_LABEL}],
            'assignees': [{'type': 'agent', 'displayName': DEBT_LABEL + ' Agent'}],
            'updatedAt': iso(NOW - 600)}


def debt_cards(count, column='Checks', board=DEBT_BOARD):
    return [debt_card(index, column, board) for index in range(count)]


def card(key, section='Todo', priority=None, age=3 * 3600, labels=None):
    task = {'ticketNumber': key, 'projectId': 13556, 'section': section, 'status': 'Normal',
            'labels': [{'name': name} for name in (labels or [LABEL])],
            'waitingOnUserId': None, 'blockerCommentId': None,
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

    def test_only_the_starting_chats_own_label_is_counted(self):
        shared = {'labels': [{'name': PRODUCT}, {'name': OWN}]}
        known = frozenset({PRODUCT.casefold(), OWN.casefold()})
        self.assertEqual(wip.cap_labels(shared, OWN, known), [OWN])

    def test_with_no_own_label_only_a_chat_label_counts(self):
        shared = {'labels': [{'name': PRODUCT}, {'name': OWN}]}
        self.assertEqual(wip.cap_labels(shared, '', frozenset({OWN.casefold()})), [OWN])
        self.assertEqual(wip.cap_labels({'labels': [{'name': PRODUCT}]}, '', frozenset()), [])
        self.assertEqual(wip.cap_labels({'labels': [{'name': PRODUCT}]}, '',
                                        frozenset({OWN.casefold()})), [])

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

    def run_lease(self, task, cards, read_error=None, own=LABEL):
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
                patch.object(lease, 'own_label', return_value=own), \
                patch.object(lease, 'chat_labels',
                             return_value=frozenset({LABEL.casefold(), OWN.casefold()})), \
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

    def test_a_product_label_at_cap_does_not_hold_the_start(self):
        """MUBO-538: the shared app label carried 14 open cards (VSTA-266)."""
        task = card('MUBO-538', labels=[PRODUCT, OWN])['task']
        code, said, started, _written = self.run_lease(
            task, open_cards(14, label=PRODUCT) + open_cards(1, label=OWN), own=OWN)
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_the_own_label_at_cap_is_held_and_named(self):
        task = card('MUBO-538', labels=[PRODUCT, OWN])['task']
        code, said, started, _written = self.run_lease(
            task, open_cards(14, label=PRODUCT) + open_cards(5, label=OWN), own=OWN)
        self.assertEqual(code, 75, said)
        self.assertIn(f'lease: MUBO-538 held: label {OWN} has 5 open tickets in '
                      'Doing+Checks+AI Review (cap 5); ship one first', said)
        started.assert_not_called()

    def test_a_board_read_that_fails_starts_the_worker_with_one_warning(self):
        code, said, started, _written = self.run_lease(card('VSTA-206')['task'], [],
                                                       read_error=OSError('board unreadable'))
        self.assertEqual(code, 0, said)
        self.assertEqual(said.count('cap not enforced'), 1, said)
        self.assertIn('wip-cap: board 13556 read failed (board unreadable); cap not enforced', said)
        started.assert_called_once()

    def test_a_todo_start_on_a_board_over_its_review_debt_is_refused(self):
        task = dict(card('MUBO-538')['task'], projectId=DEBT_BOARD)
        code, said, started, written = self.run_lease(task, debt_cards(11))
        self.assertEqual(code, 75, said)
        self.assertIn('lease: MUBO-538 held: board 13734 review debt 11 > 10 '
                      '(Checks + AI Review); ship or review first', said)
        started.assert_not_called()
        written.assert_not_called()

    def test_a_todo_start_at_the_review_debt_cap_is_allowed(self):
        task = dict(card('MUBO-538')['task'], projectId=DEBT_BOARD)
        code, said, started, _written = self.run_lease(task, debt_cards(10))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_an_urgent_todo_start_is_allowed_over_review_debt(self):
        task = dict(card('MUBO-538', priority=URGENT)['task'], projectId=DEBT_BOARD)
        code, said, started, _written = self.run_lease(task, debt_cards(11))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_a_doing_resume_is_allowed_over_review_debt(self):
        task = dict(card('MUBO-538', section='Doing')['task'], projectId=DEBT_BOARD)
        code, said, started, _written = self.run_lease(task, debt_cards(11))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()

    def test_a_board_with_no_review_debt_row_is_unchanged(self):
        code, said, started, _written = self.run_lease(card('VSTA-206')['task'],
                                                      debt_cards(11, board=13556))
        self.assertEqual(code, 0, said)
        self.assertNotIn('held:', said)
        started.assert_called_once()


class ReviewDebtTest(unittest.TestCase):
    """A board over its review debt starts nothing new until someone ships (VSTA-271)."""

    def test_the_debt_is_every_card_in_the_two_review_columns(self):
        rows = (debt_cards(6, 'Checks') + debt_cards(6, 'AI Review')
                + debt_cards(2, 'Doing') + debt_cards(2, 'Done'))
        self.assertEqual(wip.review_debt(rows), 12)

    def test_an_empty_board_owes_nothing(self):
        self.assertEqual(wip.review_debt([]), 0)
        self.assertEqual(wip.review_debt(None), 0)

    def test_at_the_cap_is_not_over_and_one_card_past_it_is(self):
        self.assertIsNone(wip.review_debt_over(DEBT_BOARD, debt_cards(10)))
        self.assertEqual(wip.review_debt_over(DEBT_BOARD, debt_cards(11)), (11, 10))

    def test_a_board_with_no_row_is_never_held(self):
        self.assertIsNone(wip.review_debt_cap(13556))
        self.assertIsNone(wip.review_debt_held(13556, debt_cards(30)))

    def test_the_held_line_names_the_board_the_debt_and_the_cap(self):
        self.assertEqual(wip.review_debt_held(DEBT_BOARD, debt_cards(14)),
                         'board 13734 review debt 14 > 10 (Checks + AI Review); '
                         'ship or review first')


class OwnLabelTest(unittest.TestCase):
    """The lease reads the label the starting chat armed its loop with (VSTA-266)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        loop_state = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.directory)})
        loop_state.start()
        self.addCleanup(loop_state.stop)
        self.loop = drain.loop_state
        self.env = {'HOME': str(self.directory)}

    def record(self, name, label, owner_pid=1):
        (self.directory / f'{self.loop.slug(name)}.json').write_text(json.dumps(
            {'name': name, 'label': label, 'owner_pid': owner_pid,
             'host': socket.gethostname(), 'armed_at': iso(NOW)}))

    def test_the_label_the_chat_armed_with_is_its_own(self):
        self.record(OWN, OWN)
        self.assertEqual(self.loop.own_label({**self.env, 'BOARD_DRAIN_NAME': OWN}), OWN)

    def test_a_launch_with_no_tab_is_found_by_the_process_above_it(self):
        self.record(OWN, OWN, owner_pid=os.getppid())
        self.assertEqual(self.loop.own_label(self.env), OWN)

    def test_the_named_chat_wins_over_a_process_above_it(self):
        self.record(OTHER, OTHER, owner_pid=os.getppid())
        self.record(OWN, OWN)
        self.assertEqual(self.loop.own_label({**self.env, 'BOARD_DRAIN_NAME': OWN}), OWN)

    def test_no_record_reads_no_own_label(self):
        self.assertEqual(self.loop.own_label(self.env), '')

    def test_chat_labels_names_every_armed_chats_label(self):
        self.record(OWN, OWN)
        self.record('Multi Bot Bugs', PRODUCT)
        self.assertEqual(self.loop.chat_labels(),
                         frozenset({OWN.casefold(), PRODUCT.casefold()}))


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
        self.assertIn('urgent: VSTA-206 is urgent and waiting in Todo; start it before any '
                      'other ticket.', out)
        self.assertIn('drain-check: FAIL (3 findings)', out)


if __name__ == '__main__':
    unittest.main()
