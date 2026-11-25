#!/usr/bin/env python3
"""A merge reaches every server without anyone running a command (VSTA-314).

2026-11-25: nothing updated the shared checkout after a merge, so Hetzner lagged
Contabo by two merges until a chat ran git fetch, checkout --detach origin/main and
./install by hand. These tests build the real shape: a bare origin, a clone at
~/.local/share/vstack, and the timer's script changing that clone.

Self-update tests: tests/test_self_update.py
"""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / 'install'
TIMEOUT = 120
GIT_ENV = {
    'GIT_AUTHOR_NAME': 'Self Update Test', 'GIT_AUTHOR_EMAIL': 'test@example.com',
    'GIT_COMMITTER_NAME': 'Self Update Test', 'GIT_COMMITTER_EMAIL': 'test@example.com',
    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
    'GIT_TERMINAL_PROMPT': '0',
}
INSTALLER = '#!/bin/sh\nprintf \'called\\n\' >> "$HOME/install-calls"\n'


class SelfUpdateTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.temp = Path(holder.name)
        self.home = self.temp / 'home'
        self.share = self.home / '.local/share/vstack'
        self.origin = self.temp / 'origin.git'
        self.seed = self.temp / 'seed'
        self.log = self.home / '.local/state/vstack/self-update.log'
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ('VSTACK_DIR', 'VSTACK_LOCK_HELD', 'XDG_CONFIG_HOME',
                                   'XDG_STATE_HOME')}
        self.env.update(GIT_ENV)
        self.env['HOME'] = str(self.home)
        self.home.mkdir()
        self.seed_repository()

    def git(self, directory, *args):
        return subprocess.run(['git', '-C', str(directory), *args], env=self.env, check=True,
                              capture_output=True, text=True, timeout=TIMEOUT).stdout.strip()

    def seed_repository(self):
        self.seed.mkdir()
        self.git(self.seed, 'init', '-q', '-b', 'main')
        (self.seed / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/vstack-self-update', self.seed / 'scripts')
        (self.seed / 'README.md').write_text('one\n')
        self.git(self.seed, 'add', '-A')
        self.git(self.seed, 'commit', '-q', '-m', 'first')
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(self.origin)],
                       env=self.env, check=True, capture_output=True, timeout=TIMEOUT)
        self.git(self.seed, 'remote', 'add', 'origin', str(self.origin))
        self.git(self.seed, 'push', '-q', 'origin', 'main')
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(self.share)],
                       env=self.env, check=True, capture_output=True, timeout=TIMEOUT)

    def publish(self, message, files):
        for name, text in files.items():
            path = self.seed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            path.chmod(0o755)
        self.git(self.seed, 'add', '-A')
        self.git(self.seed, 'commit', '-q', '-m', message)
        self.git(self.seed, 'push', '-q', 'origin', 'main')
        return self.git(self.seed, 'rev-parse', 'HEAD')

    def run_self_update(self, *args, directory=None, env=None):
        command = [sys.executable, str((directory or self.share) / 'scripts/vstack-self-update'), *args]
        return subprocess.run(command, cwd=str(directory or self.share), timeout=TIMEOUT,
                              capture_output=True, text=True, env={**self.env, **(env or {})})

    def lines(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_a_current_checkout_is_a_silent_no_op(self):
        before = self.git(self.share, 'rev-parse', 'HEAD')

        result = self.run_self_update()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.git(self.share, 'rev-parse', 'HEAD'), before)
        self.assertEqual(self.lines(), [])
        self.assertFalse((self.home / 'install-calls').exists())

    def test_a_new_commit_is_checked_out_and_installed(self):
        before = self.git(self.share, 'rev-parse', 'HEAD')
        after = self.publish('install stub', {'install': INSTALLER})

        result = self.run_self_update()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.share, 'rev-parse', 'HEAD'), after)
        self.assertEqual(self.git(self.share, 'rev-parse', '--abbrev-ref', 'HEAD'), 'HEAD')
        self.assertEqual((self.home / 'install-calls').read_text(), 'called\n')
        self.assertEqual(len(self.lines()), 1, self.lines())
        self.assertIn(before[:10], self.lines()[0])
        self.assertIn(after[:10], self.lines()[0])
        self.assertIn('ok', self.lines()[0])

    def test_local_changes_are_refused_with_one_log_line(self):
        before = self.git(self.share, 'rev-parse', 'HEAD')
        after = self.publish('install stub', {'install': INSTALLER})
        (self.share / 'README.md').write_text('hand edited\n')

        result = self.run_self_update()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.share, 'rev-parse', 'HEAD'), before)
        self.assertNotEqual(before, after)
        self.assertEqual(len(self.lines()), 1, self.lines())
        self.assertIn('local changes', self.lines()[0])
        self.assertFalse((self.home / 'install-calls').exists())

    def test_a_held_lock_skips_the_run(self):
        after = self.publish('install stub', {'install': INSTALLER})
        lock = self.home / '.local/state/vstack/self-update.lock'
        lock.parent.mkdir(parents=True)
        with lock.open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)

            result = self.run_self_update()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.git(self.share, 'rev-parse', 'HEAD'), after)
        self.assertEqual(self.lines(), [])
        self.assertFalse((self.home / 'install-calls').exists())

    def test_a_failing_install_is_logged_and_left_alone(self):
        after = self.publish('broken install', {'install': '#!/bin/sh\nexit 3\n'})

        result = self.run_self_update()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.share, 'rev-parse', 'HEAD'), after)
        self.assertEqual(len(self.lines()), 1, self.lines())
        self.assertIn('fail', self.lines()[0])
        self.assertIn(after[:10], self.lines()[0])

    def test_it_refuses_a_checkout_that_is_not_the_shared_one(self):
        loose = self.temp / 'loose'
        (loose / 'scripts').mkdir(parents=True)
        shutil.copy2(ROOT / 'scripts/vstack-self-update', loose / 'scripts')

        result = self.run_self_update(directory=loose)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('shared checkout', result.stderr)
        self.assertEqual(self.lines(), [])

    def test_install_takes_the_same_lock(self):
        lock = self.home / '.local/state/vstack/self-update.lock'
        lock.parent.mkdir(parents=True)
        with lock.open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)

            result = subprocess.run(
                ['bash', str(INSTALL)], timeout=TIMEOUT, capture_output=True, text=True,
                env={**self.env, 'VSTACK_INSTALL_ANYWHERE': '1', 'VSTACK_DIR': str(self.share)})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already running', result.stderr)
        self.assertFalse((self.home / '.claude').exists())

    def units(self):
        return Path(self.config) / 'systemd/user'

    def test_units_are_written_once_and_name_the_shared_checkout(self):
        self.config = self.temp / 'config'
        env = {'XDG_CONFIG_HOME': str(self.config)}

        for _ in range(2):
            result = self.run_self_update('--write-units', '--dir', str(self.share),
                                          '--no-enable', env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
        service = self.units() / 'vstack-update.service'
        timer = self.units() / 'vstack-update.timer'
        first = (service.read_text(), timer.read_text())
        self.run_self_update('--write-units', '--dir', str(self.share), '--no-enable', env=env)
        self.assertEqual((service.read_text(), timer.read_text()), first)
        self.assertIn(str(self.share / 'scripts/vstack-self-update'), first[0])
        for text in first:
            for line in text.splitlines():
                self.assertTrue(line.startswith('[') and line.endswith(']') or '=' in line or not line,
                                line)
        self.assertTrue(first[0].startswith('[Unit]\n'), first[0])
        self.assertIn('\nType=oneshot\n', first[0])
        self.assertIn('\nEnvironment="VSTACK_DIR=', first[0])
        self.assertIn('\nExecStart="/usr/bin/timeout"', first[0])
        self.assertIn('Type=oneshot', first[0])
        self.assertIn('OnUnitActiveSec=15min', first[1])
        self.assertIn('Persistent=true', first[1])
        self.assertIn('RandomizedDelaySec=60s', first[1])
        self.assertIn('Unit=vstack-update.service', first[1])
        self.assertIn('WantedBy=timers.target', first[1])

    def test_enabling_needs_systemd_and_uses_the_user_bus(self):
        self.config = self.temp / 'config'
        binary = self.temp / 'bin'
        binary.mkdir()
        calls = self.temp / 'calls.jsonl'
        (binary / 'systemctl').write_text(
            '#!/usr/bin/env python3\n'
            'import json, os, sys\n'
            'args = sys.argv[1:]\n'
            'with open(os.environ["FAKE_SYSTEMCTL_CALLS"], "a") as out:\n'
            '    out.write(json.dumps({"argv": args, "bus": os.environ.get("DBUS_SESSION_BUS_ADDRESS")}) + "\\n")\n'
            'sys.exit(0 if args[1:2] == ["is-enabled"] and os.environ.get("FAKE_ENABLED") else 1)\n')
        (binary / 'systemctl').chmod(0o755)
        env = {'XDG_CONFIG_HOME': str(self.config), 'PATH': str(binary) + os.pathsep + self.env['PATH'],
               'FAKE_SYSTEMCTL_CALLS': str(calls)}

        result = self.run_self_update('--write-units', '--dir', str(self.share), env=env)

        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(row)['argv'] for row in calls.read_text().splitlines()]
        self.assertIn(['--user', 'daemon-reload'], rows)
        self.assertEqual([argv for argv in rows if 'enable' in argv],
                         [['--user', 'enable', '--now', 'vstack-update.timer']])
        self.assertTrue(all(argv[0] == '--user' for argv in rows), rows)
        buses = [json.loads(row)['bus'] for row in calls.read_text().splitlines()]
        self.assertTrue(all(buses), buses)

        env['FAKE_ENABLED'] = '1'
        calls.unlink()
        self.run_self_update('--write-units', '--dir', str(self.share), env=env)
        rows = [json.loads(row) for row in calls.read_text().splitlines()]
        self.assertEqual([row['argv'] for row in rows if 'enable' in row['argv']], [], rows)


if __name__ == '__main__':
    unittest.main()
