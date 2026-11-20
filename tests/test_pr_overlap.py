"""Fixtures-only tests for scripts/pr-overlap: older PR wins on guarded files and ticket keys."""

import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/pr-overlap'
GUARDED = ROOT / 'config/pr-overlap-guarded.txt'


def load_script():
    loader = importlib.machinery.SourceFileLoader('pr_overlap', str(SCRIPT))
    spec = importlib.util.spec_from_loader('pr_overlap', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def pr(number, created_at, title=None, branch=None, author='valentinyeo', draft=False, files=()):
    title = title or f'VSTA-{number} work'
    branch = branch or f'vsta-{number}-work'
    return {
        'number': number,
        'created_at': created_at,
        'title': title,
        'head': {'ref': branch},
        'user': {'login': author},
        'draft': draft,
        'files': list(files),
    }


class OverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def guarded(self):
        return self.m.read_guarded(GUARDED)

    def findings(self, this, others):
        return self.m.findings(this, others, self.guarded(), self.m.ticket_key, self.m.is_bot)

    def test_older_open_pr_wins_newer_blocked_on_guarded_file(self):
        older = pr(10, '2026-01-01T00:00:00Z', files=['skills/valentin-mode/SKILL.md'])
        newer = pr(20, '2026-01-02T00:00:00Z', files=['skills/valentin-mode/SKILL.md'])
        found = self.findings(newer, [older, newer])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['kind'], 'SAME-FILE')
        self.assertEqual(found[0]['other_pr'], 10)
        self.assertIn('skills/valentin-mode/SKILL.md', found[0]['path_or_key'])

    def test_older_pr_not_blocked_when_newer_also_edits_guarded(self):
        older = pr(10, '2026-01-01T00:00:00Z', files=['skills/valentin-mode/SKILL.md'])
        newer = pr(20, '2026-01-02T00:00:00Z', files=['skills/valentin-mode/SKILL.md'])
        self.assertEqual(self.findings(older, [older, newer]), [])

    def test_unguarded_path_does_not_collide(self):
        older = pr(10, '2026-01-01T00:00:00Z', files=['README.md'])
        newer = pr(20, '2026-01-02T00:00:00Z', files=['README.md'])
        self.assertEqual(self.findings(newer, [older, newer]), [])

    def test_same_ticket_blocks_newer(self):
        older = pr(10, '2026-01-01T00:00:00Z', title='VSTA-61 first', branch='vsta-61-a')
        newer = pr(20, '2026-01-02T00:00:00Z', title='VSTA-61 second', branch='vsta-61-b',
                  files=['scripts/foo.py'])
        found = self.findings(newer, [older, newer])
        kinds = {f['kind'] for f in found}
        self.assertIn('SAME-TICKET', kinds)
        ticket = [f for f in found if f['kind'] == 'SAME-TICKET'][0]
        self.assertEqual(ticket['other_pr'], 10)
        self.assertEqual(ticket['path_or_key'], 'VSTA-61')

    def test_bot_pr_ignored_as_blocker(self):
        bot = pr(10, '2026-01-01T00:00:00Z', author='dependabot[bot]',
                files=['skills/valentin-mode/SKILL.md'])
        newer = pr(20, '2026-01-02T00:00:00Z', files=['skills/valentin-mode/SKILL.md'])
        self.assertEqual(self.findings(newer, [bot, newer]), [])

    def test_draft_counts_as_open(self):
        older = pr(10, '2026-01-01T00:00:00Z', draft=True,
                  files=['skills/valentin-mode/SKILL.md'])
        newer = pr(20, '2026-01-02T00:00:00Z', files=['skills/valentin-mode/SKILL.md'])
        self.assertTrue(self.findings(newer, [older, newer]))

    def test_message_names_blocking_pr(self):
        older = pr(42, '2026-01-01T00:00:00Z', files=['skills/valentin-mode/SKILL.md'])
        newer = pr(99, '2026-01-02T00:00:00Z', title='VSTA-61 probe', files=['skills/valentin-mode/SKILL.md'])
        line = self.m.format_finding(newer, self.findings(newer, [older, newer])[0])
        self.assertIn('PR #42 (older)', line)
        self.assertIn('VSTA-61', line)
        self.assertIn('skills/valentin-mode/SKILL.md', line)

    def test_same_second_lower_number_blocks_higher(self):
        ts = '2026-01-01T12:00:00Z'
        older = pr(10, ts, files=['skills/valentin-mode/SKILL.md'])
        newer = pr(20, ts, files=['skills/valentin-mode/SKILL.md'])
        found = self.findings(newer, [older, newer])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['other_pr'], 10)

    def test_same_second_higher_number_not_blocked_by_lower(self):
        ts = '2026-01-01T12:00:00Z'
        lower = pr(10, ts, files=['skills/valentin-mode/SKILL.md'])
        higher = pr(20, ts, files=['skills/valentin-mode/SKILL.md'])
        self.assertEqual(self.findings(lower, [lower, higher]), [])

    def test_same_second_same_ticket_blocks_higher_number(self):
        ts = '2026-01-01T12:00:00Z'
        older = pr(10, ts, title='VSTA-61 a', branch='vsta-61-a')
        newer = pr(20, ts, title='VSTA-61 b', branch='vsta-61-b', files=['scripts/foo.py'])
        found = self.findings(newer, [older, newer])
        self.assertTrue(any(f['kind'] == 'SAME-TICKET' for f in found))

    def test_no_pr_number_exits_with_clear_message(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), '--repo', 'valentinyeo/vstack', '--pr', ''],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(proc.stderr.strip(), 'pr-overlap: no PR number; pass --pr N')

    def test_malformed_pulls_payload_fails_closed(self):
        saved = self.m.api_request

        def bad_batch(url, token):
            if '/pulls?' in url and 'state=open' in url:
                return {'documentation_url': 'https://docs.github.com/rest'}
            return saved(url, token)

        self.m.api_request = bad_batch
        try:
            with self.assertRaises(SystemExit) as ctx:
                self.m.list_open_pulls('o', 'r', 'tok')
            self.assertEqual(str(ctx.exception), 'pr-overlap: GitHub pulls response is not a list')
        finally:
            self.m.api_request = saved

    def test_missing_guarded_file_fails_closed(self):
        missing = ROOT / 'config/no-such-guarded.txt'
        with self.assertRaises(SystemExit) as ctx:
            self.m.read_guarded(missing)
        self.assertEqual(str(ctx.exception), 'pr-overlap: guarded paths file not found: {}'.format(missing))

    def test_self_test_runs(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), '--self-test'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == '__main__':
    unittest.main()