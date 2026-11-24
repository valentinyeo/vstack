"""Open pull requests stay capped on the repos that commit straight to master (VSTA-204).

valentinyeo/multiprompt held 77 open PRs on 24 Nov 2026 while its CLAUDE.md says open none.
The cap lives in scripts/pr-cap.py; hooks/pr-cap-guard.py asks it before every command form
that opens a PR, and scripts/worker-shims gives pacer workers a `gh` shim that asks the same
module. Every test uses a fake `gh` and a scratch HOME; nothing here reaches GitHub.
"""
import json
import os
from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/pr-cap-guard.py'
SHIMS = ROOT / 'scripts/worker-shims'
REPO = 'valentinyeo/multiprompt'
ANDROID = 'valentinyeo/multiprompt-android'
OTHER = 'valentinyeo/other'
FIX = "commit small units to master per the repo's CLAUDE.md; close or land open PRs first"
COUNT_QUERY = 'search/issues'

FAKE_GH = '''#!/bin/sh
printf '%s\\n' "$*" >> "$PR_CAP_LOG"
case "$*" in
  *{query}*) cat "$PR_CAP_COUNT" ;;
  *) printf 'opened: %s\\n' "$*" ;;
esac
'''


class Scratch:
    """A scratch HOME, a fake `gh` that answers the count, and a git repo to stand in a cwd."""

    def __init__(self, test):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(__import__('shutil').rmtree, self.dir, ignore_errors=True)
        self.home = self.dir / 'home'
        self.home.mkdir()
        self.bin = self.dir / 'bin'
        self.bin.mkdir()
        self.count = self.dir / 'count'
        self.log = self.dir / 'calls.log'
        self.project = self.dir / 'project'
        self.project.mkdir()
        self.set_count(0)
        self.gh = self.bin / 'gh'
        self.write_gh(FAKE_GH.format(query=COUNT_QUERY))

    def write_gh(self, text):
        self.gh.write_text(text)
        self.gh.chmod(0o755)

    def set_count(self, value):
        self.count.write_text(f'{value}\n')

    def calls(self):
        try:
            return [line for line in self.log.read_text().splitlines() if line.strip()]
        except OSError:
            return []

    def env(self, **extra):
        return {**os.environ, 'HOME': str(self.home), 'PR_CAP_COUNT': str(self.count),
                'PR_CAP_LOG': str(self.log), 'PYTHONDONTWRITEBYTECODE': '1',
                'PATH': f'{self.bin}{os.pathsep}{os.environ.get("PATH", "")}', **extra}

    def remote(self, url):
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        subprocess.run(['git', '-C', str(self.project), 'remote', 'add', 'origin', url],
                       check=True)
        return self.project


def hook(scratch, payload):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, timeout=60, env=scratch.env())


def bash(scratch, command, cwd=None):
    return hook(scratch, {'tool_name': 'Bash', 'cwd': str(cwd or scratch.project),
                          'tool_input': {'command': command}})


def mcp(scratch, owner, repo):
    return hook(scratch, {'tool_name': 'mcp__github__create_pull_request',
                          'tool_input': {'owner': owner, 'repo': repo}})


CREATE_FORMS = (
    f'gh pr create -R {REPO} --title "small unit"',
    f'gh pr create --repo {ANDROID} --title "small unit"',
    f'gh pr create --repo={REPO} --title "small unit"',
    f'timeout 300 gh pr create -R {REPO} --title "small unit"',
    f'gh api repos/{REPO}/pulls -X POST -f title=unit',
    f'gh api --method POST repos/{ANDROID}/pulls',
    f'gh api repos/{REPO}/pulls -f title=unit',
)


