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
        configs = self.home / '.local/state/multiprompt/agent-host'
        configs.mkdir(parents=True)
        (configs / 'own.config.json').write_text(json.dumps({'tmux': TAB, 'sid': 'sid-bugs'}))
        sender = self.home / '.multiprompt-runtime/mp-send'
        sender.parent.mkdir()
        sender.write_text(f'#!{sys.executable}\nimport sys\nsys.exit(0)\n')
        sender.chmod(0o755)
        # All three tab keys are set, so an ambient one in the test runner never wins.
        self.env = {'HOME': str(self.home), 'MULTIBOT_SESSION': TAB, 'PATH': str(sender.parent),
                    'ZSB_SESSION': TAB, 'MULTIPROMPT_TAB': TAB,
                    'BOARD_DRAIN_STATE_DIR': str(self.state),
                    'BOARD_DRAIN_NOTIFY_URL': '', 'NTFY_URL': '', 'NTFY_TOPIC': '',
                    'NTFY_TOKEN': ''}
        patched = patch.dict(os.environ, self.env)
        patched.start()
        self.addCleanup(patched.stop)
        self.hook = load_hook()

    def write_state(self, name='Multi Bot Bugs', beat_hours_ago=3, watch_pid=None,
                    owner_pid=None, board=13734, label='Multi Bot Bugs', now=NOW, paused=None):
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
        record.update(paused or {})
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

    def test_a_paused_chat_is_never_nagged_or_held(self):
        """VSTA-309: told to go idle, the chat must still be able to stop."""
        self.write_state(beat_hours_ago=3, paused={'paused_at': iso(NOW - 3600),
                                                  'paused_until': iso(NOW + 6 * 3600),
                                                  'paused_reason': 'Claude budget pause'})
        self.assertEqual(self.prompt(), {})
        self.assertEqual(self.stop(), {}, 'Stop never blocks a paused chat')

    def test_an_expired_pause_nags_again(self):
        self.write_state(beat_hours_ago=3, paused={'paused_at': iso(NOW - 3600),
                                                  'paused_until': iso(NOW - 60),
                                                  'paused_reason': 'Claude budget pause'})
        self.assertIn('watcher is dead since', self.context(self.prompt()))
        self.assertEqual(self.stop().get('decision'), 'block')

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

    def _start_ntfy_server(self, status=200):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading

        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(length).decode('utf-8', errors='replace')
                received.append({
                    'path': self.path,
                    'headers': {k.lower(): v for k, v in self.headers.items()},
                    'body': body,
                })
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b'ok' if status < 300 else b'err')

            def log_message(self, format, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        port = server.server_address[1]
        return f'http://127.0.0.1:{port}/test-topic', received

    def test_kill_watcher_process_holds_stop_and_names_rearm_command(self):
        """VSTA-151 round 2: kill a real watch subprocess; own hook names re-arm and holds Stop."""
        fixture = self.home / 'view.json'
        task = {'ticketNumber': 'MUBO-1', 'projectId': 13734, 'section': 'Doing',
                'labels': [{'name': 'Multi Bot Bugs'}], 'status': 'Normal',
                'waitingOnUserId': None, 'blockerCommentId': None,
                'updatedAt': iso(time.time() - 60), 'assignees': []}
        fixture.write_text(json.dumps([{'task': task, 'comments': []}]))
        loop = self.hook.loop_state()
        loop.arm('Multi Bot Bugs', every='6h', job='cron-1', board=13734, label='Multi Bot Bugs')
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / 'skills/board-drain/watch'), '--board', '13734',
             '--label', 'Multi Bot Bugs', '--name', 'Multi Bot Bugs',
             '--fixture', str(fixture), '--no-sync', '--every', '1', '--heartbeat', '60'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, **self.env},
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                state = loop.stored('Multi Bot Bugs')
                if state.get('watch_pid') == proc.pid:
                    break
                time.sleep(0.1)
            self.assertEqual(loop.stored('Multi Bot Bugs').get('watch_pid'), proc.pid)
            # Survives a view change while alive and keeps hook silent.
            task2 = dict(task, ticketNumber='MUBO-2', section='Todo')
            fixture.write_text(json.dumps([{'task': task, 'comments': []},
                                           {'task': task2, 'comments': []}]))
            self.assertIn('changed: MUBO-2 new in Todo', proc.stdout.readline())
            time.sleep(0.2)
            self.assertIsNone(proc.poll(), 'watcher must keep polling after a view change')
            self.assertEqual(self.hook.answer({'hook_event_name': 'Stop', 'session_id': 'sid-live'},
                                              self.env, self.home), {})
        finally:
            proc.kill()
            proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()
        blocked = self.hook.answer({'hook_event_name': 'Stop', 'session_id': 'sid-killed'},
                                   self.env, self.home)
        self.assertEqual(blocked.get('decision'), 'block', blocked)
        self.assertIn('watcher is dead since', blocked.get('reason', ''))
        self.assertIn('watch --board 13734 --label "Multi Bot Bugs" --name "Multi Bot Bugs"',
                      blocked.get('reason', ''))

    def test_hypertask_reconciler_kill_test_uses_same_loop_state_and_guard(self):
        """VSTA-151 round 2: Hypertask Reconciler (live-2a735a3c) shares loop-state and guard."""
        announce = self.home / '.local/state/roster/announce'
        (announce / 'live-2a735a3c.json').write_text(json.dumps({
            'tmux': 'live-2a735a3c', 'multibot': 'Hypertask Reconciler',
            'name': 'Claude', 'cwd': '/home/valentin/projects/vstack', 'sid': 'sid-rec',
        }))
        url, received = self._start_ntfy_server()
        rec_env = {**self.env, 'MULTIBOT_SESSION': 'live-2a735a3c',
                   'ZSB_SESSION': 'live-2a735a3c', 'MULTIPROMPT_TAB': 'live-2a735a3c',
                   'BOARD_DRAIN_NOTIFY_URL': url}
        fixture = self.home / 'rec-view.json'
        task = {'ticketNumber': 'VSTA-151', 'projectId': 13556, 'section': 'Doing',
                'labels': [{'name': 'Hypertask Reconciler'}], 'status': 'Normal',
                'waitingOnUserId': None, 'blockerCommentId': None,
                'updatedAt': iso(time.time() - 60), 'assignees': []}
        fixture.write_text(json.dumps([{'task': task, 'comments': []}]))
        loop = self.hook.loop_state()
        loop.arm('Hypertask Reconciler', every='6h', job='583adbe8',
                 board=13556, label='Hypertask Reconciler')
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / 'skills/board-drain/watch'), '--board', '13556',
             '--label', 'Hypertask Reconciler', '--name', 'Hypertask Reconciler',
             '--fixture', str(fixture), '--no-sync', '--every', '1', '--heartbeat', '60'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, **rec_env},
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if loop.stored('Hypertask Reconciler').get('watch_pid') == proc.pid:
                    break
                time.sleep(0.1)
            self.assertEqual(loop.stored('Hypertask Reconciler').get('watch_pid'), proc.pid)
        finally:
            proc.kill()
            proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()
        now_dead = time.time() + 700  # > 10 minutes after last beat
        blocked = self.hook.answer({'hook_event_name': 'Stop', 'session_id': 'sid-rec-1'},
                                   rec_env, self.home, now=now_dead)
        self.assertEqual(blocked.get('decision'), 'block', blocked)
        self.assertIn(
            'watch --board 13556 --label "Hypertask Reconciler" --name "Hypertask Reconciler"',
            blocked.get('reason', ''))
        self.assertEqual(len(received), 1, received)
        self.assertIn('Hypertask Reconciler', received[0]['body'])
        self.assertIn('dead since', received[0]['body'])

    def test_dead_over_10_minutes_pushes_valentin_once_per_dead_spell(self):
        """VSTA-151 round 2: push once after >10m dead, never twice in one spell, fresh after recovery."""
        url, received = self._start_ntfy_server()
        env = {**self.env, 'BOARD_DRAIN_NOTIFY_URL': url}
        loop = self.hook.loop_state()

        # Dead 9 minutes -> no push yet.
        self.write_state(beat_hours_ago=0, watch_pid=dead_pid(), now=NOW)
        self.hook.answer({'hook_event_name': 'UserPromptSubmit', 'session_id': 'sid-1'},
                         env, self.home, NOW + 540)
        self.assertEqual(received, [], 'must not push under 10 minutes')
        # Dead exactly 10 minutes -> still not over 10 minutes.
        self.hook.answer({'hook_event_name': 'UserPromptSubmit', 'session_id': 'sid-1'},
                         env, self.home, NOW + 600)
        self.assertEqual(received, [], 'must not push at exactly 10 minutes')

        # Dead 11 minutes -> pushes ONCE and records in loop-state.
        self.hook.answer({'hook_event_name': 'UserPromptSubmit', 'session_id': 'sid-1'},
                         env, self.home, NOW + 660)
        self.assertEqual(len(received), 1)
        self.assertIn('Multi Bot Bugs', received[0]['body'])
        self.assertIn(iso(NOW), received[0]['body'])
        notice = loop.stored('Multi Bot Bugs').get('dead_notice')
        self.assertEqual(notice, {'at': iso(NOW + 660), 'since': iso(NOW), 'via': 'ntfy'})

        # Next prompt and Stop during same dead spell -> NO second push.
        self.hook.answer({'hook_event_name': 'UserPromptSubmit', 'session_id': 'sid-1'},
                         env, self.home, NOW + 900)
        self.hook.answer({'hook_event_name': 'Stop', 'session_id': 'sid-1'},
                         env, self.home, NOW + 960)
        self.assertEqual(len(received), 1, 'at most one push per dead spell')

        # Recover, then die again in a new spell -> pushes once for the new spell.
        loop.record_watch('Multi Bot Bugs', os.getpid(), now=NOW + 1000, every=180)
        self.assertNotIn('dead_notice', loop.stored('Multi Bot Bugs'))
        loop.record_watch('Multi Bot Bugs', dead_pid(), now=NOW + 1200, every=180)
        self.hook.answer({'hook_event_name': 'Stop', 'session_id': 'sid-2'},
                         env, self.home, NOW + 1900)
        self.assertEqual(len(received), 2, 'new dead spell after recovery gets one new push')
        self.assertIn(iso(NOW + 1200), received[1]['body'])

    def test_ntfy_topic_discovered_from_existing_notify_hook_without_leaking_secret(self):
        hooks_dir = self.home / '.claude/hooks'
        hooks_dir.mkdir(parents=True)
        secret_topic = 'secret-topic-xyz123456'
        (hooks_dir / 'notify-on-stop.sh').write_text(
            f'#!/bin/bash\nexport NTFY_TOPIC="${{NTFY_TOPIC:-{secret_topic}}}"\n'
        )
        url = self.hook.ntfy_url(self.home, {'HOME': str(self.home)})
        self.assertEqual(url, f'https://ntfy.sh/{secret_topic}')
        # Verify dead_notice and hook output never leak the topic.
        local_url, received = self._start_ntfy_server()
        self.write_state(beat_hours_ago=1, watch_pid=dead_pid(), now=NOW)
        with patch.object(self.hook, 'ntfy_url', return_value=local_url):
            out = self.hook.answer({'hook_event_name': 'UserPromptSubmit', 'session_id': 'sid-1'},
                                   self.env, self.home, NOW)
        self.assertNotIn(secret_topic, json.dumps(out))
        self.assertNotIn(secret_topic, (self.state / 'multi-bot-bugs.json').read_text())
        self.assertEqual(len(received), 1)

    def test_session_say_fallback_when_ntfy_unconfigured(self):
        bin_dir = self.home / '.local/bin'
        bin_dir.mkdir(parents=True)
        log = self.home / 'session-say.log'
        script = bin_dir / 'session-say'
        script.write_text(
            f'#!{sys.executable}\nimport pathlib, sys\n'
            f'pathlib.Path({str(log)!r}).write_text(" ".join(sys.argv[1:]))\n'
        )
        script.chmod(0o755)
        self.write_state(beat_hours_ago=1, watch_pid=dead_pid(), now=NOW)
        env = {**self.env, 'NTFY_TOPIC': '', 'NTFY_URL': '', 'BOARD_DRAIN_NOTIFY_URL': ''}
        self.hook.answer({'hook_event_name': 'Stop', 'session_id': 'sid-1'}, env, self.home, NOW)
        self.assertTrue(log.exists(), 'expected session-say fallback')
        logged = log.read_text()
        self.assertIn('poteto', logged)
        self.assertIn('Multi Bot Bugs', logged)
        self.assertEqual(self.hook.loop_state().stored('Multi Bot Bugs')['dead_notice']['via'],
                         'session-mail')

    def test_failed_push_delivery_fails_open_and_does_not_mark_sent(self):
        url, received = self._start_ntfy_server(status=500)
        self.write_state(beat_hours_ago=1, watch_pid=dead_pid(), now=NOW)
        env = {**self.env, 'BOARD_DRAIN_NOTIFY_URL': url}
        blocked = self.hook.answer({'hook_event_name': 'Stop', 'session_id': 'sid-1'},
                                   env, self.home, NOW)
        self.assertEqual(len(received), 1, 'must attempt delivery before failing open')
        self.assertEqual(blocked.get('decision'), 'block')
        self.assertNotIn('dead_notice', self.hook.loop_state().stored('Multi Bot Bugs'))


if __name__ == '__main__':
    unittest.main()
