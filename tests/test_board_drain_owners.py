import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OWNERS = ROOT / 'skills/board-drain/owners'
BOARD = 13556


def task(key, section, labels, board=BOARD):
    return {'ticketNumber': key, 'projectId': board, 'section': section,
            'labels': [{'name': name} for name in labels]}


def roster(*names):
    """roster-live's own shape: Name (session, harness, cwd)."""
    return ''.join(f'{name} (live-{index}, claude, /tmp)\n' for index, name in enumerate(names))


def state_file(name, pid, board=BOARD, label='Vstack'):
    """One loop-state file, as `loop-state arm` writes it."""
    record = {'name': name, 'every': '15m', 'armed_at': '2026-11-20T12:00:00Z',
              'expires_at': '2099-01-01T00:00:00Z', 'job': 'cron-1',
              'owner_pid': pid, 'host': socket.gethostname()}
    if board is not None:
        record['board'] = board
    if label is not None:
        record['label'] = label
    return record


def dead_pid():
    process = subprocess.Popen([sys.executable, '-c', 'pass'])
    process.wait()
    return process.pid


class OwnersTests(unittest.TestCase):
    def run_owners(self, tasks, live, roster_text=None, states=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'tickets.json'
            fixture.write_text(json.dumps([{'task': item} for item in tasks]))
            chats = root / 'roster.txt'
            chats.write_text(roster_text if roster_text is not None else roster(*live))
            states_dir = root / 'states'
            states_dir.mkdir()
            for state in states:
                slug = state['name'].strip().lower().replace(' ', '-')
                (states_dir / (slug + '.json')).write_text(json.dumps(state))
            env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(states_dir))
            return subprocess.run([str(OWNERS), '--board', str(BOARD), '--fixture', str(fixture),
                                   '--roster', str(chats)],
                                  capture_output=True, text=True, env=env)

    def test_todays_orphans_fail_by_name(self):
        """The real board 13556 case: Poteto and Fleet Tools have work, nobody drains it."""
        tasks = [task('VSTA-8', 'Todo', ['Poteto']),
                 task('VSTA-31', 'Todo', ['Poteto', 'Token Ladder']),
                 task('VSTA-9', 'Todo', ['Fleet Tools']),
                 task('VSTA-11', 'Todo', ['Fleet Tools']),
                 task('VSTA-34', 'Todo', ['Vstack']),
                 task('VSTA-27', 'Todo', ['Token Ladder'])]
        result = self.run_owners(tasks, ['Token Ladder'])
        self.assertEqual(result.returncode, 1, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn('orphan: Fleet Tools: 2 open (VSTA-9, VSTA-11). '
                      'Relabel to a live chat or start that chat.', lines)
        self.assertIn('orphan: Poteto: 2 open (VSTA-8, VSTA-31). '
                      'Relabel to a live chat or start that chat.', lines)
        self.assertIn('orphan: Vstack: 1 open (VSTA-34). '
                      'Relabel to a live chat or start that chat.', lines)
        self.assertEqual(lines[-1], 'owners: FAIL (3 labels)')
        self.assertNotIn('Token Ladder', result.stdout)

    def test_every_label_live_passes(self):
        tasks = [task('VSTA-27', 'Todo', ['Token Ladder']),
                 task('VSTA-43', 'Doing', ['Board Drain Loop']),
                 task('VSTA-6', 'Verification Backlog', ['VPS Admin'])]
        result = self.run_owners(tasks, ['Token Ladder', 'Board Drain Loop', 'VPS Admin'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'owners: PASS\n')

    def test_duplicated_roster_lines_report_once(self):
        tasks = [task('VSTA-27', 'Todo', ['Token Ladder']),
                 task('VSTA-9', 'Todo', ['Fleet Tools'])]
        result = self.run_owners(tasks, [],
                                 roster_text=roster('Token Ladder', 'Token Ladder', 'Token Ladder'))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            'orphan: Fleet Tools: 1 open (VSTA-9). Relabel to a live chat or start that chat.',
            'owners: FAIL (1 labels)'])

    def test_generic_labels_are_skipped(self):
        tasks = [task('VSTA-45', 'Todo', ['brain-light', 'Bug']),
                 task('VSTA-37', 'Todo', ['brain-medium', 'infra']),
                 task('VSTA-43', 'Doing', ['brain-medium', 'verification']),
                 task('VSTA-29', 'Todo', [])]
        result = self.run_owners(tasks, [])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'owners: PASS\n')

    def test_vstack_is_a_chat_label_not_a_generic_one(self):
        """The verifier's repro: Vstack names the Vstack Maintainer chat, so it needs an owner."""
        result = self.run_owners([task('VSTA-40', 'Todo', ['Vstack'])], [])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            'orphan: Vstack: 1 open (VSTA-40). Relabel to a live chat or start that chat.',
            'owners: FAIL (1 labels)'])

    def test_a_label_recorded_by_an_armed_loop_is_owned(self):
        """Vstack Maintainer drains board 13556 label Vstack, and its loop is armed."""
        result = self.run_owners([task('VSTA-40', 'Todo', ['Vstack'])], [],
                                 states=[state_file('Vstack Maintainer', os.getpid())])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, 'owners: PASS\n')

    def test_a_dead_loop_leaves_its_label_an_orphan(self):
        result = self.run_owners([task('VSTA-40', 'Todo', ['Vstack'])], [],
                                 states=[state_file('Vstack Maintainer', dead_pid())])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], 'owners: FAIL (1 labels)')

    def test_a_state_file_without_board_or_label_is_ignored(self):
        """Old state files predate the board and label record, and own nothing."""
        result = self.run_owners([task('VSTA-40', 'Todo', ['Vstack'])], [],
                                 states=[state_file('Vstack Maintainer', os.getpid(),
                                                    board=None, label=None)])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], 'owners: FAIL (1 labels)')

    def test_a_loop_for_another_board_owns_nothing_here(self):
        result = self.run_owners([task('VSTA-40', 'Todo', ['Vstack'])], [],
                                 states=[state_file('Vstack Maintainer', os.getpid(), board=2060)])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], 'owners: FAIL (1 labels)')

    def test_names_match_trimmed_and_case_insensitive(self):
        tasks = [task('VSTA-27', 'Todo', ['Token Ladder']),
                 task('VSTA-9', 'Todo', ['fleet TOOLS'])]
        result = self.run_owners(tasks, [], roster_text=roster(' token ladder ', 'Fleet Tools'))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shows_five_keys_at_most(self):
        tasks = [task(f'VSTA-{index}', 'Todo', ['Fleet Tools']) for index in range(1, 8)]
        result = self.run_owners(tasks, [])
        self.assertIn('orphan: Fleet Tools: 7 open (VSTA-1, VSTA-2, VSTA-3, VSTA-4, VSTA-5).',
                      result.stdout)

    def test_unreadable_roster_exits_2(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'tickets.json'
            fixture.write_text(json.dumps([{'task': task('VSTA-9', 'Todo', ['Fleet Tools'])}]))
            result = subprocess.run([str(OWNERS), '--board', str(BOARD), '--fixture', str(fixture),
                                     '--roster', str(Path(directory) / 'missing.txt')],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('owners:', result.stderr)


if __name__ == '__main__':
    unittest.main()