class Count(unittest.TestCase):
    def test_count_11_refuses_every_create_form(self):
        for command in CREATE_FORMS:
            with self.subTest(command=command):
                scratch = Scratch(self)
                scratch.set_count(11)
                result = bash(scratch, command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('11 open pull requests', result.stderr)
                self.assertIn('cap of 10', result.stderr)
                self.assertIn(FIX, result.stderr)

    def test_count_11_refuses_the_cwd_remote_form(self):
        scratch = Scratch(self)
        scratch.set_count(11)
        project = scratch.remote(f'https://github.com/{REPO}.git')
        result = bash(scratch, 'gh pr create --title "small unit"', cwd=project)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(REPO, result.stderr)
        self.assertIn('11 open pull requests', result.stderr)

    def test_count_11_refuses_the_mcp_create_tool(self):
        scratch = Scratch(self)
        scratch.set_count(11)
        result = mcp(scratch, 'valentinyeo', 'multiprompt')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(REPO, result.stderr)
        self.assertIn('cap of 10', result.stderr)

    def test_count_10_opens_and_reads_pass(self):
        for command in (CREATE_FORMS + (f'gh pr view 1 -R {REPO}',
                                        f'gh api repos/{REPO}/pulls')):
            with self.subTest(command=command):
                scratch = Scratch(self)
                scratch.set_count(10)
                result = bash(scratch, command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')

    def test_count_10_opens_the_mcp_tool(self):
        scratch = Scratch(self)
        scratch.set_count(10)
        self.assertEqual(mcp(scratch, 'valentinyeo', 'multiprompt').returncode, 0)

    def test_another_repo_passes_without_a_github_call(self):
        scratch = Scratch(self)
        scratch.set_count(11)
        result = bash(scratch, f'gh pr create -R {OTHER} --title unit')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(scratch.calls(), [])

    def test_a_read_failure_fails_open_with_one_warning_line(self):
        scratch = Scratch(self)
        scratch.write_gh('#!/bin/sh\necho "HTTP 503: unavailable" >&2\nexit 1\n')
        result = bash(scratch, f'gh pr create -R {REPO} --title unit')
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertIn('pr-cap:', lines[0])
        self.assertIn(REPO, lines[0])
        self.assertIn('allowing this one', lines[0])

    def test_one_count_call_serves_five_minutes(self):
        scratch = Scratch(self)
        scratch.set_count(11)
        command = f'gh pr create -R {REPO} --title unit'
        self.assertEqual(bash(scratch, command).returncode, 2)
        self.assertEqual(bash(scratch, command).returncode, 2)
        self.assertEqual(len(scratch.calls()), 1, scratch.calls())
        cache = scratch.home / '.local/state/vstack/pr-cap' / 'valentinyeo-multiprompt.json'
        saved = json.loads(cache.read_text())
        cache.write_text(json.dumps({'count': saved['count'], 'at': time.time() - 301}))
        self.assertEqual(bash(scratch, command).returncode, 2)
        self.assertEqual(len(scratch.calls()), 2, scratch.calls())

    def test_the_owner_module_holds_the_table(self):
        spec = importlib.util.spec_from_file_location('pr_cap_table', ROOT / 'scripts/pr-cap.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.REPOS, {REPO: 10, ANDROID: 10})
        self.assertIn('CLAUDE.md', module.FIX)


class WorkerShim(unittest.TestCase):
    def generate(self, scratch):
        out = scratch.dir / 'shims'
        result = subprocess.run([sys.executable, str(SHIMS), '--dir', str(out),
                                 '--path', str(scratch.bin), '--pr-cap-hook', str(HOOK)],
                                text=True, capture_output=True, timeout=60,
                                env=scratch.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        return out

    def run_shim(self, scratch, out, *args):
        return subprocess.run([str(out / 'gh'), *args], text=True, capture_output=True,
                              timeout=60, cwd=str(scratch.project),
                              env=scratch.env(PATH=f'{out}{os.pathsep}{scratch.bin}'
                                                   f'{os.pathsep}{os.environ.get("PATH", "")}'))

    def test_the_gh_shim_refuses_above_the_cap_without_running_gh(self):
        scratch = Scratch(self)
        scratch.set_count(11)
        out = self.generate(scratch)
        result = self.run_shim(scratch, out, 'pr', 'create', '-R', REPO, '--title', 'unit')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('11 open pull requests', result.stderr)
        self.assertIn(FIX, result.stderr)
        self.assertNotIn('opened:', result.stdout)

    def test_the_gh_shim_runs_gh_at_the_cap(self):
        scratch = Scratch(self)
        scratch.set_count(10)
        out = self.generate(scratch)
        result = self.run_shim(scratch, out, 'pr', 'create', '-R', REPO, '--title', 'unit')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('opened:', result.stdout)
        self.assertEqual(self.check(scratch, out), 0)

    def check(self, scratch, out):
        return subprocess.run([sys.executable, str(SHIMS), '--check', '--dir', str(out),
                               '--path', str(scratch.bin), '--pr-cap-hook', str(HOOK)],
                              capture_output=True, text=True, timeout=60,
                              env=scratch.env()).returncode


class Wiring(unittest.TestCase):
    def test_the_hook_is_registered_and_installed_for_workers(self):
        settings = json.loads((ROOT / '.claude/settings.json').read_text())
        commands = [hook.get('command', '')
                    for group in settings['hooks']['PreToolUse']
                    for hook in group.get('hooks', [])]
        self.assertTrue(any('pr-cap-guard.py' in command for command in commands), commands)
        install = (ROOT / 'install').read_text()
        self.assertIn('--pr-cap-hook', install)
        self.assertIn('pr-cap-guard.py', install)


if __name__ == '__main__':
    unittest.main()
