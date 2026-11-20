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

    def test_a_missing_loop_state_fails_when_named(self):
        code, out = self.run_check([todo('SOFT-2908', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('loop state: not armed', out)

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


if __name__ == '__main__':
    unittest.main()
