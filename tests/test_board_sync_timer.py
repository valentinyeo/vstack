import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from test_board_drain import Clock, NOW, SKILL, drain, loop, sync, watch


class SyncTimerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.units = self.root / 'systemd/user'
        self.states = self.root / 'state'
        self.calls = self.root / 'calls.jsonl'
        self.enabled = self.root / 'enabled.json'
        binary = self.root / 'bin'
        binary.mkdir()
        systemctl = binary / 'systemctl'
        systemctl.write_text(r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['FAKE_SYSTEMCTL_CALLS'], 'a') as out:
    out.write(json.dumps({'argv': args, 'bus': os.environ.get('DBUS_SESSION_BUS_ADDRESS'),
                          'runtime': os.environ.get('XDG_RUNTIME_DIR')}) + '\n')
path = Path(os.environ['FAKE_SYSTEMCTL_ENABLED'])
enabled = set(json.loads(path.read_text())) if path.exists() else set()
if os.environ.get('FAKE_SYSTEMCTL_FAIL') == args[1]:
    sys.exit(1)
if args[1] == 'enable':
    enabled.add(args[-1])
elif args[1] == 'disable':
    enabled.discard(args[-1])
elif args[1] == 'is-enabled':
    sys.exit(0 if args[-1] in enabled else 1)
