"""peers (VSTA-349): the board peer and dead-identity audit, fixtures only.

Every read is a fixture: the board, its members, the managed agents, the live chat
list, the loop records, the timers and the start-up records. Nothing here reads the
real board, the real roster or the real systemd.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PEERS = ROOT / 'skills/board-drain/peers'
BOARD = 13556
NOW = 1800000000
WEEK = 7 * 86400


def iso(seconds):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def roster(*names):
    return ''.join(f'{name} (live-{index}, claude, /tmp)\n' for index, name in enumerate(names))


def loop_record(name, board=BOARD, label='Vstack', pid=None, expires=NOW + WEEK):
    return {'name': name, 'every': '2h', 'armed_at': iso(NOW - 3600),
            'expires_at': iso(expires), 'job': 'cron-1',
            'owner_pid': os.getpid() if pid is None else pid,
            'host': socket.gethostname(), 'board': board, 'label': label}


def dead_pid():
    process = subprocess.Popen([sys.executable, '-c', 'pass'])
    process.wait()
    return process.pid


def member(agent_id, name):
    return {'id': agent_id, 'displayName': name,
            'owner': {'id': 6, 'displayName': 'Valentin Yeo'}}


def managed(agent_id, name, board=BOARD, revoked=False, created=NOW - 90 * 86400):
    return {'id': agent_id, 'display_name': name, 'revoked': revoked,
            'created_at': iso(created), 'visibility': 'PRIVATE',
            'boards': [{'id': board, 'name': 'Vstack'}] if board else []}


def card(key, section, assignee=None, agent_id=None, kind='agent'):
    task = {'ticketNumber': key, 'projectId': BOARD, 'section': section,
            'labels': [{'name': 'Vstack'}]}
    if assignee:
        task['assignees'] = [{'id': 6, 'displayName': assignee, 'type': kind,
                              'agentId': agent_id or ''}]
    return {'task': task, 'comments': []}


class PeersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.states = self.root / 'states'
        self.states.mkdir()

    def write_state(self, record):
        name = record['name'].lower().replace(' ', '-') + '.json'
        (self.states / name).write_text(json.dumps(record))

    def run_peers(self, *, live=(), rows=(), members=(), agents=(), timers=(),
                  states=(), announce=None, published=None, name='Vstack Maintainer',
                  extra=(), now=NOW, roster_text=None, env=None, agents_key=True):
        data = {'rows': list(rows), 'members': list(members),
                'timers': list(timers), 'announce': dict(announce or {}),
                'published': dict(published or {})}
        if agents_key:
            data['agents'] = list(agents)
        if roster_text is not None:
            data['roster'] = roster_text
        fixture = self.root / 'peers.json'
        fixture.write_text(json.dumps(data))
        chats = self.root / 'roster.txt'
        chats.write_text(roster(*live))
        for state in states:
            self.write_state(state)
        base = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.states),
                    HYPERTASK_AGENT_TOKEN_FILE=str(self.root / 'none-token'),
                    SHIP_SESSION_NAME=name, HOME=str(self.root))
        base.pop('MULTIPROMPT_TAB', None)
        env = {**base, **(env or {})}
        return subprocess.run(
            [sys.executable, str(PEERS), '--board', str(BOARD), '--fixture', str(fixture),
             '--roster', str(chats), '--now', iso(now), '--name', name, *extra],
            capture_output=True, text=True, env=env)

    def test_a_live_peer_passes(self):
        result = self.run_peers(live=['Fleet Tools'],
                                members=[member('id-fleet', 'Fleet Tools')],
                                rows=[card('VSTA-1', 'Todo', 'Fleet Tools', 'id-fleet')])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('peer: LIVE Fleet Tools', result.stdout)
        self.assertEqual(result.stdout.splitlines()[-1],
                         f'peers: PASS (1 agent identities on board {BOARD}, none dead)')

    def test_an_armed_loop_counts_as_live_even_with_no_roster_line(self):
        """A chat between two of its own ticks is still woken by its armed loop."""
        result = self.run_peers(members=[member('id-loop', 'Board Drain Loop')],
                                states=[loop_record('Board Drain Loop')])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('peer: LIVE Board Drain Loop', result.stdout)

    def test_a_paused_chat_is_reported_and_held(self):
        """A pause is a decision, not a death: report it and never archive it."""
        result = self.run_peers(members=[member('id-loop', 'Board Drain Loop')],
                                states=[{**loop_record('Board Drain Loop'),
                                         'paused_at': iso(NOW - 600),
                                         'paused_reason': 'budget pause'}],
                                extra=['--apply'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('peer: PAUSED Board Drain Loop: paused until further notice: budget pause',
                      result.stdout)
        self.assertNotIn('ARCHIVED', result.stdout)

    def test_a_recent_identity_is_held_in_grace(self):
        """A chat created minutes ago has no roster line yet and must never be archived."""
        result = self.run_peers(members=[member('id-new', 'Brand New Chat')],
                                agents=[managed('id-new', 'Brand New Chat', created=NOW - 600)],
                                extra=['--apply'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('peer: GRACE Brand New Chat: identity created', result.stdout)
        self.assertNotIn('ARCHIVED', result.stdout)

    def test_a_recently_started_chat_is_held_in_grace(self):
        result = self.run_peers(members=[member('id-old', 'Old Chat')],
                                agents=[managed('id-old', 'Old Chat')],
                                announce={'Old Chat': iso(NOW - 3600)})
        self.assertIn('peer: GRACE Old Chat: chat last started', result.stdout)

    def test_a_recently_published_chat_is_held_in_grace(self):
        result = self.run_peers(members=[member('id-old', 'Old Chat')],
                                agents=[managed('id-old', 'Old Chat')],
                                published={'Old Chat': NOW - 7200})
        self.assertIn('peer: GRACE Old Chat: chat last published', result.stdout)

    def test_a_dead_identity_is_reported_and_never_touched_in_dry_run(self):
        result = self.run_peers(members=[member('id-dead', 'Ghost Chat')],
                                agents=[managed('id-dead', 'Ghost Chat', revoked=True)])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('peer: DEAD-IDENTITY Ghost Chat: id-dead', result.stdout)
        self.assertIn('peers: FAIL (1 dead identity', result.stdout)
        self.assertIn(f'peers: fix: skills/board-drain/peers --board {BOARD} --apply',
                      result.stdout)
        self.assertNotIn('ARCHIVED', result.stdout)

    def test_apply_archives_a_verified_dead_identity(self):
        with tempfile.TemporaryDirectory() as binaries:
            calls = Path(binaries) / 'calls.jsonl'
            write_cli(Path(binaries), calls)
            result = self.run_peers(members=[member('id-dead', 'Ghost Chat')],
                                    agents=[managed('id-dead', 'Ghost Chat')],
                                    extra=['--apply'],
                                    env={'PATH': f'{binaries}{os.pathsep}{os.environ["PATH"]}',
                                         'PEERS_CLI_CALLS': str(calls)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('peer: ARCHIVED Ghost Chat: id-dead', result.stdout)
            self.assertIn('peers: archived 1 dead identity (Ghost Chat)', result.stdout)
            self.assertEqual(archived_calls(calls), [['--json', 'agents', 'archive',
                                                      '--id', 'id-dead']])

    def test_an_identity_holding_open_tickets_is_orphaned_not_archived(self):
        """A dead identity with Doing work is someone's promise: report it, never archive."""
        result = self.run_peers(members=[member('id-dead', 'Ghost Chat')],
                                agents=[managed('id-dead', 'Ghost Chat')],
                                rows=[card('VSTA-7', 'Doing', 'Ghost Chat', 'id-dead'),
                                      card('VSTA-8', 'Todo', 'Ghost Chat', 'id-dead')],
                                extra=['--apply'])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('peer: ORPHAN-TICKETS Ghost Chat: id-dead; 2 open (VSTA-7, VSTA-8)',
                      result.stdout)
        self.assertNotIn('ARCHIVED', result.stdout)

    def test_orphaned_tickets_on_a_revoked_identity_are_reported(self):
        result = self.run_peers(members=[member('id-dead', 'Ghost Chat')],
                                agents=[managed('id-dead', 'Ghost Chat', revoked=True)],
                                rows=[card('VSTA-9', 'Checks', 'Ghost Chat', 'id-dead')])
        self.assertIn('peer: ORPHAN-TICKETS Ghost Chat: id-dead; identity revoked; 1 open '
                      '(VSTA-9)', result.stdout)

    def test_a_dead_sync_timer_is_reported(self):
        result = self.run_peers(live=['Vstack Maintainer'],
                                members=[member('id-me', 'Vstack Maintainer')],
                                timers=['vstack-maintainer', 'ghost-chat'])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f'peer: DEAD-TIMER board-sync@ghost-chat.timer: no live session; fix: '
                      f'systemctl --user disable --now board-sync@ghost-chat.timer',
                      result.stdout)
        self.assertNotIn('board-sync@vstack-maintainer.timer', result.stdout)

    def test_a_recently_seen_chat_keeps_its_timer(self):
        result = self.run_peers(live=['Vstack Maintainer'],
                                members=[member('id-me', 'Vstack Maintainer')],
                                timers=['ghost-chat'],
                                announce={'Ghost Chat': iso(NOW - 3600)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_calling_chat_is_never_a_peer_to_judge(self):
        result = self.run_peers(members=[member('id-me', 'Vstack Maintainer')],
                                agents=[managed('id-me', 'Vstack Maintainer', revoked=True)])
        self.assertIn('peer: LIVE Vstack Maintainer', result.stdout)
        self.assertNotIn('ARCHIVED', result.stdout)

    def test_a_person_is_never_archived(self):
        for name in ('Valentin Yeo', "Valentin's Claude Code"):
            with self.subTest(name=name):
                result = self.run_peers(live=[], agents=[managed('id-person', name)])
                self.assertIn(f'peer: LIVE {name}', result.stdout)

    def test_a_role_identity_is_never_archived(self):
        result = self.run_peers(agents=[managed('id-role', 'Chief Of Staff')])
        self.assertIn('peer: LIVE Chief Of Staff', result.stdout)

    def test_a_person_member_is_not_an_agent_peer(self):
        result = self.run_peers(live=['Vstack Maintainer'],
                                members=[{'id': 6, 'displayName': 'Valentin Yeo'},
                                         member('id-me', 'Vstack Maintainer')])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('Valentin Yeo', result.stdout)

    def test_apply_is_capped_per_run(self):
        names = ['Ghost One', 'Ghost Two', 'Ghost Three']
        with tempfile.TemporaryDirectory() as binaries:
            calls = Path(binaries) / 'calls.jsonl'
            write_cli(Path(binaries), calls)
            result = self.run_peers(
                members=[member(f'id-{index}', name) for index, name in enumerate(names)],
                agents=[managed(f'id-{index}', name) for index, name in enumerate(names)],
                extra=['--apply', '--max-archive', '2'],
                env={'PATH': f'{binaries}{os.pathsep}{os.environ["PATH"]}',
                     'PEERS_CLI_CALLS': str(calls)})
            self.assertEqual(len(archived_calls(calls)), 2, result.stdout)
            self.assertIn('peers: 1 more dead identities wait for the next run '
                          '(cap --max-archive 2)', result.stdout)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_management_key_is_passed_through_when_the_shell_exports_one(self):
        with tempfile.TemporaryDirectory() as binaries:
            calls = Path(binaries) / 'calls.jsonl'
            write_cli(Path(binaries), calls)
            result = self.run_peers(members=[member('id-dead', 'Ghost Chat')],
                                    agents=[managed('id-dead', 'Ghost Chat')],
                                    extra=['--apply'],
                                    env={'PATH': f'{binaries}{os.pathsep}{os.environ["PATH"]}',
                                         'PEERS_CLI_CALLS': str(calls),
                                         'HYPERTASK_MANAGEMENT_KEY': 'htmk-owner'})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(archived_calls(calls), [['--json', 'agents', 'archive', '--id',
                                                      'id-dead', '--management-key', 'htmk-owner']])

    def test_a_failed_archive_keeps_the_identity_reported_and_never_crashes(self):
        with tempfile.TemporaryDirectory() as binaries:
            calls = Path(binaries) / 'calls.jsonl'
            write_cli(Path(binaries), calls, fail_archive=True)
            result = self.run_peers(members=[member('id-dead', 'Ghost Chat')],
                                    agents=[managed('id-dead', 'Ghost Chat')],
                                    extra=['--apply'],
                                    env={'PATH': f'{binaries}{os.pathsep}{os.environ["PATH"]}',
                                         'PEERS_CLI_CALLS': str(calls)})
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('peer: DEAD-IDENTITY Ghost Chat: id-dead', result.stdout)
            self.assertIn('could not archive Ghost Chat', result.stderr)

    def test_an_unreadable_roster_exits_2_with_nothing_archived(self):
        with tempfile.TemporaryDirectory() as binaries:
            calls = Path(binaries) / 'calls.jsonl'
            write_cli(Path(binaries), calls)
            env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.states),
                       HYPERTASK_AGENT_TOKEN_FILE=str(self.root / 'none-token'),
                       SHIP_SESSION_NAME='Vstack Maintainer',
                       PATH=f'{binaries}{os.pathsep}{os.environ["PATH"]}',
                       PEERS_CLI_CALLS=str(calls))
            result = subprocess.run(
                [sys.executable, str(PEERS), '--board', str(BOARD), '--apply',
                 '--roster', str(self.root / 'missing.txt'), '--grace', '7d'],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn('live chat list unreadable', result.stderr)
            self.assertFalse(calls.exists())

    def test_an_unreadable_managed_agent_list_still_judges_the_board(self):
        """`agents list` is an owner-only read, so a chat may be refused it."""
        with tempfile.TemporaryDirectory() as binaries:
            calls = Path(binaries) / 'calls.jsonl'
            write_cli(Path(binaries), calls, refuse_list=True)
            result = self.run_peers(live=['Fleet Tools'],
                                    members=[member('id-fleet', 'Fleet Tools')],
                                    agents_key=False,
                                    env={'PATH': f'{binaries}{os.pathsep}{os.environ["PATH"]}',
                                         'PEERS_CLI_CALLS': str(calls)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('managed agent list unreadable', result.stdout)
            self.assertIn('peer: LIVE Fleet Tools', result.stdout)

    def test_a_missing_cli_fails_open(self):
        with tempfile.TemporaryDirectory() as empty:
            env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.states), PATH=str(empty))
            result = subprocess.run([sys.executable, str(PEERS), '--board', str(BOARD)],
                                    capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn('peers:', result.stderr)

    def test_names_match_trimmed_and_case_insensitive(self):
        result = self.run_peers(roster_text=roster('  fleet TOOLS '),
                                members=[member('id-fleet', 'Fleet Tools')])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shows_five_ticket_keys_at_most(self):
        rows = [card(f'VSTA-{index}', 'Todo', 'Ghost Chat', 'id-dead') for index in range(1, 8)]
        result = self.run_peers(members=[member('id-dead', 'Ghost Chat')], rows=rows)
        self.assertIn('7 open (VSTA-1, VSTA-2, VSTA-3, VSTA-4, VSTA-5) (+2 more)',
                      result.stdout)

    def test_self_test_passes(self):
        result = subprocess.run([sys.executable, str(PEERS), '--self-test'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'peers self-test ok')


class PeersTimeoutTests(unittest.TestCase):
    """A slow board degrades to one line; it never hangs an onboarding chat."""

    def setUp(self):
        import importlib.machinery
        import importlib.util
        path = ROOT / 'skills/board-drain/peers'
        loader = importlib.machinery.SourceFileLoader('board_drain_peers_timeout', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.peers = importlib.util.module_from_spec(spec)
        sys.modules[loader.name] = self.peers
        loader.exec_module(self.peers)

    def args(self, **overrides):
        import argparse
        base = dict(board=BOARD, name='Vstack Maintainer', apply=False, max_archive=3,
                    grace='7d', fixture=None, roster=None, now=None)
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_a_board_read_that_times_out_exits_2_with_nothing_archived(self):
        import argparse
        from unittest import mock
        timeout = subprocess.TimeoutExpired('hypertask', 15)
        with mock.patch.object(self.peers, 'run_cli', side_effect=timeout), \
                mock.patch.object(self.peers, 'roster_names', return_value=set()):
            snap = self.peers.snapshot(self.args())
        self.assertTrue(snap.broken)
        self.assertIn('board tickets unreadable', snap.notes[0])

    def test_the_caller_sees_one_line_and_exit_2_on_a_timeout(self):
        import io
        from contextlib import redirect_stderr
        from unittest import mock
        timeout = subprocess.TimeoutExpired('hypertask', 15)
        err = io.StringIO()
        with mock.patch.object(self.peers, 'run_cli', side_effect=timeout), \
                mock.patch.object(self.peers, 'roster_names', return_value=set()), \
                mock.patch.object(self.peers, 'archive') as archive, \
                redirect_stderr(err):
            code = self.peers.main(['--board', str(BOARD), '--apply'])
        self.assertEqual(code, 2)
        self.assertIn('peers: board tickets unreadable', err.getvalue())
        archive.assert_not_called()


class DrainCheckPeerNotes(unittest.TestCase):
    """drain-check reports dead peers as news, never as a failure of its own tick."""

    def setUp(self):
        import importlib.machinery
        import importlib.util
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ['BOARD_DRAIN_CACHE_DIR'] = self.temp.name
        path = ROOT / 'skills/board-drain/drain-check'
        loader = importlib.machinery.SourceFileLoader('board_drain_check_peers', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.drain = importlib.util.module_from_spec(spec)
        sys.modules[loader.name] = self.drain
        loader.exec_module(self.drain)
        self.peers = self.drain.peers_module()

    def args(self, **overrides):
        import argparse
        base = dict(board=BOARD, label='Vstack', fixture=None, state_name='Vstack Maintainer',
                    no_peers=False, now=None)
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_a_fixture_tick_never_reads_the_host(self):
        """A board under test is not this host's fleet, and its tick must stay offline."""
        from unittest import mock
        with mock.patch.object(self.peers, 'snapshot') as read:
            self.assertEqual(self.drain.peer_notes([], self.args(fixture='x.json'), NOW), [])
            read.assert_not_called()

    def test_a_tick_without_a_state_name_skips_the_audit(self):
        from unittest import mock
        with mock.patch.object(self.peers, 'snapshot') as read:
            self.assertEqual(self.drain.peer_notes([], self.args(state_name=None), NOW), [])
            read.assert_not_called()

    def test_no_peers_skips_the_audit(self):
        from unittest import mock
        with mock.patch.object(self.peers, 'snapshot') as read:
            self.assertEqual(self.drain.peer_notes([], self.args(no_peers=True), NOW), [])
            read.assert_not_called()

    def test_a_dead_peer_becomes_one_note_with_the_exact_fix(self):
        from unittest import mock
        snap = self.peers.Snapshot(NOW, BOARD, 'Vstack Maintainer', 'id-me', (), (), {},
                                   frozenset(), (), (), {}, {})
        peer = self.peers.Peer('Ghost Chat', 'id-dead', 'DEAD-IDENTITY')
        with mock.patch.object(self.peers, 'snapshot', return_value=snap), \
                mock.patch.object(self.peers, 'classify', return_value=[peer]):
            notes = self.drain.peer_notes([], self.args(), NOW)
        self.assertEqual(notes, [f'peer: DEAD-IDENTITY Ghost Chat: id-dead; no live chat, no '
                                 f'armed loop, no recent activity; fix: '
                                 f'skills/board-drain/peers --board {BOARD} --apply'])

    def test_a_failed_peer_read_is_one_warning_and_never_a_fail(self):
        from unittest import mock
        with mock.patch.object(self.peers, 'snapshot', side_effect=ValueError('board down')):
            notes = self.drain.peer_notes([], self.args(), NOW)
        self.assertEqual(notes, ['warning: peers: board down; skipped'])

    def test_the_audit_reuses_the_cards_the_tick_already_read(self):
        from unittest import mock
        snap = self.peers.Snapshot(NOW, BOARD, 'Vstack Maintainer', 'id-me', (), (), {},
                                   frozenset(), (), (), {}, {})
        with mock.patch.object(self.peers, 'snapshot', return_value=snap) as read:
            self.drain.peer_notes([{'ticketNumber': 'VSTA-1', 'section': 'Todo'}],
                                  self.args(), NOW)
        self.assertEqual(read.call_args.kwargs['rows'],
                         [{'task': {'ticketNumber': 'VSTA-1', 'section': 'Todo'}}])
        self.assertFalse(read.call_args.kwargs['managed'], 'a chat cannot list managed agents')

def write_cli(directory, calls, refuse_list=False, fail_archive=False):
    """A `hypertask` stand-in: it records each call and answers one shape."""
    binary = directory / 'hypertask'
    binary.write_text(f'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['PEERS_CLI_CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if args[1:2] == ['agents'] and args[2:3] == ['list']:
    if {refuse_list}:
        print(json.dumps({{'success': False,
                          'error': 'Agents cannot list managed agent identities'}}))
        sys.exit(1)
    print(json.dumps({{'success': True, 'agents': []}}))
elif args[1:2] == ['project'] and args[2:3] == ['members']:
    print(json.dumps({{'success': True, 'members': []}}))
elif args[1:2] == ['agents'] and args[2:3] == ['archive']:
    if {fail_archive}:
        print('agents archive failed', file=sys.stderr)
        sys.exit(1)
    print(json.dumps({{'success': True}}))
else:
    print(json.dumps({{'success': True}}))
''')
    binary.chmod(0o755)


def archived_calls(path):
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [row for row in rows if row[1:3] == ['agents', 'archive']]


if __name__ == '__main__':
    unittest.main()
