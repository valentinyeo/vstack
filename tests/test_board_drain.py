import contextlib
from datetime import datetime, timezone
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/board-drain'
FIXTURES = ROOT / 'tests/fixtures/board_drain'
NOW = 1800000000


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


drain = load('board_drain_check', SKILL / 'drain-check')
loop = load('board_drain_loop_state', SKILL / 'loop-state')
sync = load('board_drain_sync', SKILL / 'sync')
watch = load('board_drain_watch', SKILL / 'watch')


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


ADD_LINE = 'ADD worker, ADD chat: all gates green'
HOLD_LINE = 'HOLD worker, HOLD chat: load5 30.24 is 1.68x 18 cores, cpu some60 26%'


def snapshot(key):
    """A real ticket and its comments, as `hypertask --json task get` returned them."""
    task = json.loads((FIXTURES / f'{key}.task.json').read_text())['tasks'][0]
    comments = json.loads((FIXTURES / f'{key}.comments.json').read_text())['comments']
    return {'task': task, 'comments': comments}


def todo(key, age=1800, waiting_on=None, blocker=None, comments=()):
    task = {'ticketNumber': key, 'projectId': 2060, 'section': 'Todo',
            'labels': [{'name': 'Poteto'}], 'waitingOnUserId': waiting_on,
            'blockerCommentId': blocker, 'updatedAt': iso(NOW - age)}
    return {'task': task, 'comments': list(comments)}


def agent_assignee(name='Poteto'):
    """The shape `task get` sends for a ticket an agent holds."""
    return {'id': 6, 'email': '', 'displayName': name, 'type': 'agent',
            'agentId': '8658ed82-c372-4e10-8410-0989067bb08f',
            'agent': {'id': '8658ed82-c372-4e10-8410-0989067bb08f', 'displayName': name}}


def doing(key, age=300, section='Doing', assignees=None):
    task = {'ticketNumber': key, 'projectId': 2060, 'section': section,
            'labels': [{'name': 'Poteto'}], 'waitingOnUserId': None,
            'blockerCommentId': None, 'updatedAt': iso(NOW - age),
            'assignees': [agent_assignee()] if assignees is None else assignees}
    return {'task': task, 'comments': []}


def vsta4():
    """VSTA-4 as `hypertask --json task get VSTA-4` sent it: an agent holds it."""
    task = json.loads((FIXTURES / 'VSTA-4.task.json').read_text())['tasks'][0]
    task['updatedAt'] = iso(NOW - 300)
    return {'task': task, 'comments': []}


def vsta(key, section='Todo', age=1800, assignees=None):
    """A board-13556 ticket on the label this check drains."""
    task = {'ticketNumber': key, 'projectId': 13556, 'section': section,
            'labels': [{'name': 'Board Drain Loop'}], 'status': 'Normal',
            'waitingOnUserId': None, 'blockerCommentId': None,
            'updatedAt': iso(NOW - age), 'assignees': assignees or []}
    return {'task': task, 'comments': []}


def blocked_by():
    """VSTA-7's links as `hypertask --json task relations VSTA-7` sent them."""
    return json.loads((FIXTURES / 'VSTA-7.relations.json').read_text())['relations']


def agent_comment(age):
    return {'createdAt': iso(NOW - age), 'creatorId': 6, 'agent': {'id': 'a'},
            'agent_display_name': 'Poteto', 'text': 'working it'}


def human_comment(age):
    return {'createdAt': iso(NOW - age), 'creatorId': 6,
            'creator': {'id': 6, 'displayName': 'Valentin Yeo'}, 'text': 'yes, go'}


def dead_pid():
    """The pid of a process that has already exited."""
    process = subprocess.Popen([sys.executable, '-c', 'pass'])
    process.wait()
    return process.pid


