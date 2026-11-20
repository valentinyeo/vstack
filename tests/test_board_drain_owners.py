import json
from pathlib import Path
import subprocess
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


class OwnersTests(unittest.TestCase):
    def run_owners(self, tasks, live, roster_text=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'tickets.json'
            fixture.write_text(json.dumps([{'task': item} for item in tasks]))
            chats = root / 'roster.txt'
            chats.write_text(roster_text if roster_text is not None else roster(*live))
            return subprocess.run([str(OWNERS), '--board', str(BOARD), '--fixture', str(fixture),
                                   '--roster', str(chats)],
                                  capture_output=True, text=True)

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
        self.assertEqual(lines[-1], 'owners: FAIL (2 labels)')
        self.assertNotIn('Token Ladder', result.stdout)
        self.assertNotIn('Vstack', result.stdout)

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
                 task('VSTA-40', 'Todo', ['Vstack']),
                 task('VSTA-29', 'Todo', [])]
        result = self.run_owners(tasks, [])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'owners: PASS\n')

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
