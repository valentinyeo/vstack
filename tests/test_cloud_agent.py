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
from unittest.mock import patch

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
        found = self.m.pr_after(rows, launch, ['cursor/'])
        self.assertEqual(found['number'], 3)
        self.assertIsNone(self.m.pr_after(rows[:2], launch, ['cursor/']))
        self.assertIsNone(self.m.pr_after([pull(4, 'cursor/x', '2026-11-20T13:00:00Z')], launch, ['cursor/']),
                          'a PR created at the launch second is not after it')

    def test_pr_matching_takes_the_earliest_qualifying_pull_request(self):
        launch = time.time()
        later = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(launch + 120))
        sooner = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(launch + 60))
        found = self.m.pr_after([pull(9, 'claude/a', later), pull(8, 'claude/b', sooner)], launch, ['claude/'])
        self.assertEqual(found['number'], 8)

    def test_pr_matching_reads_a_fractional_gh_timestamp(self):
        launch = self.m.moment('2026-11-20T13:00:00Z').timestamp()
        found = self.m.pr_after([pull(1, 'cursor/x', '2026-11-20T13:00:01.123Z')], launch, ['cursor/'])
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
        pane = 'Composer 2.5\n' + brief
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

    def test_paste_token_counts_the_briefs_newlines_plus_one(self):
        # The real pane, 2026-11-23: 60 lines no trailing newline showed +60, with one showed +61.
        self.assertEqual(self.m.expected_paste_lines('a\nb\nc'), 3)
        self.assertEqual(self.m.expected_paste_lines('a\nb\nc\n'), 4)
        self.assertEqual(self.m.expected_paste_lines('one flat line'), 1)
        self.assertEqual(self.m.brief_line_count('a\nb\nc\n'), 3, 'a trailing newline adds no line')
        self.assertEqual(self.m.paste_token_lines('& [Pasted text #1 +61 lines]'), 61)
        self.assertIsNone(self.m.paste_token_lines('& plain typed text'))

    def test_a_short_token_is_a_shortfall_and_a_whole_brief_is_not(self):
        brief = 'a\nb\nc'
        self.assertEqual(self.m.paste_shortfall('& [Pasted text #1 +2 lines]', brief), (2, 3))
        self.assertIsNone(self.m.paste_shortfall('& [Pasted text #1 +3 lines]', brief))
        self.assertIsNone(self.m.paste_shortfall('& a b c', brief), 'a short brief shows inline')

    def test_pr_matching_also_accepts_the_checkout_branch_name(self):
        launch = self.m.moment('2026-11-20T13:00:00Z').timestamp()
        rows = [pull(1, 'cursor/other', '2026-11-20T13:02:00Z'),
                pull(2, 'vsta-120-cloud-launch', '2026-11-20T13:01:00Z')]
        found = self.m.pr_after(rows, launch, ['cursor/', 'vsta-120-cloud-launch'])
        self.assertEqual(found['number'], 2)

    def test_cursor_push_dialog_pattern_matches_real_wording(self):
        text = ('Branch Not Pushed. Push to remote before kicking off agent? '
                '[y] Push [n] Cancel')
        self.assertTrue(self.m.CURSOR_PUSH_DIALOG.search(text))


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

    def test_a_local_only_branch_is_pushed_before_cursor_can_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / 'remote.git'
            subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
            repo = make_repo(root / 'repo', remote=GITHUB)
            git(repo, 'config', f'url.{remote.as_uri()}.insteadOf', GITHUB)
            git(repo, 'push', '-q', 'origin', 'main')
            git(repo, 'checkout', '-q', '-b', 'vsta-120-tip')
            git(repo, 'branch', '--set-upstream-to=origin/main', 'vsta-120-tip')
            self.assertIsNone(self.m.preflight(repo))
            git(remote, 'rev-parse', '--verify', 'vsta-120-tip')


