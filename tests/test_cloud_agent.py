"""Tests for skills/cloud-agent/cloud-agent: preflight, vendor output parsing and the exit contract.

Every fixture is text a vendor CLI really prints, a gh JSON shape, or a temp git repo with a fake
github origin. No test touches the network or starts a cloud agent."""

import contextlib
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

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/cloud-agent/cloud-agent'
PANE = '  Open Cloud Agent in: https://cursor.com/agents/bc-970b7d10-2ec0-4b74-ab61-deb21d0cb986'
REAL_ID = 'task_e_6af0b6c226208326ad137036b93bf744'
GITHUB = 'https://github.com/valentinyeo/example.git'


def load_script():
    loader = importlib.machinery.SourceFileLoader('cloud_agent', str(SCRIPT))
    spec = importlib.util.spec_from_loader('cloud_agent', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, check=True)


def make_repo(root, remote=GITHUB):
    """A repo whose origin says github.com and whose main has an origin/main upstream."""
    root.mkdir(parents=True)
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.name', 'Cloud Agent Test')
    git(root, 'config', 'user.email', 'cloud-agent@users.noreply.github.com')
    (root / 'README.md').write_text('# example\n')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'first commit')
    git(root, 'remote', 'add', 'origin', remote)
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    git(root, 'branch', '--set-upstream-to=origin/main', 'main')
    return root


def pull(number, branch, created, url=None):
    return {'number': number, 'headRefName': branch, 'url': url or f'https://github.com/o/r/pull/{number}',
            'createdAt': created}


class ModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def test_result_has_exactly_the_documented_keys_in_order(self):
        row = self.m.outcome('cursor', 'done', agent_url='u', task_id='bc-1', branch='cursor/x',
                             pr_url='p')
        self.assertEqual(list(row), ['vendor', 'status', 'agent_url', 'task_id', 'branch', 'pr_url', 'error'])
        self.assertIsNone(row['error'])

    def test_every_status_has_its_exit_code(self):
        self.assertEqual(self.m.exit_code('started'), 0)
        self.assertEqual(self.m.exit_code('done'), 0)
        self.assertEqual(self.m.exit_code('limit'), 75)
        self.assertEqual(self.m.exit_code('failed'), 1)
        self.assertEqual(self.m.exit_code('timeout'), 124)
        with self.assertRaises(ValueError):
            self.m.exit_code('nearly-done')

    def test_emit_prints_one_json_line_and_maps_the_exit(self):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.m.emit(self.m.outcome('codex', 'limit', task_id='task_e_1'))
        self.assertEqual(code, 75)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])['status'], 'limit')
        self.assertIn('429 limit', err.getvalue())

    def test_cursor_url_from_the_real_pane_line(self):
        url, task_id = self.m.extract_cursor_url(PANE)
        self.assertEqual(url, 'https://cursor.com/agents/bc-970b7d10-2ec0-4b74-ab61-deb21d0cb986')
        self.assertEqual(task_id, 'bc-970b7d10-2ec0-4b74-ab61-deb21d0cb986')

    def test_cursor_url_missing_while_it_checks_git_status(self):
        self.assertEqual(self.m.extract_cursor_url('  Checking git status'), (None, None))
        self.assertEqual(self.m.extract_cursor_url(''), (None, None))

    def test_cursor_task_id_is_the_bc_id_in_the_url(self):
        _, task_id = self.m.extract_cursor_url(PANE)
        self.assertTrue(task_id.startswith('bc-'))
        self.assertEqual(task_id, self.m.extract_cursor_url(PANE)[0].rsplit('/', 1)[1])

    def test_limit_detection_for_every_vendor(self):
        for text in ('Usage limit reached', 'rate limit hit', 'Quota exhausted',
                     'You have hit your usage limit. Resets in 3h.'):
            self.assertTrue(self.m.limit_hit(text), text)
        self.assertFalse(self.m.limit_hit('Task applied cleanly'))
        # Cursor also says "upgrade", the other vendors do not.
        self.assertTrue(self.m.cursor_limit_hit('Upgrade your plan to keep going'))
        self.assertFalse(self.m.limit_hit('Upgrade your plan to keep going'))
        self.assertFalse(self.m.cursor_limit_hit('Move to cloud agent'))

    def test_codex_task_id_and_url_from_exec_output(self):
        text = f'Submitted task {REAL_ID}\nhttps://chatgpt.com/codex/tasks/{REAL_ID}\n'
        self.assertEqual(self.m.codex_task(text),
                         (REAL_ID, f'https://chatgpt.com/codex/tasks/{REAL_ID}'))
        self.assertEqual(self.m.codex_task(f'task {REAL_ID}'), (REAL_ID, None))
        self.assertEqual(self.m.codex_task(f'see https://chatgpt.com/codex/tasks/{REAL_ID}'),
                         (REAL_ID, f'https://chatgpt.com/codex/tasks/{REAL_ID}'))
        self.assertEqual(self.m.codex_task('environment not found'), (None, None))

    def test_codex_status_words(self):
        ready = f'[READY] Add routing decision for cloud roles\ntoken-ladder  •  Nov  8 18:52'
        self.assertEqual(self.m.codex_state(ready), 'done')
        self.assertEqual(self.m.codex_state('[COMPLETED] x'), 'done')
        self.assertEqual(self.m.codex_state('[IN PROGRESS] x'), 'pending')
        self.assertEqual(self.m.codex_state('[PENDING] x'), 'pending')
        self.assertEqual(self.m.codex_state('[ERROR] x'), 'failed')
        self.assertEqual(self.m.codex_state('[FAILED] x'), 'failed')
        self.assertEqual(self.m.codex_state('something new from the vendor'), 'pending',
                         'an unknown word waits for --timeout instead of guessing')

    def test_pr_matching_needs_both_a_later_time_and_the_branch_prefix(self):
        launch = self.m.moment('2026-11-20T13:00:00Z').timestamp()
        rows = [pull(1, 'cursor/old', '2026-11-20T12:59:59Z'),
                pull(2, 'codex/other', '2026-11-20T13:01:00Z'),
                pull(3, 'cursor/right', '2026-11-20T13:02:00Z')]
        found = self.m.pr_after(rows, launch, 'cursor/')
        self.assertEqual(found['number'], 3)
        self.assertIsNone(self.m.pr_after(rows[:2], launch, 'cursor/'))
        self.assertIsNone(self.m.pr_after([pull(4, 'cursor/x', '2026-11-20T13:00:00Z')], launch, 'cursor/'),
                          'a PR created at the launch second is not after it')

    def test_pr_matching_takes_the_earliest_qualifying_pull_request(self):
        launch = time.time()
        later = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(launch + 120))
        sooner = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(launch + 60))
        found = self.m.pr_after([pull(9, 'claude/a', later), pull(8, 'claude/b', sooner)], launch, 'claude/')
        self.assertEqual(found['number'], 8)

    def test_pr_matching_reads_a_fractional_gh_timestamp(self):
        launch = self.m.moment('2026-11-20T13:00:00Z').timestamp()
        found = self.m.pr_after([pull(1, 'cursor/x', '2026-11-20T13:00:01.123Z')], launch, 'cursor/')
        self.assertEqual(found['number'], 1)

    def test_only_composer_and_grok_cursor_models(self):
        for model in ('composer-2.5', 'composer-2.5-fast', 'grok-4.7-high', 'grok-4.7-xhigh-fast',
                      'cursor-grok-4.6-high'):
            self.assertTrue(self.m.cursor_model_ok(model), model)
        for model in ('auto', 'claude-opus-5-high', 'gpt-5.3-codex', 'sonnet-4-thinking', '',
                      'grok-', 'composer-2.5-'):
            self.assertFalse(self.m.cursor_model_ok(model), model)

    def test_cursor_prompt_label(self):
        self.assertEqual(self.m.model_label('composer-2.5'), 'Composer 2.5')
        self.assertEqual(self.m.model_label('grok-4.7-high'), 'Grok 4.7')
        self.assertEqual(self.m.model_label('grok-'), 'Grok', 'an odd id must not crash the launch')

    def test_a_brief_that_mentions_a_rate_limit_is_not_a_vendor_limit(self):
        # Verified break, 2026-11-20: the pane still shows the brief the user typed, so reading the
        # whole pane made "fix the rate limit bug" report status limit, exit 75, and skip the lane.
        brief = "Fix the bug where the API says 'rate limit' when caching. Avoid quota errors."
        pane = 'Composer 2.5\n' + self.m.flatten(brief)
        self.assertFalse(self.m.cursor_limit_hit(self.m.submitted_tail(pane)))
        real = pane + '\nChecking git status\nUsage limit reached. Resets in 3h.'
        self.assertTrue(self.m.cursor_limit_hit(self.m.submitted_tail(real)))
        submitted = pane + '\nChecking git status\n' + PANE
        self.assertEqual(self.m.extract_cursor_url(self.m.submitted_tail(submitted))[0],
                         'https://cursor.com/agents/bc-970b7d10-2ec0-4b74-ab61-deb21d0cb986')

    def test_owner_repo_from_every_remote_form(self):
        for remote in ('git@github.com:valentinyeo/vstack.git',
                       'https://github.com/valentinyeo/vstack.git',
                       'https://github.com/valentinyeo/vstack',
                       'ssh://git@github.com/valentinyeo/vstack.git'):
            self.assertEqual(self.m.owner_repo(remote), 'valentinyeo/vstack', remote)
        self.assertIsNone(self.m.owner_repo('https://gitlab.com/o/r.git'))
        self.assertIsNone(self.m.owner_repo(''))

    def test_claude_url_and_exit_3_message(self):
        line = 'session https://claude.ai/code/session_01AbCdEfGhIjK ready'
        self.assertEqual(self.m.extract_claude_url(line), 'https://claude.ai/code/session_01AbCdEfGhIjK')
        refused = ('refused: the Claude GitHub App is not installed on valentinyeo/example, so the '
                   'session would get an upload that cannot push.')
        self.assertEqual(self.m.claude_error(3, refused), refused)
        self.assertIn('GitHub App', self.m.claude_error(3, ''))
        self.assertIsNone(self.m.claude_error(0, 'https://claude.ai/code/session_x'))
        self.assertIn('boom', self.m.claude_error(1, 'boom'))

    def test_codex_env_names_its_map_file_when_there_is_no_env(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'codex-envs.json'
            env, why = self.m.codex_env('valentinyeo/example', None, path=missing)
            self.assertIsNone(env)
            self.assertIn(str(missing), why)
            self.assertEqual(self.m.codex_env('valentinyeo/example', 'token-ladder', path=missing),
                             ('token-ladder', None), '--env wins without reading the file')
            missing.write_text(json.dumps({'valentinyeo/example': 'token-ladder'}))
            self.assertEqual(self.m.codex_env('valentinyeo/example', None, path=missing),
                             ('token-ladder', None))
            _, why = self.m.codex_env('valentinyeo/other', None, path=missing)
            self.assertIn('valentinyeo/other', why)

    def test_codex_log_never_reaches_the_pull_request(self):
        # The codex CLI writes error.log into its working directory. In the throwaway worktree a
        # `git add -A` would commit that debug log into the pull request.
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo')
            (repo / 'error.log').write_text('codex startup\n')
            self.m.drop_codex_log(repo)
            self.assertFalse((repo / 'error.log').exists(), 'an untracked codex log is removed')
            (repo / 'error.log').write_text('the repo keeps its own log\n')
            git(repo, 'add', 'error.log')
            git(repo, 'commit', '-q', '-m', 'track our own error.log')
            self.m.drop_codex_log(repo)
            self.assertTrue((repo / 'error.log').exists(), 'a tracked error.log is never deleted')

    def test_flatten_collapses_newlines_for_the_cursor_repl(self):
        self.assertEqual(self.m.flatten('Reply with the first heading.\n\nNo PR.\n'), 'Reply with the first heading. No PR.')


CODEX_STUB = '''
import pathlib, sys
args = sys.argv[1:]
if args[:2] == ['cloud', 'apply']:
    pathlib.Path('applied.txt').write_text('codex changed this\\n')
    pathlib.Path('error.log').write_text('vendor debug\\n')
    print('applied')
    sys.exit(0)
print('codex stub: unexpected ' + ' '.join(args), file=sys.stderr)
sys.exit(1)
'''

GH_STUB = '''
import sys
if sys.argv[1:3] == ['pr', 'create']:
    print('https://github.com/valentinyeo/example/pull/7')
    sys.exit(0)
print('gh stub: unexpected ' + ' '.join(sys.argv[1:]), file=sys.stderr)
sys.exit(1)
'''


class CodexPullRequestTests(unittest.TestCase):
    """The path that cannot be proven live today: apply, commit, push and gh pr create."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def test_a_ready_task_becomes_a_pushed_branch_and_pull_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / 'remote.git'
            subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
            repo = make_repo(root / 'repo', remote=str(remote))
            git(repo, 'push', '-q', 'origin', 'main')
            fake = root / 'bin'
            fake.mkdir()
            (fake / 'codex').write_text(f'#!{sys.executable}\n' + CODEX_STUB)
            (fake / 'gh').write_text(f'#!{sys.executable}\n' + GH_STUB)
            (fake / 'codex').chmod(0o755)
            (fake / 'gh').chmod(0o755)
            saved = self.m.BIN_DIRS
            self.m.BIN_DIRS = (fake,)
            try:
                row = self.m.codex_pull_request(
                    repo, 'valentinyeo/example', 'task_e_test',
                    'https://chatgpt.com/codex/tasks/task_e_test', 'Add the thing.\n')
            finally:
                self.m.BIN_DIRS = saved
            self.assertEqual(row['status'], 'done', row)
            self.assertEqual(row['branch'], 'codex/task_e_test')
            self.assertEqual(row['pr_url'], 'https://github.com/valentinyeo/example/pull/7')
            git(remote, 'rev-parse', '--verify', 'codex/task_e_test')
            self.assertEqual(git(repo, 'show', 'codex/task_e_test:applied.txt').stdout,
                             'codex changed this\n')
            log = subprocess.run(['git', '-C', str(repo), 'show', 'codex/task_e_test:error.log'],
                                 capture_output=True, text=True)
            self.assertNotEqual(log.returncode, 0, 'the codex debug log never reaches the branch')
            trees = [line for line in git(repo, 'worktree', 'list').stdout.splitlines() if line.strip()]
            self.assertEqual(len(trees), 1, 'the temporary worktree is removed')


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def test_a_clean_pushed_github_checkout_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo')
            self.assertIsNone(self.m.preflight(repo))

    def test_a_directory_that_is_not_git_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            why = self.m.preflight(directory)
            self.assertIn('not a git repository', why)

    def test_an_origin_off_github_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo', remote='https://gitlab.com/o/r.git')
            why = self.m.preflight(repo)
            self.assertIn('not on github.com', why)
            self.assertIn('gitlab.com', why)

    def test_no_upstream_fails_because_the_cloud_agent_clones_github(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo')
            git(repo, 'branch', '--unset-upstream')
            why = self.m.preflight(repo)
            self.assertIn('no upstream branch', why)

    def test_unpushed_commit_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo')
            (repo / 'local.txt').write_text('only on this VPS\n')
            git(repo, 'add', '-A')
            git(repo, 'commit', '-q', '-m', 'not pushed')
            why = self.m.preflight(repo)
            self.assertIn('commit(s) not on origin/main', why)
            self.assertIn('push them first', why)

    def test_uncommitted_tracked_change_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo')
            (repo / 'README.md').write_text('# example\nchanged and never committed\n')
            why = self.m.preflight(repo)
            self.assertIn('uncommitted tracked changes', why)
            self.assertIn('README.md', why)

    def test_an_untracked_file_passes_because_a_cloud_agent_cannot_see_it_anyway(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo')
            (repo / 'scratch.txt').write_text('local notes\n')
            self.assertIsNone(self.m.preflight(repo))


class CliTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                              env=dict(os.environ, HOME=tempfile.gettempdir()))

    def test_a_non_repo_prints_one_json_line_and_exits_one(self):
        with tempfile.TemporaryDirectory() as directory:
            brief = Path(directory) / 'brief.txt'
            brief.write_text('Reply with the first heading of README.md. Make no changes.\n')
            result = self.cli('cursor', '--repo', directory, '--brief', str(brief), '--no-wait')
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stdout + result.stderr)
        row = json.loads(lines[0])
        self.assertEqual(list(row), ['vendor', 'status', 'agent_url', 'task_id', 'branch', 'pr_url', 'error'])
        self.assertEqual(row['vendor'], 'cursor')
        self.assertEqual(row['status'], 'failed')
        self.assertIn('not a git repository', row['error'])
        self.assertIsNone(row['agent_url'])
        self.assertEqual(result.returncode, 1)

    def test_a_model_outside_the_plan_is_refused_before_any_launch(self):
        result = self.cli('cursor', '--repo', '/nowhere', '--brief', '/nowhere/brief.txt',
                          '--model', 'claude-opus-5-high', '--no-wait')
        row = json.loads(result.stdout.strip())
        self.assertEqual(row['status'], 'failed')
        self.assertIn('Composer 2.5 and Grok', row['error'])
        self.assertEqual(result.returncode, 1)

    def test_an_empty_brief_fails_with_a_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            brief = Path(directory) / 'brief.txt'
            brief.write_text('   \n')
            result = self.cli('codex', '--repo', directory, '--brief', str(brief), '--no-wait')
        row = json.loads(result.stdout.strip())
        self.assertEqual(row['status'], 'failed')
        self.assertIn('empty', row['error'])
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