path.write_text(json.dumps(sorted(enabled)))
""")
        systemctl.chmod(0o755)
        env = patch.dict(os.environ, {
            'PATH': str(binary) + os.pathsep + os.environ['PATH'],
            'XDG_CONFIG_HOME': str(self.root),
            'BOARD_DRAIN_STATE_DIR': str(self.states),
            'BOARD_DRAIN_CRED_DIR': str(self.root / 'credentials'),
            'FAKE_SYSTEMCTL_CALLS': str(self.calls),
            'FAKE_SYSTEMCTL_ENABLED': str(self.enabled),
            'HT_TOKEN': 'another-chat-token', 'SHIP_SESSION_NAME': 'Another Chat',
        })
        env.start()
        self.addCleanup(env.stop)

    def arm(self, name='Timer Test', board='42', label='Own View'):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = loop.main(['timer', '--name', name, '--board', board, '--label', label])
        self.assertEqual(code, 0, out.getvalue())

    def commands(self):
        return [json.loads(row)['argv'] for row in self.calls.read_text().splitlines()]

    def test_arm_creates_and_enables_only_own_units_idempotently(self):
        self.arm()
        first = {p.name: (p.read_text(), p.stat().st_mtime_ns) for p in self.units.iterdir()}
        self.arm()
        second = {p.name: (p.read_text(), p.stat().st_mtime_ns) for p in self.units.iterdir()}
        self.assertEqual(first, second)
        self.assertEqual(set(first), {'board-sync@timer-test.timer', 'board-sync@timer-test.service'})
        timer = first['board-sync@timer-test.timer'][0]
        self.assertIn('OnUnitActiveSec=15min', timer)
        self.assertIn('RandomizedDelaySec=3min', timer)
        self.assertIn('WantedBy=timers.target', timer)
        self.assertEqual(json.loads(self.enabled.read_text()), ['board-sync@timer-test.timer'])
        self.assertEqual(loop.stored('Timer Test')['sync_timer'], 'board-sync@timer-test.timer')
        self.assertEqual(self.commands().count(['--user', 'daemon-reload']), 2)
        for row in map(json.loads, self.calls.read_text().splitlines()):
            self.assertEqual(row['runtime'], f'/run/user/{os.getuid()}')
            self.assertEqual(row['bus'], f'unix:path=/run/user/{os.getuid()}/bus')

    def test_rearm_updates_board_and_label_without_touching_other_units(self):
        self.arm('Other Test', '99', 'Other View')
        other = {p.name: p.read_bytes() for p in self.units.glob('*other-test*')}
        self.arm()
        self.arm(board='43', label='Updated View')
        service = (self.units / 'board-sync@timer-test.service').read_text()
        self.assertIn('"--board" "43" "--label" "Updated View"', service)
        self.assertEqual(other, {p.name: p.read_bytes() for p in self.units.glob('*other-test*')})

    def test_service_uses_only_this_chats_token_file(self):
        self.arm()
        service = (self.units / 'board-sync@timer-test.service').read_text()
        self.assertIn('"600"', service)
        self.assertIn('"--name" "Timer Test" "--own-token"', service)
        self.assertIn('DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/', service)
        self.assertNotIn('another-chat-token', service)
        self.assertNotIn('Another Chat', service)
        self.assertIn('BOARD_DRAIN_CRED_DIR=' + str(self.root / 'credentials'), service)
        sync.token_path('Timer Test').parent.mkdir(parents=True)
        sync.token_path('Timer Test').write_text('own-fixture-token')
        calls = []

        def reconcile(argv, **kwargs):
            calls.append(kwargs['env'])
            return subprocess.CompletedProcess(argv, 0, '', '')

        with patch.object(sync.subprocess, 'run', side_effect=reconcile), contextlib.redirect_stdout(io.StringIO()):
            code = sync.main(['--board', '42', '--label', 'Own View', '--name', 'Timer Test', '--own-token'])
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        for env in calls:
            self.assertEqual(env['HT_TOKEN'], 'own-fixture-token')
            self.assertEqual(env['SHIP_SESSION_NAME'], 'Timer Test')
        sync.token_path('Timer Test').unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.main(['--board', '42', '--label', 'Own View', '--name', 'Timer Test', '--own-token']), 1)

    def test_prunes_only_stale_recorded_timer(self):
        self.arm('Old Test')
        old = loop.state_path('Old Test')
        stale = time.time() - 8 * 86400
        os.utime(old, (stale, stale))
        self.arm('Recent Test')
        enabled = json.loads(self.enabled.read_text())
        self.assertNotIn('board-sync@old-test.timer', enabled)
        self.assertIn('board-sync@recent-test.timer', enabled)
        self.assertIn(['--user', 'disable', '--now', 'board-sync@old-test.timer'], self.commands())
        self.assertFalse(any('recent-test' in ' '.join(c) and 'disable' in c for c in self.commands()))

    def test_scheduled_sync_cannot_keep_abandoned_chat_alive(self):
        self.arm('Old Test')
        state = loop.stored('Old Test')
        state['sync_timer_armed_at'] = loop.iso(NOW - 8 * 86400)
        loop.store('Old Test', state)
        loop.record_sync('Old Test', True, '', now=NOW)
        with patch.object(loop.time, 'time', return_value=NOW):
            self.arm()
        self.assertNotIn('board-sync@old-test.timer', json.loads(self.enabled.read_text()))

    def test_drain_check_reports_missing_timer_and_recovers_when_enabled(self):
        fixture = self.root / 'view.json'
        fixture.write_text(json.dumps({'rows': [], 'roster': ''}))
        loop.arm('Timer Test', now=NOW)
        loop.record_sync('Timer Test', True, '', now=NOW)
        argv = ['--board', '42', '--label', 'Own View', '--state-name', 'Timer Test',
                '--fixture', str(fixture), '--now', loop.iso(NOW), '--no-load']
        for armed in (False, True):
            if armed:
                self.arm()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = drain.main(argv)
            self.assertEqual(code, 0 if armed else 1, out.getvalue())
            self.assertEqual('sync timer off' in out.getvalue(), not armed)
        self.enabled.write_text('[]')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(drain.main(argv), 1)
        self.assertIn('sync timer off', out.getvalue())

    def test_watcher_arms_timer_that_survives_its_exit(self):
        fixture = self.root / 'view.json'
        fixture.write_text(json.dumps({'rows': [], 'roster': ''}))
        clock = Clock()
        with patch.object(watch.sync, 'main', return_value=0), \
                patch.object(watch, 'wake', return_value=False), \
                contextlib.redirect_stdout(io.StringIO()):
            code = watch.main(['--board', '42', '--label', 'Own View', '--name', 'Timer Test',
                               '--fixture', str(fixture), '--heartbeat', '1', '--cycles', '1'],
                              clock=clock.time, sleep=clock.sleep)
        self.assertEqual(code, 0)
        self.assertIsNone(loop.stored('Timer Test')['watch_pid'])
        self.assertIn('board-sync@timer-test.timer', json.loads(self.enabled.read_text()))

    def test_failed_enable_does_not_record_a_successful_arm(self):
        with patch.dict(os.environ, {'FAKE_SYSTEMCTL_FAIL': 'enable'}), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(loop.main(['timer', '--name', 'Timer Test', '--board', '42', '--label', 'Own View']), 2)
        self.assertNotIn('sync_timer', loop.stored('Timer Test'))

    def test_loop_rearm_preserves_timer_record(self):
        self.arm()
        loop.arm('Timer Test', now=NOW)
        self.assertEqual(loop.stored('Timer Test')['sync_timer'], 'board-sync@timer-test.timer')

    def test_arm_recovers_after_a_failed_reload(self):
        with patch.dict(os.environ, {'FAKE_SYSTEMCTL_FAIL': 'daemon-reload'}), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(loop.main(['timer', '--name', 'Timer Test', '--board', '42', '--label', 'Own View']), 2)
        self.arm()
        self.assertIn('board-sync@timer-test.timer', json.loads(self.enabled.read_text()))

    def test_broken_or_unrelated_records_never_disable_another_unit(self):
        self.states.mkdir()
        (self.states / 'broken.json').write_text('{')
        (self.states / 'list.json').write_text('[]')
        (self.states / 'wrong.json').write_text(json.dumps({
            'name': 'Other Test', 'sync_timer': 'unrelated.timer',
            'sync_timer_armed_at': loop.iso(NOW - 8 * 86400)}))
        self.arm()
        self.assertFalse(any('disable' in c for c in self.commands()))

    def test_state_writes_keep_changes_from_the_other_writer(self):
        self.arm()
        loop.record_watch('Timer Test', os.getpid(), now=NOW)
        loop.record_sync('Timer Test', True, '', now=NOW)
        loop.clear_watch('Timer Test')
        state = loop.stored('Timer Test')
        self.assertEqual(state['sync_timer'], 'board-sync@timer-test.timer')
        self.assertTrue(state['last_sync']['ok'])
        self.assertIsNone(state['watch_pid'])