class CursorLaunchFailureTests(unittest.TestCase):
    """launch_cursor must return failed rows, not crash, when the pane never reaches a step."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def test_prompt_bar_timeout_emits_one_json_line_and_exits_one(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo')
            ok = subprocess.CompletedProcess([], 0, '', '')
            pane_snippet = 'cursor-agent booting\nstill no Composer label\n'

            def fake_run(args, cwd=None, timeout=None):
                if args and 'capture-pane' in args:
                    return subprocess.CompletedProcess(args, 0, pane_snippet, '')
                return ok

            with patch.object(self.m, 'run', side_effect=fake_run), \
                    patch.object(self.m, 'poll', return_value=None), \
                    patch.object(self.m, 'quiet'):
                row = self.m.launch_cursor(repo, 'Do the thing.', 'composer-2.5', True, 60)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.m.emit(row)
            lines = out.getvalue().strip().splitlines()
            self.assertEqual(len(lines), 1, out.getvalue())
            parsed = json.loads(lines[0])
            self.assertEqual(parsed['status'], 'failed')
            self.assertEqual(parsed['vendor'], 'cursor')
            self.assertEqual(code, 1)
            self.assertIn('never appeared', parsed['error'] or '')
            self.assertIn('Composer 2.5', parsed['error'] or '')

    def test_push_dialog_gets_y_while_waiting_for_the_agent_url(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo')
            pane_snippet = ('Checking git status\n'
                            'Branch Not Pushed. Push to remote before kicking off agent?\n'
                            '[y] Push [n] Cancel\n')

            def fake_run(args, cwd=None, timeout=None):
                if args and 'send-keys' in args and args[-1] == 'y':
                    nonlocal pane_snippet
                    pane_snippet = (pane_snippet + '  Open Cloud Agent in: '
                                    + PANE.split(':', 1)[1].strip() + '\n')
                    return subprocess.CompletedProcess(args, 0, '', '')
                if args and 'capture-pane' in args:
                    return subprocess.CompletedProcess(args, 0, pane_snippet, '')
                return subprocess.CompletedProcess(args or [], 0, '', '')

            with patch.object(self.m, 'run', side_effect=fake_run), \
                    patch.object(self.m, 'quiet'):
                text = self.m.wait_cursor_agent_url('tmux', 'sess', lambda: pane_snippet, 5)
            self.assertIsNotNone(text)
            self.assertEqual(self.m.extract_cursor_url(text)[0],
                             'https://cursor.com/agents/bc-970b7d10-2ec0-4b74-ab61-deb21d0cb986')


LONG_BRIEF = '\n'.join(
    f'Line {number}: fix https://example.com/doc/{number} and keep `code_{number}` quoted as '
    f'"value {number}".'
    for number in range(1, 61))


def cursor_pane(paste_lines, extra=''):
    """The cursor REPL with a whole-brief paste token, the way the real pane draws one."""
    return (f'& [Pasted text #1 +{paste_lines} lines]\n'
            f'^ Move to cloud agent\nComposer 2.5                    Run Everything\n{extra}')


class CursorBriefPasteTests(unittest.TestCase):
    """A long brief must reach cursor whole and then submit, however the pane stalls on Enter.

    Labelled break, 2026-11-23: a 60-line brief typed with send-keys collapsed into
    `[Pasted text #1 +1 lines]` and the single Enter after it was ignored, so the launcher reported
    no cloud agent URL 240s later while the brief never left the prompt.
    """

    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def launch(self, pane_for, brief=LONG_BRIEF):
        """Launch cursor against a fake tmux. Returns (row, enters, pasted brief text)."""
        state = {'enters': 0, 'reads': 0, 'buffer': None}
        ok = subprocess.CompletedProcess([], 0, '', '')

        def fake_run(args, cwd=None, timeout=None):
            if 'capture-pane' in args:
                state['reads'] += 1
                return subprocess.CompletedProcess(args, 0, pane_for(state), '')
            if 'load-buffer' in args:
                state['buffer'] = Path(args[-1]).read_text()
                return ok
            if 'send-keys' in args and args[-1] == 'Enter':
                state['enters'] += 1
            return ok

        timers = dict(CURSOR_PROMPT_SECONDS=0, CURSOR_CLOUD_SECONDS=0, CURSOR_PASTE_LAND_SECONDS=0,
                      CURSOR_PASTE_SETTLE_SECONDS=0, CURSOR_ENTER_CONFIRM_SECONDS=0.2,
                      CURSOR_SUBMIT_SECONDS=1)
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / 'repo')
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(self.m, 'run', side_effect=fake_run))
                stack.enter_context(patch.object(self.m, 'quiet'))
                stack.enter_context(patch.object(self.m.time, 'sleep'))
                for name, value in timers.items():
                    stack.enter_context(patch.object(self.m, name, value, create=True))
                row = self.m.launch_cursor(repo, brief, 'composer-2.5', True, 60)
        return row, state['enters'], state['buffer']

    def test_the_whole_brief_is_pasted_with_every_line_and_no_flattening(self):
        row, enters, pasted = self.launch(lambda pane: cursor_pane(60, PANE))
        self.assertEqual(pasted, LONG_BRIEF)
        self.assertEqual(row['status'], 'started')
        self.assertEqual(enters, 1)

    def test_a_collapsed_paste_and_an_ignored_first_enter_still_submit(self):
        def pane_for(pane):
            if pane['enters'] < 2:
                return cursor_pane(60)
            return cursor_pane(60, 'Checking git status\n  ' + PANE.strip())

        row, enters, _ = self.launch(pane_for)
        self.assertEqual(enters, 2, 'cursor ignored the first Enter after the paste')
        self.assertEqual(row['status'], 'started')
        self.assertTrue((row['task_id'] or '').startswith('bc-'))

    def test_checking_git_status_keeps_waiting_for_the_url(self):
        # The live proof, 2026-11-23: `Checking git status` confirmed the Enter, the URL arrived
        # about 30s later, and stopping at the confirmation reported a failed launch.
        def pane_for(pane):
            if pane['reads'] < 6:
                return cursor_pane(60, 'Checking git status\n')
            return cursor_pane(60, 'Checking git status\n  ' + PANE.strip())

        row, enters, _ = self.launch(pane_for)
        self.assertEqual(enters, 1)
        self.assertEqual(row['status'], 'started')

    def test_three_ignored_enters_fail_once_with_the_counts_in_the_error(self):
        row, enters, _ = self.launch(lambda pane: cursor_pane(60))
        self.assertEqual(enters, 3)
        self.assertEqual(row['status'], 'failed')
        self.assertIn('3 Enter presses', row['error'] or '')

    def test_a_short_paste_token_stops_the_launch_before_any_enter(self):
        row, enters, _ = self.launch(lambda pane: cursor_pane(2), brief=LONG_BRIEF + '\n')
        self.assertEqual(enters, 0, 'a brief cursor only half received must never be submitted')
        self.assertEqual(row['status'], 'failed')
        self.assertIn('2 of the 61 lines', row['error'] or '')
        self.assertIn('60-line brief', row['error'] or '')


class PlanGateTests(unittest.TestCase):
    def setUp(self):
        self.m = load_script()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.gate = self.home / '.local/bin/plan-pick'
        self.gate.parent.mkdir(parents=True)
        home = patch.object(self.m, 'HOME', self.home)
        home.start()
        self.addCleanup(home.stop)

    def gate_script(self, code, reason=''):
        self.gate.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "' + str(self.home / 'args') + '"\n'
                             'printf "%s\\n" "' + reason + '"\nexit ' + str(code) + '\n')
        self.gate.chmod(0o755)

    def invoke(self, vendor):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(self.m, 'read_brief', return_value='Do the task.'), \
                patch.object(self.m, 'preflight', return_value=None) as preflight, \
                patch.object(self.m, 'launch_cursor', return_value=self.m.outcome('cursor', 'started')) as cursor, \
                patch.object(self.m, 'launch_codex', return_value=self.m.outcome('codex', 'started')) as codex, \
                patch.object(self.m, 'launch_claude', return_value=self.m.outcome('claude', 'started')) as claude, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.m.main([vendor, '--repo', str(self.home), '--brief', 'brief.txt', '--no-wait'])
        row = json.loads(out.getvalue())
        return code, row, err.getvalue(), preflight, (cursor, codex, claude)

    def test_skipped_lane_refuses_every_vendor_before_preflight_or_launch(self):
        for vendor in self.m.VENDORS:
            with self.subTest(vendor=vendor):
                reason = f'{vendor}: limited until 2026-12-23 19:35 UTC'
                self.gate_script(3, reason)
                code, row, err, preflight, launches = self.invoke(vendor)
                self.assertEqual(code, 75)
                self.assertEqual(row['status'], 'limit')
                self.assertIn(reason, row['error'])
                self.assertIn(reason, err)
                self.assertIn('plan-pick --run', err)
                self.assertEqual((self.home / 'args').read_text().splitlines(), ['--lane-ok', vendor, '--cloud'])
                preflight.assert_not_called()
                for launch in launches:
                    launch.assert_not_called()

    def test_allowed_lane_reaches_only_the_selected_vendor(self):
        self.gate_script(0, 'allowed')
        for index, vendor in enumerate(self.m.VENDORS):
            with self.subTest(vendor=vendor):
                code, row, err, preflight, launches = self.invoke(vendor)
                self.assertEqual(code, 0)
                self.assertEqual(row['status'], 'started')
                self.assertNotIn('warning', err.lower())
                preflight.assert_called_once()
                self.assertEqual([launch.call_count for launch in launches], [int(i == index) for i in range(3)])

    def test_missing_plan_pick_warns_and_fails_open(self):
        code, row, err, preflight, launches = self.invoke('cursor')
        self.assertEqual(code, 0)
        self.assertEqual(row['status'], 'started')
        self.assertIn('warning', err.lower())
        self.assertIn('plan-pick', err)
        self.assertIn('missing', err)
        self.assertEqual(len(err.splitlines()), 1)
        launches[0].assert_called_once()

    def test_installed_but_old_or_broken_plan_pick_does_not_fail_open(self):
        for gate_code in (1, 2, 124, 126):
            with self.subTest(gate_code=gate_code):
                self.gate_script(gate_code, 'eligibility check failed')
                code, row, err, preflight, launches = self.invoke('cursor')
                self.assertEqual(code, 1)
                self.assertEqual(row['status'], 'failed')
                self.assertIn('plan-pick', row['error'])
                self.assertIn(str(gate_code), row['error'])
                preflight.assert_not_called()
                for launch in launches:
                    launch.assert_not_called()

    def test_gate_timeout_refuses_without_launching(self):
        self.gate_script(0)
        with patch.object(self.m, 'run', return_value=subprocess.CompletedProcess([], 124, '', 'timed out')):
            code, row, err, preflight, launches = self.invoke('cursor')
        self.assertEqual(code, 1)
        self.assertIn('124', row['error'])
        preflight.assert_not_called()
        for launch in launches:
            launch.assert_not_called()


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
