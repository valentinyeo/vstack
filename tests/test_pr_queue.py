"""Tests for skills/pr-housekeeping/pr-queue: mine filter, staleness, exit codes. Fixtures only."""

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/pr-housekeeping/pr-queue'


def load_script():
    loader = importlib.machinery.SourceFileLoader('pr_queue', str(SCRIPT))
    spec = importlib.util.spec_from_loader('pr_queue', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def hours_ago(hours):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - hours * 3600))


def node(number, owner, pushed=1.0, ci='SUCCESS', repo='o/r', title=None, body=None):
    title = title or f'VSTA-{number} work'
    if body is None:
        body = f'Owner chat: {owner}\n'
    return {
        'number': number,
        'url': f'https://github.com/{repo}/pull/{number}',
        'title': title,
        'body': body,
        'updatedAt': hours_ago(pushed),
        'repository': {'nameWithOwner': repo},
        'commits': {'nodes': [{'commit': {'committedDate': hours_ago(pushed)}}]},
        'statusCheckRollup': {'state': ci},
    }


GH_STUB = '''import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARGV = sys.argv[1:]
(ROOT / 'gh-calls.txt').open('a').write(' '.join(ARGV).replace('\\n', ' ') + '\\n')
EXIT = (ROOT / 'gh-exit.txt').read_text().strip()
if EXIT not in ('', '0'):
    sys.exit(int(EXIT))
PRS = json.loads((ROOT / 'prs.json').read_text())
if ARGV[:2] != ['api', 'graphql']:
    sys.stderr.write('gh fixture: unexpected ' + ' '.join(ARGV) + '\\n')
    sys.exit(3)
fields = {}
rest = iter(ARGV[3:])
for arg in rest:
    if arg in ('-f', '-F'):
        name, _, value = next(rest, '').partition('=')
        fields[name] = value
q = fields.get('q', '')
if 'repo:' in q:
    want = q.split('repo:', 1)[1].split()[0]
    prs = [p for p in PRS if p['repository']['nameWithOwner'] == want]
else:
    prs = PRS
after = int(fields.get('after') or 0)
page = prs[after:after + 100]
end = after + len(page)
print(json.dumps({'data': {'search': {
    'pageInfo': {'hasNextPage': end < len(prs), 'endCursor': None if end >= len(prs) else str(end)},
    'nodes': page}}}))
'''


class ModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def test_owner_from_body(self):
        self.assertEqual(self.m.owner_chat('Owner chat: PR Housekeeping\n'), 'PR Housekeeping')
        self.assertIsNone(self.m.owner_chat('no owner here'))

    def test_build_rows_keeps_only_mine(self):
        now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
        nodes = [node(1, 'Mine'), node(2, 'Other')]
        rows = self.m.build_rows(nodes, 'Mine', now, 72)
        self.assertEqual([r['number'] for r in rows], [1])

    def test_stale_next_action(self):
        now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
        rows = self.m.build_rows([node(1, 'Mine', pushed=100, ci='SUCCESS')], 'Mine', now, 72)
        self.assertTrue(rows[0]['stale'])
        self.assertIn('stale:', rows[0]['next_action'])


class CliTests(unittest.TestCase):
    def cli(self, prs, args=(), gh_exit=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            (root / 'prs.json').write_text(json.dumps(prs))
            (bin_dir / 'gh').write_text(f'#!{sys.executable}\n' + GH_STUB)
            (bin_dir / 'gh').chmod(0o755)
            (root / 'gh-exit.txt').write_text(str(gh_exit))
            env = {**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH']}
            return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                                  capture_output=True, text=True)

    def test_own_prs_listed_not_others(self):
        prs = [node(1, 'Owner'), node(2, 'Other Chat')]
        result = self.cli(prs, ('--mine', 'Owner'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('o/r#1', result.stdout)
        self.assertNotIn('o/r#2', result.stdout)

    def test_stale_exits_one(self):
        prs = [node(1, 'Owner', pushed=200)]
        result = self.cli(prs, ('--mine', 'Owner'))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('stale:', result.stdout)

    def test_missing_mine_exits_two(self):
        result = self.cli([node(1, 'Owner')])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('--mine', result.stderr)

    def test_gh_error_exits_two(self):
        result = self.cli([], gh_exit=1, args=('--mine', 'Owner'))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()