class Clock:
    """A fake clock: time only moves when the watcher decides to sleep."""

    def __init__(self, moment=NOW):
        self.now = moment
        self.on_sleep = None

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(int((self.now - NOW) // seconds))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        env = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.directory)})
        env.start()
        self.addCleanup(env.stop)
        timer = patch.object(drain.loop_state, 'timer_enabled', return_value=True)
        timer.start()
        self.addCleanup(timer.stop)

    def run_check(self, rows, *extra, alive=False, board=2060, label='Poteto',
                  probe=(0, ADD_LINE)):
        fixture = self.directory / 'fixture.json'
        fixture.write_text(json.dumps(rows))
        argv = ['--board', str(board), '--label', label, '--fixture', str(fixture),
                '--now', iso(NOW), *extra]
        out = io.StringIO()
        with patch.object(drain, 'probe_load', return_value=probe), \
                patch.object(drain.reconcile, 'worker_alive', return_value=alive), \
                contextlib.redirect_stdout(out):
            code = drain.main(argv)
        return code, out.getvalue()

    def test_real_case_all_four_unmarked(self):
        # Board 2060 label Poteto this morning, unedited: four real tickets sat
        # unmarked in Todo for hours and nothing was in Doing.
        rows = []
        for key in ('SOFT-2809', 'SOFT-2810', 'SOFT-2813', 'SOFT-2815'):
            row = snapshot(key)
            row['task'].update(section='Todo', waitingOnUserId=None, blockerCommentId=None,
                               labels=[{'name': 'Poteto'}], updatedAt=iso(NOW - 3 * 3600))
            rows.append(row)
        code, out = self.run_check(rows)
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 4 workable Todo, nothing in Doing.', out)
        for key in ('SOFT-2809', 'SOFT-2810', 'SOFT-2813', 'SOFT-2815'):
            self.assertIn(f'stale: {key} workable in Todo for 3h.', out)
            self.assertNotIn(f'waiting: {key}', out)
        self.assertIn('drain-check: FAIL (5 findings)', out)

    def test_real_case_two_marked_variant(self):
        # This morning, marked side: SOFT-2809 and SOFT-2813 sat unmarked in Todo
        # for hours, two other tickets were marked waiting, and nothing was in Doing.
        rows = []
        for key in ('SOFT-2809', 'SOFT-2813'):
            row = snapshot(key)
            row['task'].update(section='Todo', waitingOnUserId=None, blockerCommentId=None,
                               labels=[{'name': 'Poteto'}], updatedAt=iso(NOW - 3 * 3600))
            rows.append(row)
        rows += [todo('SOFT-2801', waiting_on=6), todo('SOFT-2802', waiting_on=6)]
        code, out = self.run_check(rows)
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 2 workable Todo, nothing in Doing.', out)
        self.assertIn('start a worker on SOFT-2809.', out)
        self.assertIn('stale: SOFT-2809 workable in Todo for 3h.', out)
        self.assertIn('stale: SOFT-2813 workable in Todo for 3h.', out)
        self.assertIn('waiting: SOFT-2801 (marked)', out)
        self.assertIn('waiting: SOFT-2802 (marked)', out)
        self.assertIn('drain-check: FAIL (3 findings)', out)

    def test_all_marked_todo_passes(self):
        code, out = self.run_check([todo('SOFT-2901', waiting_on=6),
                                    todo('SOFT-2902', blocker=9001)])
        self.assertEqual(code, 0, out)
        self.assertIn('waiting: SOFT-2901 (marked)', out)
        self.assertIn('waiting: SOFT-2902 (marked)', out)
        self.assertIn('drain-check: PASS', out)

    def test_a_human_answer_after_the_agent_fails(self):
        comments = [agent_comment(3600), human_comment(600)]
        code, out = self.run_check([todo('SOFT-2903', waiting_on=6, comments=comments)])
        self.assertEqual(code, 1, out)
        self.assertIn('answered: SOFT-2903 clear the waiting-on mark and work it', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_an_agent_comment_after_the_human_stays_waiting(self):
        comments = [human_comment(3600), agent_comment(600)]
        code, out = self.run_check([todo('SOFT-2904', waiting_on=6, comments=comments)])
        self.assertEqual(code, 0, out)
        self.assertIn('waiting: SOFT-2904 (marked)', out)

    def test_a_fresh_doing_ticket_is_alive(self):
        for section in ('Doing', 'Building'):
            with self.subTest(section=section):
                code, out = self.run_check([doing('SOFT-2905', age=300, section=section)])
                self.assertEqual(code, 0, out)
                self.assertIn('drain-check: PASS', out)

    def test_an_old_doing_ticket_without_a_worker_stalls(self):
        code, out = self.run_check([doing('SOFT-2906', age=7200)], alive=False)
        self.assertEqual(code, 1, out)
        self.assertIn('stalled: SOFT-2906 in Doing with no live worker.', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_live_lease_counts_even_on_an_old_doing_ticket(self):
        code, out = self.run_check([doing('SOFT-2907', age=7200)], alive=True)
        self.assertEqual(code, 0, out)

    def test_an_assigned_ticket_in_a_working_column_is_not_flagged(self):
        code, out = self.run_check([vsta4()], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 0, out)
        self.assertNotIn('unassigned:', out)
        self.assertIn('drain-check: PASS', out)

    def test_an_unassigned_ticket_in_a_working_column_is_flagged(self):
        row = vsta4()
        row['task']['assignees'] = []
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertIn('unassigned: VSTA-4 in AI Review has no agent assigned. Assign your own '
                      'agent login to it (task assign VSTA-4 --self, with your token).', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_only_a_human_assignee_still_counts_as_unassigned(self):
        row = vsta4()
        row['task']['assignees'] = [{'id': 6, 'email': 'valentin.yeo@gmail.com',
                                     'displayName': 'Valentin Yeo', 'type': 'user'}]
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertIn('unassigned: VSTA-4 in AI Review has no agent assigned.', out)

    def test_every_working_column_needs_an_agent(self):
        for column in ('Doing', 'Building', 'Checks', 'AI Review', 'Verifier'):
            with self.subTest(column=column):
                row = doing('SOFT-2917', section=column, assignees=[])
                code, out = self.run_check([row])
                self.assertEqual(code, 1, out)
                self.assertIn(f'unassigned: SOFT-2917 in {column} has no agent assigned.', out)

    def test_an_unassigned_todo_ticket_is_not_an_unassigned_finding(self):
        # Todo is where a ticket waits for an owner; only a working column needs one.
        row = todo('SOFT-2918')
        row['task']['assignees'] = []
        code, out = self.run_check([row])
        self.assertNotIn('unassigned:', out)

    def test_a_todo_with_no_timestamp_is_never_stale(self):
        # The API may send updatedAt null; that is not a crash and not an age.
        row = todo('SOFT-2910')
        row['task']['updatedAt'] = None
        code, out = self.run_check([row])
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)
        self.assertIn('start a worker on SOFT-2910.', out)
        self.assertNotIn('stale:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_an_unparsable_timestamp_is_never_fresh(self):
        row = todo('SOFT-2911')
        row['task']['updatedAt'] = 'not a date'
        code, out = self.run_check([row])
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 1 workable Todo', out)
        self.assertNotIn('stale:', out)

    def test_a_marked_todo_with_no_comment_timestamp_does_not_crash(self):
        comments = [dict(agent_comment(3600), createdAt=None)]
        code, out = self.run_check([todo('SOFT-2912', waiting_on=6, comments=comments)])
        self.assertEqual(code, 0, out)
        self.assertIn('waiting: SOFT-2912 (marked)', out)
        self.assertIn('drain-check: PASS', out)

    def test_an_unexpected_error_exits_two_not_one(self):
        with patch.object(drain, 'check', side_effect=AttributeError('boom')), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code = drain.main(['--board', '2060', '--label', 'Poteto', '--now', iso(NOW)])
        self.assertEqual(code, 2, out.getvalue() + err.getvalue())
        self.assertIn('drain-check: error: boom', err.getvalue())

    def test_a_ticket_linked_to_open_blockers_is_not_workable(self):
        # VSTA-7 is BlockedBy VSTA-2 and VSTA-3, both open, so it waits outside the drain.
        rows = [vsta('VSTA-7', age=3 * 3600), vsta('VSTA-2', age=300),
                vsta('VSTA-3', age=300)]
        rows[0]['relations'] = blocked_by()
        for row in rows[1:]:
            row['task'].update(section='Doing', assignees=[agent_assignee()])
        code, out = self.run_check(rows, board=13556, label='Board Drain Loop')
        self.assertEqual(code, 0, out)
        self.assertIn('blocked: VSTA-7 by VSTA-2, VSTA-3', out)
        self.assertNotIn('stale:', out)
        self.assertNotIn('loop off:', out)
        self.assertIn('drain-check: PASS', out)

    def test_a_ticket_whose_blockers_are_done_is_workable(self):
        rows = [vsta('VSTA-7'), vsta('VSTA-2', section='Done'), vsta('VSTA-3', section='Done')]
        rows[0]['relations'] = blocked_by()
        code, out = self.run_check(rows, board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)
        self.assertIn('start a worker on VSTA-7.', out)
        self.assertNotIn('blocked:', out)

    def test_one_open_blocker_among_done_ones_still_blocks(self):
        rows = [vsta('VSTA-7'), vsta('VSTA-2', section='Done'), vsta('VSTA-3')]
        rows[0]['relations'] = blocked_by()
        code, out = self.run_check(rows, board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertIn('blocked: VSTA-7 by VSTA-3', out)
        self.assertNotIn('blocked: VSTA-7 by VSTA-3,', out)
        self.assertIn('loop off: 1 workable Todo', out)

    def test_a_ticket_with_no_links_reads_as_before(self):
        for relations in (None, []):
            with self.subTest(relations=relations):
                row = vsta('VSTA-7')
                if relations is not None:
                    row['relations'] = relations
                code, out = self.run_check([row], board=13556, label='Board Drain Loop')
                self.assertEqual(code, 1, out)
                self.assertIn('loop off: 1 workable Todo', out)
                self.assertNotIn('blocked:', out)

    def test_a_blocker_missing_from_the_board_counts_open(self):
        row = vsta('VSTA-7')
        row['relations'] = [{'relationType': 'BlockedBy', 'direction': 'outgoing',
                             'otherTask': {'ticketNumber': 'SOFT-99', 'status': 'Normal'}}]
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 0, out)
        self.assertIn('blocked: VSTA-7 by SOFT-99', out)
        self.assertIn('drain-check: PASS', out)

    def test_a_missing_blocker_whose_status_says_done_does_not_block(self):
        row = vsta('VSTA-7')
        row['relations'] = [{'relationType': 'BlockedBy', 'direction': 'outgoing',
                             'otherTask': {'ticketNumber': 'SOFT-99', 'status': 'Done'}}]
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertNotIn('blocked:', out)
        self.assertIn('loop off: 1 workable Todo', out)

    def test_incoming_and_blocks_links_never_block(self):
        row = vsta('VSTA-7')
        row['relations'] = [
            {'relationType': 'BlockedBy', 'direction': 'incoming',
             'otherTask': {'ticketNumber': 'VSTA-9', 'status': 'Normal'}},
            {'relationType': 'Blocks', 'direction': 'outgoing',
             'otherTask': {'ticketNumber': 'VSTA-10', 'status': 'Normal'}}]
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertNotIn('blocked:', out)
        self.assertIn('loop off: 1 workable Todo', out)

    def test_a_marked_ticket_is_never_asked_for_its_links(self):
        # A marked wait already keeps it out of the drain; no links read needed.
        row = vsta('VSTA-8')
        row['task']['waitingOnUserId'] = 6
        row['relations'] = blocked_by()
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 0, out)
        self.assertIn('waiting: VSTA-8 (marked)', out)
        self.assertNotIn('blocked:', out)

    def test_a_missing_loop_state_fails_when_named(self):
        code, out = self.run_check([todo('SOFT-2908', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('loop state: not armed', out)

    def test_a_dead_watcher_fails_the_check_when_named(self):
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW)
        loop.record_watch('HT Test', dead_pid(), now=NOW)
        code, out = self.run_check([todo('SOFT-2929', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('loop state: watcher dead', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_an_armed_loop_with_a_fresh_sync_passes(self):
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW)
        code, out = self.run_check([todo('SOFT-2913', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 0, out)
        self.assertIn('drain-check: PASS', out)
        self.assertNotIn('sync stale', out)

    def test_a_failed_sync_fails_the_check(self):
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_sync('HT Test', False, 'usage: --apply requires SHIP_SESSION_NAME', now=NOW)
        code, out = self.run_check([todo('SOFT-2914', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('sync failed: usage: --apply requires SHIP_SESSION_NAME. '
                      'Fix it, then run ./sync.', out)

    def test_a_stale_sync_fails_the_check(self):
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW - 3600)
        code, out = self.run_check([todo('SOFT-2915', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('sync stale: last sync 60 min ago.', out)

    def test_a_missing_sync_fails_the_check(self):
        loop.arm('HT Test', every='15m', now=NOW)
        code, out = self.run_check([todo('SOFT-2916', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('sync stale: no sync recorded yet.', out)

    def test_a_server_hold_turns_loop_off_and_stale_into_a_held_line(self):
        # Valentin's rule holds launches while the server is overloaded, so an
        # idle drain on a HOLD server is obeying him, not broken.
        code, out = self.run_check([todo('SOFT-2920', age=3 * 3600),
                                    todo('SOFT-2921', age=3 * 3600)],
                                   probe=(2, HOLD_LINE))
        self.assertEqual(code, 0, out)
        self.assertIn(f'held: {HOLD_LINE}; 2 workable Todo wait for the server', out)
        self.assertNotIn('loop off:', out)
        self.assertNotIn('stale:', out)
        self.assertIn('drain-check: PASS', out)

    def test_a_server_hold_never_hides_a_stalled_ticket(self):
        code, out = self.run_check([doing('SOFT-2922', age=7200)], alive=False,
                                   probe=(2, HOLD_LINE))
        self.assertEqual(code, 1, out)
        self.assertIn('stalled: SOFT-2922 in Doing with no live worker.', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_server_hold_never_hides_an_answered_ticket(self):
        comments = [agent_comment(3600), human_comment(600)]
        code, out = self.run_check([todo('SOFT-2923', waiting_on=6, comments=comments)],
                                   probe=(2, HOLD_LINE))
        self.assertEqual(code, 1, out)
        self.assertIn('answered: SOFT-2923', out)

    def test_an_add_server_still_fails_loop_off(self):
        code, out = self.run_check([todo('SOFT-2924')], probe=(0, ADD_LINE))
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)

    def test_a_careful_server_still_fails_loop_off(self):
        code, out = self.run_check([todo('SOFT-2925')],
                                   probe=(1, 'CAREFUL worker, ADD chat: load5 20.0'))
        self.assertEqual(code, 1, out)
        self.assertIn('loop off:', out)

    def test_a_probe_failure_never_hides_a_finding(self):
        code, out = self.run_check([todo('SOFT-2926', age=3 * 3600)], probe=(3, ''))
        self.assertEqual(code, 1, out)
        self.assertIn('loop off:', out)
        self.assertIn('stale:', out)
        self.assertNotIn('held:', out)

    def test_no_load_skips_the_probe(self):
        code, out = self.run_check([todo('SOFT-2927')], '--no-load')
        self.assertEqual(code, 1, out)
        self.assertIn('loop off:', out)
        self.assertNotIn('held:', out)

    def test_the_probe_runs_only_when_loop_off_or_stale_is_there_to_judge(self):
        with patch.object(drain, 'probe_load', return_value=(2, HOLD_LINE)) as probe:
            fixture = self.directory / 'fixture.json'
            fixture.write_text(json.dumps([todo('SOFT-2928', waiting_on=6)]))
            with contextlib.redirect_stdout(io.StringIO()):
                code = drain.main(['--board', '2060', '--label', 'Poteto',
                                   '--fixture', str(fixture), '--now', iso(NOW)])
        self.assertEqual(code, 0)
        probe.assert_not_called()

    def test_a_usage_error_exits_two(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as raised:
            drain.main(['--board', '0', '--label', 'Poteto'])
        self.assertEqual(raised.exception.code, 2)


class RuleBreakTest(CheckTest):
    """Board-rule breaks reach the chat that owns them, in its own drain check."""

    def run_payload(self, payload, *extra, alive=False, board=2060, label='Poteto',
                    probe=(0, ADD_LINE), fail_rules=frozenset()):
        fixture = self.directory / 'fixture.json'
        fixture.write_text(json.dumps(payload))
        argv = ['--board', str(board), '--label', label, '--fixture', str(fixture),
                '--now', iso(NOW), *extra]
        out = io.StringIO()
        with patch.object(drain, 'probe_load', return_value=probe), \
                patch.object(drain, 'FAIL_RULES', fail_rules), \
                patch.object(drain.reconcile, 'worker_alive', return_value=alive), \
                contextlib.redirect_stdout(out):
            code = drain.main(argv)
        return code, out.getvalue()

    def worker_card(self, assignees=None):
        task = {'ticketNumber': 'SOFT-2931', 'projectId': 2060, 'section': 'Doing',
                'labels': [{'name': 'Poteto'}], 'updatedAt': iso(NOW - 300),
                'assignees': [agent_assignee()] if assignees is None else assignees}
        return {'task': task, 'comments': []}

    CHAT = 'Poteto (live-p, claude, /tmp)\n'

    def payload(self, rows, **facts):
        """Rows plus the board facts a drain-check fixture does not carry."""
        return {'rows': rows, 'roster': self.CHAT, 'chats': ['Poteto'], **facts}

    def test_one_break_prints_one_warning_line_and_still_passes(self):
        row = todo('SOFT-2930')
        row['task']['assignees'] = [{'id': 6, 'email': 'valentin.yeo@gmail.com',
                                     'displayName': 'Valentin Yeo', 'type': 'user'}]
        code, out = self.run_payload(self.payload([row, self.worker_card()],
                                                  workers={'SOFT-2931': True}), alive=True)
        breaks = [line for line in out.splitlines() if line.startswith('rule-break: ')]
        self.assertEqual(len(breaks), 1, out)
        self.assertEqual(breaks[0], "rule-break: SOFT-2930 agent-assignee: assignee "
                                    "'Valentin Yeo' is a person, not an agent; assign the chat agent")
        self.assertIn('drain-check: PASS', out)
        self.assertEqual(code, 0, out)

    def test_a_promoted_rule_fails_the_check(self):
        row = todo('SOFT-2932')
        row['task']['assignees'] = [{'id': 6, 'displayName': 'Valentin Yeo', 'type': 'user'}]
        code, out = self.run_payload(self.payload([row, self.worker_card()],
                                                  workers={'SOFT-2931': True}), alive=True,
                                     fail_rules=frozenset({'agent-assignee'}))
        self.assertEqual(code, 1, out)
        self.assertIn('rule-break: SOFT-2932 agent-assignee:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_another_chats_view_break_is_not_this_chats_finding(self):
        # Both labels are on this ticket, but the broken view belongs to another chat.
        row = todo('SOFT-2933', waiting_on=6)
        row['task']['labels'] = [{'name': 'Poteto'}, {'name': 'Multi Bot Bugs'}]
        payload = self.payload([row], chats=['Poteto', 'Multi Bot Bugs'], views=[
            {'slug': 'poteto', 'id': 'v-1', 'owner': {'displayName': 'Poteto'}},
            {'slug': 'multi-bot-bugs', 'id': 'v-2', 'owner': {'displayName': 'Valentin Yeo'}},
        ])
        code, out = self.run_payload(payload)
        self.assertEqual(code, 0, out)
        self.assertIn('drain-check: PASS', out)
        self.assertNotIn('Multi Bot Bugs', out)
        self.assertNotIn('rule-break:', out)

    def test_human_owner_view_with_matching_title_is_not_a_view_owner_break(self):
        label = 'Seamless Session Transitioning'
        row = {'task': {'ticketNumber': 'MUBO-101', 'projectId': 13734, 'section': 'Todo',
                        'labels': [{'name': label}], 'updatedAt': iso(NOW - 300),
                        'waitingOnUserId': 6},
               'comments': []}
        payload = {
            'rows': [row],
            'roster': f'{label} (live-s, claude, /tmp)\n',
            'chats': [label],
            'labels': [{'id': 'L-seamless', 'name': label}],
            'views': [{
                'id': 'v-seamless',
                'title': label,
                'slug': 'seamless-session-transitioning',
                'owner': {'id': 6, 'displayName': 'Valentin Yeo'},
                'board_filters': {'addedFilters': [{'type': 'Labels',
                                                    'searchPayload': [{'id': 'L-seamless'}]}]},
            }],
        }
        code, out = self.run_payload(payload, board=13734, label=label,
                                     fail_rules=frozenset({'view-owner'}))
        self.assertEqual(code, 0, out)
        self.assertIn('drain-check: PASS', out)
        self.assertNotIn('rule-break:', out)

    def test_human_owner_view_with_mismatched_title_still_flags_view_owner(self):
        label = 'Seamless Session Transitioning'
        row = {'task': {'ticketNumber': 'MUBO-102', 'projectId': 13734, 'section': 'Todo',
                        'labels': [{'name': label}], 'updatedAt': iso(NOW - 300),
                        'waitingOnUserId': 6},
               'comments': []}
        payload = {
            'rows': [row],
            'roster': f'{label} (live-s, claude, /tmp)\n',
            'chats': [label],
            'labels': [{'id': 'L-seamless', 'name': label}],
            'views': [{
                'id': 'v-personal',
                'title': "Valentin's Seamless View",
                'slug': 'seamless-session-transitioning',
                'owner': {'id': 6, 'displayName': 'Valentin Yeo'},
                'board_filters': {'addedFilters': [{'type': 'Labels',
                                                    'searchPayload': [{'id': 'L-seamless'}]}]},
            }],
        }
        code, out = self.run_payload(payload, board=13734, label=label,
                                     fail_rules=frozenset({'view-owner'}))
        self.assertEqual(code, 1, out)
        self.assertIn('rule-break: (view) view-owner:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_revoked_agent_still_prints_and_names_who_can_fix_it(self):
        row = self.worker_card(assignees=[agent_assignee() | {'agentId': 'gone-agent'}])
        payload = self.payload([row], workers={'SOFT-2931': True}, agents=[])
        code, out = self.run_payload(payload, alive=True)
        self.assertEqual(code, 0, out)
        self.assertIn('rule-break: SOFT-2931 agent-assignee:', out)
        self.assertIn('revoked', out)
        self.assertIn('ask Valentin', out)
        self.assertIn('drain-check: PASS', out)

    def test_the_tick_reads_the_board_once_and_adds_one_github_call(self):
        task = self.worker_card()['task']
        saved = {'at': NOW - 60, 'probe_since': '2027-01-01T00:00:00Z', 'repos': [],
                 'tickets': {'SOFT-2931': {'at': NOW - 60, 'updated_at': task['updatedAt'],
                                           'pulls': [], 'facts': {}}}}
        board = drain.reconcile.BOARDS[2060]
        lint = drain.lint_module()
        gh_calls, board_reads = [], []

        def fake_run(*args, **kwargs):
            gh_calls.append(args)
            return json.dumps({'items': [], 'total_count': 0})

        def fake_tickets(**kwargs):
            board_reads.append(kwargs)
            return [task]

        out = io.StringIO()
        with patch.object(drain.reconcile, 'board_config', return_value=board), \
                patch.object(drain.reconcile, 'tickets', side_effect=fake_tickets), \
                patch.object(drain.reconcile, 'api', return_value={}), \
                patch.object(drain.reconcile, 'read_board_facts', return_value=saved), \
                patch.object(drain.reconcile, 'run', side_effect=fake_run), \
                patch.object(drain.reconcile, 'worker_alive', return_value=True), \
                patch.object(drain, 'probe_load', return_value=(0, ADD_LINE)), \
                patch.object(lint, 'mp_session_names', return_value=set()), \
                patch.object(lint, 'published_names', return_value=set()), \
                patch.object(lint.owners, 'live_names', return_value=set()), \
                contextlib.redirect_stdout(out):
            code = drain.main(['--board', '2060', '--label', 'Poteto', '--now', iso(NOW)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(len(board_reads), 1, 'one board read per tick')
        self.assertEqual(len(gh_calls), 1, gh_calls)
        self.assertIn('search/issues', gh_calls[0])


def write_tool(path, body):
    path.write_text(f'#!{sys.executable}\n' + body)
    path.chmod(0o755)


class HypertaskPathTest(unittest.TestCase):
    """A `hypertask` worker shim early on PATH must never win over the real CLI."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.home = self.directory / 'home'
        self.real_bin = self.home / '.local/bin'
        self.real_bin.mkdir(parents=True)
        self.shim_bin = self.directory / 'shim'
        self.shim_bin.mkdir()
        self.real_log = self.directory / 'real.log'
        self.shim_log = self.directory / 'shim.log'
        self.real_log.write_text('')
        write_tool(self.shim_bin / 'hypertask',
                   f'import pathlib, sys\n'
                   f'pathlib.Path({str(self.shim_log)!r}).write_text(" ".join(sys.argv[1:]))\n'
                   'sys.stderr.write("hypertask: no board login\\n")\n'
                   'raise SystemExit(3)\n')
        write_tool(self.real_bin / 'hypertask',
                   'import json, os, pathlib, sys\n'
                   'log = pathlib.Path(os.environ["REAL_HYPERTASK_LOG"])\n'
                   'log.write_text(log.read_text() + " ".join(sys.argv[1:]) + "\\n")\n'
                   'print(json.dumps({"tasks": [], "total": 0}))\n')

    def environment(self, **extra):
        """The shim first on PATH, the real CLI only in HOME/.local/bin."""
        return {'HOME': str(self.home), 'PATH': f'{self.shim_bin}:/usr/bin:/bin',
                'REAL_HYPERTASK_LOG': str(self.real_log),
                'BOARD_DRAIN_STATE_DIR': str(self.directory / 'state'),
                'RECONCILE_CACHE': str(self.directory / 'cache.json'),
                **extra}

    def run_script(self, name, *argv, **extra):
        return subprocess.run([sys.executable, str(SKILL / name), *argv], capture_output=True,
                              text=True, env=self.environment(**extra), timeout=60)

    def test_drain_check_reads_the_real_cli_not_the_shim(self):
        done = self.run_script('drain-check', '--board', '2060', '--label', 'Poteto',
                              '--now', iso(NOW))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('drain-check: PASS', done.stdout)
        self.assertFalse(self.shim_log.exists(), done.stdout + done.stderr)
        self.assertIn('task list', self.real_log.read_text())

    def test_sync_reads_the_real_cli_not_the_shim(self):
        done = self.run_script('sync', '--board', '2060', '--label', 'Poteto',
                               '--name', 'HT Test', HT_TOKEN='tok-from-env')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('sync: ok', done.stdout)
        self.assertFalse(self.shim_log.exists(), done.stdout + done.stderr)
        self.assertIn('task list', self.real_log.read_text())

    def test_both_scripts_fix_the_path_before_their_steps(self):
        for name, module in (('drain-check', 'board_drain_check_fresh'),
                             ('sync', 'board_drain_sync_fresh')):
            with self.subTest(script=name), \
                    patch.dict(os.environ, {'HOME': str(self.home),
                                            'PATH': f'{self.shim_bin}:/usr/bin:/bin'}):
                load(module, SKILL / name)
                path = os.environ['PATH'].split(os.pathsep)
                self.assertEqual(path[0], str(self.real_bin))
                self.assertEqual(path.count(str(self.real_bin)), 1)

    def test_the_real_bin_goes_first_and_only_once(self):
        before = f'{self.real_bin}{os.pathsep}/usr/bin'
        with patch.dict(os.environ, {'HOME': str(self.home), 'PATH': before}):
            loop.ensure_cli_path()
            self.assertEqual(os.environ['PATH'], before)
            loop.ensure_cli_path()
            self.assertEqual(os.environ['PATH'], before)

    def test_a_missing_real_bin_leaves_path_alone(self):
        with patch.dict(os.environ, {'HOME': str(self.directory / 'nowhere'),
                                    'PATH': '/usr/bin:/bin'}):
            loop.ensure_cli_path()
            self.assertEqual(os.environ['PATH'], '/usr/bin:/bin')


class LoopStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        env = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.directory)})
        env.start()
        self.addCleanup(env.stop)

    def test_arm_then_status_reads_armed(self):
        state = loop.arm('HT Test', every='15m', job='cron-1', now=NOW)
        self.assertEqual(set(state), {'name', 'every', 'armed_at', 'expires_at', 'job',
                                      'owner_pid', 'host'})
        self.assertEqual(state['expires_at'], iso(NOW + 7 * 86400))
        self.assertTrue((self.directory / 'ht-test.json').exists())
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_arm_records_the_board_and_label_it_drains(self):
        state = loop.arm('Vstack Maintainer', every='15m', job='cron-1', board=13556,
                         label='Vstack', now=NOW)
        self.assertEqual(state['board'], 13556)
        self.assertEqual(state['label'], 'Vstack')
        self.assertEqual(loop.status('Vstack Maintainer', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_a_file_without_a_board_and_label_still_reads(self):
        state = loop.arm('HT Test', now=NOW)
        self.assertNotIn('board', state)
        self.assertNotIn('label', state)
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_the_cli_records_the_board_and_label(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.directory))
        result = subprocess.run([sys.executable, str(SKILL / 'loop-state'), 'arm',
                                 '--name', 'Vstack Maintainer', '--every', '15m',
                                 '--job', 'cron-1', '--board', '13556', '--label', 'Vstack'],
                                capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads((self.directory / 'vstack-maintainer.json').read_text())
        self.assertEqual(state['board'], 13556)
        self.assertEqual(state['label'], 'Vstack')

    def test_expiry_within_a_day_asks_for_a_rearm(self):
        loop.arm('HT Test', expires=iso(NOW + 10 * 3600), now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW),
                         (3, 'expires soon (<24h): re-arm now'))

    def test_an_expired_loop_is_not_armed(self):
        loop.arm('HT Test', expires=iso(NOW - 60), now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_a_dead_owner_pid_is_not_armed(self):
        process = subprocess.Popen([sys.executable, '-c', 'pass'])
        process.wait()
        dead = process.pid
        state = loop.arm('HT Test', now=NOW)
        self.assertFalse(loop.reconcile.pid_alive(dead))
        state['owner_pid'] = dead
        loop.state_path('HT Test').write_text(json.dumps(state))
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_another_host_is_not_armed(self):
        state = loop.arm('HT Test', now=NOW)
        state['host'] = 'some-other-machine'
        loop.state_path('HT Test').write_text(json.dumps(state))
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_a_missing_file_is_not_armed(self):
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))
        loop.arm('HT Test', now=NOW)
        loop.clear('HT Test')
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_record_sync_creates_the_file_without_arming(self):
        record = loop.record_sync('HT Test', False, 'usage: no token', now=NOW)
        self.assertEqual(record, {'at': iso(NOW), 'ok': False, 'reason': 'usage: no token'})
        self.assertTrue((self.directory / 'ht-test.json').exists())
        self.assertEqual(loop.sync_state('HT Test'), record)
        # A sync record alone never arms the loop.
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_record_sync_keeps_the_armed_loop(self):
        loop.arm('HT Test', every='15m', job='cron-1', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))
        self.assertEqual(loop.sync_state('HT Test'), {'at': iso(NOW), 'ok': True, 'reason': ''})

    def test_arm_keeps_last_sync_and_watch_fields(self):
        loop.record_sync('HT Test', True, 'ok', now=NOW)
        loop.record_watch('HT Test', os.getpid(), now=NOW)
        prior = loop.stored('HT Test')
        state = loop.arm('HT Test', every='6h', job='cron-1', board=13556,
                         label='Board Drain Loop', now=NOW)
        self.assertEqual(state['last_sync'], prior['last_sync'])
        self.assertEqual(state['watch_pid'], prior['watch_pid'])
        self.assertEqual(state['watch_started'], prior['watch_started'])

    def test_loop_interval_reads_plan_pick(self):
        with patch.object(loop, 'PLAN_PICK', SKILL / 'loop-state'), \
                patch.object(loop.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess(
                ['plan-pick', '--loop-interval'], 0, '14400 claude pace ahead', '')
            self.assertEqual(loop.loop_interval(), 14400)
        with patch.object(loop.subprocess, 'run', side_effect=OSError('missing')):
            self.assertEqual(loop.loop_interval(), loop.PACER_FLOOR)

    def test_a_dead_watcher_reads_watcher_dead(self):
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.record_watch('HT Test', dead_pid(), now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW),
                         (2, f'watcher dead since {iso(NOW)}'))

    def test_a_live_watcher_leaves_the_loop_armed(self):
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        state = loop.record_watch('HT Test', os.getpid(), now=NOW)
        self.assertEqual(state['watch_started'], iso(NOW))
        self.assertEqual(state['watch_beat'], iso(NOW))
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_an_exited_watcher_reads_dead_until_a_new_one_starts(self):
        """VSTA-151: the watcher exits, the chat never re-arms, and the loop read armed."""
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.record_watch('HT Test', os.getpid(), now=NOW)
        loop.clear_watch('HT Test')
        self.assertIsNone(loop.stored('HT Test')['watch_pid'])
        self.assertEqual(loop.status('HT Test', now=NOW + 60),
                         (2, f'watcher dead since {iso(NOW)}'))
        loop.record_watch('HT Test', os.getpid(), now=NOW + 120)
        self.assertEqual(loop.status('HT Test', now=NOW + 120)[0], 0)

    def test_a_hung_watcher_past_three_polls_reads_dead(self):
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.record_watch('HT Test', os.getpid(), now=NOW, every=180)
        self.assertEqual(loop.status('HT Test', now=NOW + 540)[0], 0)
        self.assertEqual(loop.status('HT Test', now=NOW + 541),
                         (2, f'watcher dead since {iso(NOW)}'))

    def test_a_live_watcher_without_beats_counts_as_alive_during_upgrade(self):
        """An old pre-upgrade watcher wrote watch_pid and watch_started, never watch_beat."""
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.store('HT Test', {'watch_pid': os.getpid(), 'watch_started': iso(NOW - 3600)})
        self.assertNotIn('watch_beat', loop.stored('HT Test'))
        self.assertEqual(loop.watch_health('HT Test', now=NOW), ('ok', 'watcher ok'))
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))
        loop.store('HT Test', {'watch_pid': dead_pid()})
        self.assertEqual(loop.watch_health('HT Test', now=NOW),
                         ('dead', f'watcher dead since {iso(NOW - 3600)}'))
        self.assertEqual(loop.status('HT Test', now=NOW),
                         (2, f'watcher dead since {iso(NOW - 3600)}'))

    def test_the_pulse_deadline_follows_the_poll_interval(self):
        self.assertEqual(loop.beat_limit({'watch_every': 60}), loop.BEAT_FLOOR)
        self.assertEqual(loop.beat_limit({'watch_every': 180}), 540)
        self.assertEqual(loop.beat_limit({}), 540)
        self.assertEqual(loop.beat_limit({'watch_every': 'broken'}), 540)

    def test_the_cli_watcher_verb_prints_one_line(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.directory))
        command = [sys.executable, str(SKILL / 'loop-state')]
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_watch('HT Test', os.getpid(), now=NOW, every=180)
        live = subprocess.run(command + ['watcher', '--name', 'HT Test'],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(live.returncode, 0, live.stderr)
        self.assertEqual(live.stdout.strip(), 'watcher ok')
        loop.record_watch('HT Test', dead_pid(), now=NOW - 3600, every=180)
        dead = subprocess.run(command + ['watcher', '--name', 'HT Test'],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(dead.returncode, 1, dead.stderr)
        self.assertEqual(dead.stdout.strip(), f'watcher dead since {iso(NOW - 3600)}')

    def test_an_old_watcher_cannot_clear_its_replacement(self):
        loop.arm('HT Test', now=NOW)
        loop.record_watch('HT Test', 101, now=NOW)
        replacement = loop.record_watch('HT Test', 202, now=NOW + 60)
        loop.clear_watch('HT Test', pid=101)
        self.assertEqual(loop.stored('HT Test'), replacement)
        loop.clear_watch('HT Test', pid=202)
        self.assertEqual(loop.stored('HT Test'), dict(replacement, watch_pid=None))

    def test_a_watcher_can_clear_its_own_pid(self):
        recorded = loop.record_watch('HT Test', 101, now=NOW)
        loop.clear_watch('HT Test', pid=101)
        self.assertEqual(loop.stored('HT Test'), dict(recorded, watch_pid=None))

    def test_no_watcher_recorded_behaves_as_today(self):
        loop.arm('HT Test', every='15m', job='cron-1', now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))
        loop.record_sync('HT Test', True, '', now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_a_file_with_no_sync_record_reads_none(self):
        loop.arm('HT Test', now=NOW)
        self.assertIsNone(loop.sync_state('HT Test'))
        self.assertIsNone(loop.sync_state('HT Never Armed'))

    def test_the_cli_exits_with_the_status_code(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.directory))
        command = [sys.executable, str(SKILL / 'loop-state')]
        armed = subprocess.run(command + ['arm', '--name', 'HT Test', '--every', '15m'],
                               capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(armed.returncode, 0, armed.stderr)
        self.assertIn('armed, expires in 7d0h', armed.stdout)
        status = subprocess.run(command + ['status', '--name', 'HT Test'],
                                capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertRegex(status.stdout, r'armed, expires in \d+d\d+h')
        cleared = subprocess.run(command + ['clear', '--name', 'HT Test'],
                                 capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        missing = subprocess.run(command + ['status', '--name', 'HT Test'],
                                 capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertEqual(missing.stdout.strip(), 'not armed')


class WatchTest(unittest.TestCase):
    """The watcher blocks on the chat's own view and exits the moment it changes."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fixture = self.directory / 'view.json'
        env = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.directory / 'state')})
        env.start()
        self.addCleanup(env.stop)

    def rows(self, rows):
        self.fixture.write_text(json.dumps(rows))

    def run_watch(self, rows, *extra, on_sleep=None, clock=None):
        self.rows(rows)
        clock = clock or Clock()
        clock.on_sleep = on_sleep
        argv = ['--board', '13556', '--label', 'Board Drain Loop', '--name', 'Watch Test',
                '--fixture', str(self.fixture), '--no-sync', *extra]
        out, err = io.StringIO(), io.StringIO()
        with patch.object(watch.drain.reconcile, 'worker_alive', return_value=False), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = watch.main(argv, clock=clock.time, sleep=clock.sleep)
        return code, out.getvalue() + err.getvalue(), clock

    def test_once_prints_the_snapshot_and_exits(self):
        rows = [vsta('VSTA-1', section='Doing', age=300), vsta('VSTA-2')]
        rows[1]['task']['waitingOnUserId'] = 6
        rows[1]['comments'] = [dict(human_comment(600), id=12)]
        code, out, _ = self.run_watch(rows, '--once')
        self.assertEqual(code, 0, out)
        snapshot = json.loads(out)
        self.assertEqual(snapshot['tickets']['VSTA-1']['column'], 'Doing')
        self.assertTrue(snapshot['tickets']['VSTA-1']['stalled'] is False)
        self.assertEqual(snapshot['tickets']['VSTA-2']['waiting'], [6, None])
        self.assertEqual(snapshot['tickets']['VSTA-2']['newest_comment'], 12)
        # The finding kinds are drain-check's own: no second verdict lived here.
        self.assertEqual(snapshot['findings'], ['answered', 'unassigned'])

    def test_a_new_ticket_wakes_the_chat(self):
        code, out, _ = self.run_watch(
            [vsta('VSTA-1', section='Doing', age=300)],
            on_sleep=lambda tick: tick >= 1 and self.rows(
                [vsta('VSTA-1', section='Doing', age=300), vsta('VSTA-80')]))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-80 new in Todo', out)

    def test_a_valentin_reply_on_a_waiting_ticket_wakes_the_chat(self):
        first = [dict(agent_comment(3600), id=11)]
        both = first + [dict(human_comment(600), id=12)]
        rows = [vsta('VSTA-12')]
        rows[0]['task']['waitingOnUserId'] = 6
        rows[0]['comments'] = first
        code, out, _ = self.run_watch(
            rows, on_sleep=lambda tick: tick >= 1 and self._mark_waiting(rows, both))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-12 Valentin replied', out)

    def test_a_dead_worker_wakes_the_chat(self):
        code, out, _ = self.run_watch(
            [vsta('VSTA-9', section='Doing', age=300),
             vsta('VSTA-1', section='Done')],
            on_sleep=lambda tick: tick >= 1 and self.rows(
                [vsta('VSTA-9', section='Doing', age=3 * 3600),
                 vsta('VSTA-1', section='Done')]))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-9 worker died', out)

    def test_a_column_move_wakes_the_chat(self):
        code, out, _ = self.run_watch(
            [vsta('VSTA-5', section='Doing', age=300)],
            on_sleep=lambda tick: tick >= 1 and self.rows(
                [vsta('VSTA-5', section='Done')]))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-5 Doing -> Done', out)

    def test_a_quiet_view_exits_on_the_heartbeat_before_the_harness_limit(self):
        with patch.object(watch.loop_state, 'loop_interval', return_value=loop.PACER_FLOOR):
            code, out, clock = self.run_watch([vsta('VSTA-1', section='Done')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), 'heartbeat: no change in 2h')
        self.assertEqual(clock.now - NOW, 7020)
        self.assertLess(clock.now - NOW, 7200)

    def test_the_default_heartbeat_follows_the_plan_pacer(self):
        """A 1h plan pace caps under 2h and sets the heartbeat one poll short of it."""
        paced = 3600 - 180
        with patch.object(watch.loop_state, 'loop_interval', return_value=3600):
            code, out, clock = self.run_watch([vsta('VSTA-1', section='Done')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), 'heartbeat: no change in 57m')
        self.assertEqual(clock.now - NOW, paced)

    def test_an_explicit_heartbeat_is_honoured(self):
        code, out, clock = self.run_watch([vsta('VSTA-1', section='Done')],
                                          '--heartbeat', '600')
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), 'heartbeat: no change in 10m')
        self.assertEqual(clock.now - NOW, 600)

    def test_one_api_failure_retries_on_the_next_poll(self):
        def on_sleep(tick):
            if tick == 1:
                self.fixture.write_text('{not json')
            elif tick == 2:
                self.rows([vsta('VSTA-80')])

        code, out, _ = self.run_watch([vsta('VSTA-1', section='Done')], on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        self.assertNotIn('FAIL', out)
        self.assertIn('changed: VSTA-80 new in Todo', out)

    def test_three_api_failures_in_a_row_exit_one(self):
        self.fixture.write_text('{not json')
        clock = Clock()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = watch.main(
                ['--board', '13556', '--label', 'Board Drain Loop', '--name', 'Watch Test',
                 '--fixture', str(self.fixture), '--no-sync'],
                clock=clock.time, sleep=clock.sleep)
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn('watch: FAIL', out.getvalue())
        self.assertEqual(clock.now - NOW, 2 * 180)  # three attempts, two waits between

    def test_the_watcher_records_and_clears_its_pid(self):
        seen = []

        def on_sleep(tick):
            state = json.loads((self.directory / 'state/watch-test.json').read_text())
            seen.append((state.get('watch_pid'), state.get('watch_started')))

        code, out, _ = self.run_watch([vsta('VSTA-1', section='Done')], on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        self.assertEqual(seen[0], (os.getpid(), iso(NOW)))
        state = json.loads((self.directory / 'state/watch-test.json').read_text())
        self.assertIsNone(state.get('watch_pid'))

    def test_the_watcher_leaves_a_replacement_pid_on_exit(self):
        replacement_pid = os.getpid() + 1

        def on_sleep(tick):
            watch.loop_state.record_watch('Watch Test', replacement_pid, now=NOW + 180)

        code, out, _ = self.run_watch([vsta('VSTA-1', section='Done')],
                                      '--heartbeat', '180', on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        state = json.loads((self.directory / 'state/watch-test.json').read_text())
        self.assertEqual(state['watch_pid'], replacement_pid)
        self.assertEqual(state['watch_started'], iso(NOW + 180))

    def test_the_watcher_pulses_on_every_poll(self):
        """VSTA-151: the pulse is the marker a dead watcher leaves behind."""
        beats = []

        def on_sleep(tick):
            state = json.loads((self.directory / 'state/watch-test.json').read_text())
            beats.append(state.get('watch_beat'))

        with patch.object(watch.loop_state, 'loop_interval', return_value=loop.PACER_FLOOR):
            code, out, _ = self.run_watch([vsta('VSTA-1', section='Done')], on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        self.assertEqual(beats[:3], [iso(NOW), iso(NOW + 180), iso(NOW + 360)])
        state = json.loads((self.directory / 'state/watch-test.json').read_text())
        self.assertEqual(state['watch_every'], 180)
        self.assertEqual(state['watch_beat'], iso(NOW + 7020))
        self.assertIsNone(state.get('watch_pid'))
        self.assertEqual(loop.watch_health('Watch Test', now=NOW + 7020),
                         ('dead', f'watcher dead since {iso(NOW + 7020)}'))

    def test_the_cli_records_the_watcher_pid(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.directory / 'state'))
        done = subprocess.run([sys.executable, str(SKILL / 'loop-state'), 'watch',
                               '--name', 'Watch Test', '--pid', str(os.getpid())],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        state = json.loads((self.directory / 'state/watch-test.json').read_text())
        self.assertEqual(state['watch_pid'], os.getpid())

    def _mark_waiting(self, rows, comments):
        rows[0]['comments'] = comments
        self.rows(rows)


class WatchSyncTest(unittest.TestCase):
    """The watcher runs the chat's own sync, so a merged PR's card still moves."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fixture = self.directory / 'view.json'
        self.rows([vsta('VSTA-1', section='Done')])
        env = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.directory / 'state')})
        env.start()
        self.addCleanup(env.stop)

    def rows(self, rows):
        self.fixture.write_text(json.dumps(rows))

    def run_watch(self, *extra, syncs=None, on_sync=None):
        """syncs: one (exit code, reason) per sync call, in order; extra calls succeed."""
        queue, calls, clock = list(syncs or []), [], Clock()

        def fake_sync(argv):
            calls.append({'argv': list(argv), 'at': clock.now - NOW})
            code, reason = queue.pop(0) if queue else (0, '')
            loop.record_sync('Watch Test', not code, reason, now=clock.now)
            if on_sync:
                on_sync(clock.now - NOW)
            return code

        out = io.StringIO()
        with patch.object(watch.loop_state, 'arm_timer'), \
                patch.object(watch.sync, 'main', side_effect=fake_sync), \
                patch.object(watch.drain.reconcile, 'worker_alive', return_value=False), \
                contextlib.redirect_stdout(out):
            code = watch.main(['--board', '13556', '--label', 'Board Drain Loop',
                               '--name', 'Watch Test', '--fixture', str(self.fixture), *extra],
                              clock=clock.time, sleep=clock.sleep)
        return code, out.getvalue(), calls

    def test_the_watcher_calls_the_sync_scripts_own_code(self):
        self.assertEqual(Path(watch.sync.__file__).resolve(), (SKILL / 'sync').resolve())

    def test_the_sync_runs_at_start_and_every_sync_every_seconds(self):
        code, out, calls = self.run_watch('--every', '60', '--heartbeat', '240',
                                          '--sync-every', '120')
        self.assertEqual(code, 0, out)
        self.assertEqual([call['at'] for call in calls], [0, 120, 240])

    def test_the_default_sync_runs_every_fifteen_minutes(self):
        code, out, calls = self.run_watch('--every', '60', '--heartbeat', '1800')
        self.assertEqual(code, 0, out)
        self.assertEqual([call['at'] for call in calls], [0, 900, 1800])

    def test_no_sync_never_runs_it(self):
        code, out, calls = self.run_watch('--every', '60', '--heartbeat', '240', '--no-sync')
        self.assertEqual(code, 0, out)
        self.assertEqual(calls, [])

    def test_once_never_syncs(self):
        code, out, calls = self.run_watch('--once')
        self.assertEqual(code, 0, out)
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(out)['tickets']['VSTA-1']['column'], 'Done')

    def test_the_sync_runs_as_this_chat(self):
        _code, out, calls = self.run_watch('--every', '60', '--heartbeat', '60',
                                           '--sync-every', '600')
        self.assertEqual(calls[0]['argv'], ['--board', '13556', '--label', 'Board Drain Loop',
                                            '--name', 'Watch Test'], out)

    def test_a_failed_sync_wakes_the_chat_at_once(self):
        code, out, calls = self.run_watch(
            '--every', '60', '--heartbeat', '600',
            syncs=[(1, 'board 13556 unreachable')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), 'changed: sync failed: board 13556 unreachable')
        self.assertEqual(len(calls), 1, out)

    def test_a_sync_that_moved_a_card_wakes_the_chat_on_the_next_snapshot(self):
        def move(tick):
            if tick:
                self.rows([vsta('VSTA-1', section='Done'), vsta('VSTA-80')])

        code, out, calls = self.run_watch('--every', '60', '--heartbeat', '600',
                                          '--sync-every', '120', on_sync=move)
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-80 new in Todo', out)
        self.assertEqual([call['at'] for call in calls], [0, 120])

    def test_a_failed_sync_records_the_failure_for_drain_check(self):
        _code, _out, _calls = self.run_watch('--every', '60', '--heartbeat', '600',
                                             syncs=[(1, 'preview printed: usage')])
        record = loop.sync_state('Watch Test')
        self.assertFalse(record['ok'])
        self.assertEqual(record['reason'], 'preview printed: usage')


class RelationsCliTest(unittest.TestCase):
    """The real CLI answers `task relations`: one read per unmarked Todo ticket."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.real_bin = self.directory / 'home/.local/bin'
        self.real_bin.mkdir(parents=True)
        self.real_log = self.directory / 'real.log'
        self.real_log.write_text('')
        task = {'projectId': 13556, 'labels': [{'name': 'Board Drain Loop'}],
                'status': 'Normal', 'assignees': [], 'waitingOnUserId': None,
                'blockerCommentId': None, 'updatedAt': iso(NOW - 300)}
        tasks = [dict(task, ticketNumber='VSTA-7', section='Todo'),
                 dict(task, ticketNumber='VSTA-8', section='Todo', waitingOnUserId=6),
                 dict(task, ticketNumber='VSTA-2', section='Doing',
                      assignees=[agent_assignee('Board Drain Loop')])]
        answers = {'task list': {'tasks': tasks, 'total': len(tasks)},
                   'comment list': {'comments': []},
                   'task relations': {'success': True, 'relations': blocked_by()},
                   'project show': {'project': {'uniqueIdentifier': 'VSTA', 'sections': [
                       {'section_title': 'Todo'}, {'section_title': 'Doing'}]}}}
        write_tool(self.real_bin / 'hypertask',
                   'import json, os, pathlib, sys\n'
                   'log = pathlib.Path(os.environ["REAL_HYPERTASK_LOG"])\n'
                   'log.write_text(log.read_text() + " ".join(sys.argv[1:]) + "\\n")\n'
                   f'answers = {answers!r}\n'
                   'args = [a for a in sys.argv[1:] if a != "--json"]\n'
                   'print(json.dumps(answers.get(" ".join(args[:2]), {"tasks": [], "total": 0})))\n')

    def test_links_come_from_the_cli_once_per_unmarked_todo(self):
        done = subprocess.run(
            [sys.executable, str(SKILL / 'drain-check'), '--board', '13556',
             '--label', 'Board Drain Loop', '--now', iso(NOW)],
            capture_output=True, text=True, timeout=60,
            env={'HOME': str(self.directory / 'home'), 'PATH': '/usr/bin:/bin',
                 'REAL_HYPERTASK_LOG': str(self.real_log),
                 'BOARD_DRAIN_STATE_DIR': str(self.directory / 'state'),
                 'RECONCILE_CACHE': str(self.directory / 'cache.json')})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('blocked: VSTA-7 by VSTA-2, VSTA-3', done.stdout)
        self.assertIn('waiting: VSTA-8 (marked)', done.stdout)
        self.assertIn('drain-check: PASS', done.stdout)
        reads = [line for line in self.real_log.read_text().splitlines()
                 if 'task relations' in line]
        self.assertEqual(reads, ['--json task relations VSTA-7'])


class SyncTest(unittest.TestCase):
    """The sync steps reconcile runs as this chat's own login, without the network."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.creds = self.directory / 'credentials'
        self.creds.mkdir()
        self.states = self.directory / 'state'
        env = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.states),
                                      'BOARD_DRAIN_CRED_DIR': str(self.creds),
                                      'HT_TOKEN': '', 'SHIP_SESSION_NAME': ''})
        env.start()
        self.addCleanup(env.stop)

    def run_sync(self, answers, *extra, name='HT Test'):
        """answers: one (returncode, stdout, stderr) per reconcile call, in order."""
        queued, calls = list(answers), []

        def fake(argv, **kwargs):
            calls.append({'argv': argv, **kwargs})
            return subprocess.CompletedProcess(argv, *queued.pop(0))

        out, err = io.StringIO(), io.StringIO()
        with patch.object(sync.subprocess, 'run', side_effect=fake), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.main(['--board', '2060', '--label', 'Poteto', '--name', name, *extra])
        return code, out.getvalue() + err.getvalue(), calls

    def write_token(self, text='tok-from-file', name='HT Test'):
        (self.creds / (loop.slug(name) + '-agent-token')).write_text(text + '\n')

    def test_a_usage_error_fails_and_records_it(self):
        self.write_token()
        code, out, calls = self.run_sync([(2, '', 'usage: --apply requires SHIP_SESSION_NAME\n')])
        self.assertEqual(code, 1, out)
        self.assertIn('sync: FAIL', out)
        self.assertIn('usage:', out)
        self.assertEqual(len(calls), 1, out)  # no apply after a broken preview
        record = loop.sync_state('HT Test')
        self.assertIsNotNone(record)
        self.assertFalse(record['ok'])
        self.assertIn('usage:', record['reason'])
        self.assertEqual(loop.status('HT Test'), (2, 'not armed'))

    def test_an_error_in_the_output_fails_even_on_a_zero_exit(self):
        self.write_token()
        code, out, _ = self.run_sync([(0, 'reconcile: API error: 500\n', '')])
        self.assertEqual(code, 1, out)
        self.assertIn('sync: FAIL', out)
        self.assertFalse(loop.sync_state('HT Test')['ok'])

    def test_a_non_zero_exit_fails(self):
        self.write_token()
        code, out, _ = self.run_sync([(1, '', 'board 2060 unreachable\n')])
        self.assertEqual(code, 1, out)
        self.assertIn('sync: FAIL', out)
        self.assertIn('board 2060 unreachable', out)
        self.assertFalse(loop.sync_state('HT Test')['ok'])

    def test_a_clean_preview_then_apply_succeeds(self):
        self.write_token()
        code, out, calls = self.run_sync([(0, 'preview: 2 moves\n', ''),
                                          (0, 'applied: 2 moves\n', '')])
        self.assertEqual(code, 0, out)
        self.assertIn('preview: 2 moves', out)
        self.assertIn('applied: 2 moves', out)
        self.assertEqual(out.strip().splitlines()[-1], 'sync: ok')
        self.assertEqual(len(calls), 2)
        self.assertNotIn('--apply', calls[0]['argv'])
        self.assertIn('--apply', calls[1]['argv'])
        self.assertEqual(calls[1]['argv'][calls[1]['argv'].index('--limit') + 1], '5')
        self.assertEqual(loop.sync_state('HT Test')['ok'], True)

    def test_the_token_comes_from_the_session_credentials(self):
        self.write_token()
        code, out, calls = self.run_sync([(0, 'ok\n', ''), (0, 'ok\n', '')])
        self.assertEqual(code, 0, out)
        for call in calls:
            self.assertEqual(call['env']['HT_TOKEN'], 'tok-from-file')
            self.assertEqual(call['env']['SHIP_SESSION_NAME'], 'HT Test')

    def test_an_existing_token_and_session_name_are_kept(self):
        with patch.dict(os.environ, {'HT_TOKEN': 'from-env', 'SHIP_SESSION_NAME': 'other-chat'}):
            code, out, calls = self.run_sync([(0, 'ok\n', ''), (0, 'ok\n', '')])
        self.assertEqual(code, 0, out)
        self.assertEqual(calls[0]['env']['HT_TOKEN'], 'from-env')
        self.assertEqual(calls[0]['env']['SHIP_SESSION_NAME'], 'other-chat')

    def test_no_token_anywhere_fails(self):
        code, out, calls = self.run_sync([])
        self.assertEqual(code, 1, out)
        self.assertIn('sync: FAIL', out)
        self.assertIn('HT_TOKEN', out)
        self.assertEqual(calls, [])
        self.assertFalse(loop.sync_state('HT Test')['ok'])

    def test_the_cli_runs_and_refuses_without_a_token(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.states),
                   BOARD_DRAIN_CRED_DIR=str(self.creds), HT_TOKEN='', SHIP_SESSION_NAME='')
        done = subprocess.run([sys.executable, str(SKILL / 'sync'), '--board', '2060',
                               '--label', 'Poteto', '--name', 'HT Test'],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn('sync: FAIL', done.stdout)


if __name__ == '__main__':
    unittest.main()
