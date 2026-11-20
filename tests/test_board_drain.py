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


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


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


def doing(key, age=300, section='Doing'):
    task = {'ticketNumber': key, 'projectId': 2060, 'section': section,
            'labels': [{'name': 'Poteto'}], 'waitingOnUserId': None,
            'blockerCommentId': None, 'updatedAt': iso(NOW - age)}
    return {'task': task, 'comments': []}


def agent_comment(age):
    return {'createdAt': iso(NOW - age), 'creatorId': 6, 'agent': {'id': 'a'},
            'agent_display_name': 'Poteto', 'text': 'working it'}


def human_comment(age):
    return {'createdAt': iso(NOW - age), 'creatorId': 6,
            'creator': {'id': 6, 'displayName': 'Valentin Yeo'}, 'text': 'yes, go'}


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        env = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.directory)})
        env.start()
        self.addCleanup(env.stop)

    def run_check(self, rows, *extra, alive=False):
        fixture = self.directory / 'fixture.json'
        fixture.write_text(json.dumps(rows))
        argv = ['--board', '2060', '--label', 'Poteto', '--fixture', str(fixture),
                '--now', iso(NOW), *extra]
        out = io.StringIO()
        with patch.object(drain.reconcile, 'worker_alive', return_value=alive), \
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

    def test_a_missing_loop_state_fails_when_named(self):
        code, out = self.run_check([todo('SOFT-2908', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('loop state: not armed', out)

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

    def test_a_usage_error_exits_two(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as raised:
            drain.main(['--board', '0', '--label', 'Poteto'])
        self.assertEqual(raised.exception.code, 2)


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
