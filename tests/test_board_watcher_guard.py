#!/usr/bin/env python3
"""A dead board watcher wakes its own chat (VSTA-151).

2026-11-23: in Multi Bot Bugs and Multi Bot Features the background watcher had died and
nothing woke them; board 13734 drifted to 89 tickets in AI Review. The state files these
tests write are that shape: a live chat, an armed loop, and a watcher whose last pulse is
hours old. The hook reads them as this chat's own and says re-arm.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/board-drain-guard.py'
SETTINGS = ROOT / '.claude/settings.json'
NOW = 1800000000
TAB = 'live-guard'


def load_hook():
    name = 'board_drain_guard'
    loader = importlib.machinery.SourceFileLoader(name, str(HOOK))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def iso(seconds):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(seconds))


def dead_pid():
    """The pid of a process that has already exited."""
    process = subprocess.Popen([sys.executable, '-c', 'pass'])
    process.wait()
    return process.pid


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.state = self.home / '.local/state/board-drain'
        self.state.mkdir(parents=True)
        announce = self.home / '.local/state/roster/announce'
        announce.mkdir(parents=True)
        (announce / f'{TAB}.json').write_text(json.dumps({
            'tmux': TAB, 'multibot': 'Multi Bot Bugs', 'sid': 'sid-bugs'}))
        (announce / 'live-features.json').write_text(json.dumps({
            'tmux': 'live-features', 'multibot': 'Multi Bot Features', 'sid': 'sid-features'}))
        # All three tab keys are set, so an ambient one in the test runner never wins.
        self.env = {'HOME': str(self.home), 'MULTIBOT_SESSION': TAB,
                    'ZSB_SESSION': TAB, 'MULTIPROMPT_TAB': TAB,
                    'BOARD_DRAIN_STATE_DIR': str(self.state)}
        patched = patch.dict(os.environ, self.env)
        patched.start()
        self.addCleanup(patched.stop)
        self.hook = load_hook()

    def write_state(self, name='Multi Bot Bugs', beat_hours_ago=3, watch_pid=None,
                    owner_pid=None, board=13734, label='Multi Bot Bugs', now=NOW):
        """The record a chat leaves: armed, and its watcher last seen `beat_hours_ago`."""
        beat = iso(now - int(beat_hours_ago * 3600))
        record = {
            'name': name, 'every': '6h', 'armed_at': iso(now - 86400),
            'expires_at': iso(now + 6 * 86400), 'job': 'efcdac5d',
            'owner_pid': os.getpid() if owner_pid is None else owner_pid,
            'host': socket.gethostname(), 'board': board, 'label': label,
            'last_sync': {'at': iso(now - 3600), 'ok': True, 'reason': ''},
            'watch_pid': watch_pid, 'watch_started': beat,
            'watch_beat': beat, 'watch_every': 180,
        }
        slug = name.lower().replace(' ', '-')
        (self.state / f'{slug}.json').write_text(json.dumps(record))
        return record

    def prompt(self, env=None, **extra):
        return self.hook.answer({'hook_event_name': 'UserPromptSubmit', 'session_id': 'sid-1',
                                 **extra}, env or self.env, self.home, NOW)

    def stop(self, env=None, **extra):
        return self.hook.answer({'hook_event_name': 'Stop', 'session_id': 'sid-1',
                                 **extra}, env or self.env, self.home, NOW)

    def context(self, answer):
        return answer.get('hookSpecificOutput', {}).get('additionalContext', '')

    def test_a_dead_watcher_wakes_its_own_chat(self):
        """The real failure: the watcher exited, the chat never re-armed."""
        self.write_state(beat_hours_ago=3)
        told = self.context(self.prompt())
        self.assertIn(f'watcher is dead since {iso(NOW - 3 * 3600)}', told)
        self.assertIn('Nothing is polling your view', told)
        self.assertIn('watch --board 13734 --label "Multi Bot Bugs" --name "Multi Bot Bugs"',
                      told)
        body = json.dumps(self.prompt())
        self.assertIn('hookEventName', body)
        self.assertIn('UserPromptSubmit', body)

    def test_a_killed_watcher_names_when_it_was_last_seen(self):
        self.write_state(beat_hours_ago=2, watch_pid=dead_pid())
        self.assertIn(f'watcher is dead since {iso(NOW - 2 * 3600)}', self.context(self.prompt()))

    def test_a_pulsing_watcher_is_left_alone(self):
        self.write_state(beat_hours_ago=0, watch_pid=os.getpid())
        self.assertEqual(self.prompt(), {})
        self.assertEqual(self.stop(), {})

    def test_a_pre_upgrade_live_watcher_without_beats_is_left_alone(self):
        """An older watcher has watch_pid and watch_started, no watch_beat; live pid stays quiet."""
        record = self.write_state(beat_hours_ago=3, watch_pid=os.getpid())
        record.pop('watch_beat')
        record.pop('watch_every')
        (self.state / 'multi-bot-bugs.json').write_text(json.dumps(record))
        self.assertEqual(self.prompt(), {})
        self.assertEqual(self.stop(), {})

    def test_a_chat_that_never_armed_is_left_alone(self):
        self.assertEqual(self.prompt(), {}, 'no record, nothing to say')
        (self.state / 'multi-bot-bugs.json').write_text('{}')
        self.assertEqual(self.prompt(), {}, 'an empty record is not a loop')
        (self.state / 'multi-bot-bugs.json').write_text(json.dumps({'name': 'Multi Bot Bugs'}))
        self.assertIn('not armed', self.context(self.prompt()),
                      'a chat that synced but never armed is told to arm')

    def test_a_restarted_chat_is_told_its_loop_is_not_armed(self):
        self.write_state(owner_pid=dead_pid())
        told = self.context(self.prompt())
        self.assertIn('not armed', told)
        self.assertIn('Re-arm now', told)

    def test_stop_holds_the_turn_until_a_watcher_is_back(self):
        self.write_state(beat_hours_ago=3)
        blocked = self.stop()
        self.assertEqual(blocked.get('decision'), 'block')
        self.assertIn('watcher is dead since', blocked.get('reason', ''))
        for _ in range(self.hook.MAX_BLOCKS - 1):
            self.stop()
        self.assertEqual(self.stop(), {}, 'past the cap the turn ends, so a chat is never trapped')
        self.write_state(beat_hours_ago=0, watch_pid=os.getpid())
        self.assertEqual(self.stop(session_id='sid-2'), {}, 'a fresh watcher ends the nagging')

    def test_each_chat_reads_only_its_own_record(self):
        self.write_state(beat_hours_ago=3)
        self.write_state(name='Multi Bot Features', beat_hours_ago=3, watch_pid=2_000_000_000,
                         label='Multi Bot Features')
        mine = self.context(self.prompt())
        self.assertIn('Multi Bot Bugs', mine)
        self.assertNotIn('Multi Bot Features', mine)
        theirs = self.context(self.prompt({**self.env, 'MULTIBOT_SESSION': 'live-features',
                                          'ZSB_SESSION': 'live-features',
                                          'MULTIPROMPT_TAB': 'live-features'}))
        self.assertIn('Multi Bot Features', theirs)
        self.assertNotIn('Multi Bot Bugs', theirs)
        self.assertEqual(self.prompt({'HOME': str(self.home),
                                       'BOARD_DRAIN_STATE_DIR': str(self.state)}), {},
                         'no tab, no verdict')

    def test_a_broken_record_never_holds_the_turn(self):
        (self.state / 'multi-bot-bugs.json').write_text('{not json')
        self.assertEqual(self.prompt(), {})
        self.assertEqual(self.stop(), {})

    def test_the_hook_reads_its_input_and_answers_on_stdout(self):
        self.write_state(beat_hours_ago=3, now=time.time())
        done = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True,
                              input=json.dumps({'hook_event_name': 'UserPromptSubmit',
                                                'session_id': 'sid-1'}),
                              env={**os.environ, **self.env}, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout)
        self.assertIn('watcher is dead since', self.context(answer))

    def test_the_self_test_passes(self):
        done = subprocess.run([sys.executable, str(HOOK), '--self-test'],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('self-test ok', done.stdout)

    def test_the_chat_settings_register_the_guard(self):
        """Without a registration the hook never runs, and the chat stays deaf (VSTA-151)."""
        settings = json.loads(SETTINGS.read_text())
        commands = [hook.get('command', '')
                    for groups in settings['hooks'].values()
                    for group in groups for hook in group.get('hooks', [])]
        registered = [command for command in commands if 'board-drain-guard.py' in command]
        self.assertTrue(registered, 'register board-drain-guard.py in .claude/settings.json')
        for command in registered:
            self.assertIn('hooks/run-hook', command, 'a missing hook file must fail open via run-hook')
        events = [event for event, groups in settings['hooks'].items()
                  if any('board-drain-guard.py' in hook.get('command', '')
                         for group in groups for hook in group.get('hooks', []))]
        self.assertEqual(sorted(events), ['Stop', 'UserPromptSubmit'])


if __name__ == '__main__':
    unittest.main()
