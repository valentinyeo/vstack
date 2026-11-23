"""Tests for skills/pr-housekeeping/pr-queue: mine filter, staleness, exit codes. Fixtures only."""

import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

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
            env = {**os.environ, 'HOME': str(root), 'PATH': str(bin_dir) + ':' + os.environ['PATH']}
            return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                                  capture_output=True, text=True, cwd=root)

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


class CleanupLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pr-cleanup-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = mock.patch.dict(os.environ, HOME=str(self.root))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.m = load_script()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@invalid',
                 'commit', '-qm', 'base', '--allow-empty')
        self.git('branch', 'my-branch')
        self.git('branch', 'other-branch')
        self.git('remote', 'add', 'origin', 'https://github.com/o/r.git')
        cwd_patch = mock.patch.object(Path, 'cwd', return_value=self.repo)
        self.cwd = cwd_patch.start()
        self.addCleanup(cwd_patch.stop)
        self.own = node(1, 'Owner')
        self.own.update(headRefName='my-branch', headRefOid=self.git('rev-parse', 'HEAD').strip())
        now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
        self.row = self.m.build_rows([self.own], 'Owner', now, 72)[0]

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout

    def tick(self, rows=(), mine='Owner', merged=True):
        with mock.patch.object(self.m, 'gh_json', return_value={
                'state': 'closed', 'merged_at': hours_ago(1) if merged else None}) as gh:
            result = self.m.cleanup_rows(list(rows), mine, 'o/r')
        return result, gh

    def test_merged_pr_stays_visible_until_own_branch_is_gone(self):
        self.assertEqual(self.tick([self.row])[0], [])
        rows, gh = self.tick()
        self.assertEqual([r['cleanup'] for r in rows], [True])
        self.assertIn('--branch my-branch', rows[0]['next_action'])
        gh.assert_called_once_with(['api', 'repos/o/r/pulls/1'])
        self.assertEqual(self.tick()[0][0]['cleanup'], True, 'holds survive later ticks')
        self.git('branch', '-D', 'my-branch')
        self.assertEqual(self.tick()[0], [], 'another chat branch must not keep mine pending')

    def test_loop_exit_stays_nonzero_after_merge_until_cleaned(self):
        own = self.own
        with mock.patch.object(self.m, 'bulk_prs', side_effect=[[own], [], []]), \
                mock.patch.object(self.m, 'gh_json', return_value={'merged_at': hours_ago(1)}), \
                mock.patch('sys.stdout', new_callable=io.StringIO) as output:
            self.m.main(['--mine', 'Owner', '--repo', 'o/r'])
            self.assertEqual(self.m.main(['--mine', 'Owner', '--repo', 'o/r']), 1)
            self.assertIn('cleanup:', output.getvalue())
            self.assertIn('--branch my-branch', output.getvalue())
            self.git('branch', '-D', 'my-branch')
            self.assertEqual(self.m.main(['--mine', 'Owner', '--repo', 'o/r']), 0)

    def test_other_chat_cannot_see_or_retire_our_cleanup(self):
        self.tick([self.row])
        self.assertEqual(self.tick(mine='Other')[0], [])
        self.assertEqual(self.tick()[0][0]['cleanup'], True)

    def test_closed_unmerged_is_not_cleanup(self):
        self.tick([self.row])
        self.assertEqual(self.tick(merged=False)[0], [])
        self.assertIn('my-branch', self.git('branch', '--list'))

    def test_worker_repo_is_tracked_when_chat_is_elsewhere(self):
        (self.root / 'projects').mkdir()
        (self.root / 'projects/r').symlink_to(self.repo, target_is_directory=True)
        self.cwd.return_value = self.root
        self.tick([self.row])
        self.assertEqual(self.tick()[0][0]['cleanup'], True)

    def test_two_local_clones_keep_two_cleanup_records(self):
        other = self.root / 'projects/r'
        other.parent.mkdir()
        subprocess.run(['git', 'clone', '-q', str(self.repo), str(other)], check=True)
        subprocess.run(['git', '-C', str(other), 'remote', 'set-url', 'origin',
                        'https://github.com/o/r.git'], check=True)
        subprocess.run(['git', '-C', str(other), 'branch', 'my-branch', 'HEAD'], check=True)
        self.tick([self.row])
        self.assertEqual(len(self.tick()[0]), 2)
        self.git('branch', '-D', 'my-branch')
        rows, _ = self.tick()
        self.assertEqual(len(rows), 1)
        self.assertIn(str(other), rows[0]['next_action'])
        subprocess.run(['git', '-C', str(other), 'branch', '-D', 'my-branch'],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(other), 'branch', '-dr', 'origin/my-branch'],
                       check=True, capture_output=True)
        self.assertEqual(self.tick()[0], [])

    def test_chat_clone_without_the_worker_branch_cannot_hide_it(self):
        other = self.root / 'projects/r'
        other.parent.mkdir()
        subprocess.run(['git', 'clone', '-q', str(self.repo), str(other)], check=True)
        subprocess.run(['git', '-C', str(other), 'remote', 'set-url', 'origin',
                        'https://github.com/o/r.git'], check=True)
        subprocess.run(['git', '-C', str(other), 'branch', 'my-branch', 'HEAD'], check=True)
        self.git('branch', '-D', 'my-branch')
        self.tick([self.row])
        rows, _ = self.tick()
        self.assertEqual(len(rows), 1)
        self.assertIn(str(other), rows[0]['next_action'])

    def test_detached_worktree_is_not_mistaken_for_cleaned(self):
        tree = self.root / 'worker-tree'
        self.git('worktree', 'add', '-q', str(tree), 'my-branch')
        self.tick([self.row])
        subprocess.run(['git', '-C', str(tree), 'checkout', '--detach', '-q'], check=True)
        self.git('branch', '-D', 'my-branch')
        rows, _ = self.tick()
        self.assertEqual(rows[0]['cleanup'], True)
        self.assertIn('do not delete', rows[0]['next_action'])
        self.assertTrue(tree.exists())

    def test_worker_push_after_last_tick_uses_merged_head(self):
        self.tick([self.row])
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@invalid',
                 'commit', '-qm', 'worker fix', '--allow-empty')
        self.git('branch', '-f', 'my-branch', 'HEAD')
        with mock.patch.object(self.m, 'gh_json', return_value={
                'merged_at': hours_ago(1), 'head': {'sha': self.git('rev-parse', 'HEAD').strip()}}):
            rows = self.m.cleanup_rows([], 'Owner', 'o/r')
        self.assertIn('--branch my-branch', rows[0]['next_action'])

    def test_transferred_pr_is_not_our_cleanup(self):
        self.tick([self.row])
        with mock.patch.object(self.m, 'gh_json', return_value={
                'merged_at': hours_ago(1), 'body': 'Owner chat: Other'}):
            self.assertEqual(self.m.cleanup_rows([], 'Owner', 'o/r'), [])
        self.assertIn('my-branch', self.git('branch', '--list'))

    def test_reused_branch_does_not_get_a_delete_command(self):
        self.tick([self.row])
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@invalid',
                 'commit', '-qm', 'new work', '--allow-empty')
        self.git('branch', '-f', 'my-branch', 'HEAD')
        rows, _ = self.tick()
        self.assertEqual(rows[0]['cleanup'], True)
        self.assertNotIn('--apply', rows[0]['next_action'])
        self.assertIn('do not delete', rows[0]['next_action'])

    def test_failed_github_read_keeps_pending_record(self):
        self.tick([self.row])
        with mock.patch.object(self.m, 'gh_json', side_effect=self.m.GhError('offline')):
            with self.assertRaises(self.m.GhError):
                self.m.cleanup_rows([], 'Owner', 'o/r')
        self.assertEqual(self.tick()[0][0]['cleanup'], True)


if __name__ == '__main__':
    unittest.main()