"""valentin-mode prints its version when it loads.

The version is a plain number: commits that touched the skill folder. version.sh
lives next to the skill and is run here in throwaway repos: one level with
origin/main, one a commit behind it, and one with no git at all. The skill's
context.py hook runs it at the chat's first tool call and hands the line over.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / 'skills/valentin-mode'
SCRIPT = SKILL_DIR / 'version.sh'
SKILL = SKILL_DIR / 'SKILL.md'
LOAD_HOOK = 'python3 "$CLAUDE_PLUGIN_ROOT/context.py"'
BULLET = '- **Version:** your first reply after loading names that version line.'
LATEST = re.compile(r'^valentin-mode v\d+ \(latest\)$')
BEHIND = re.compile(
    r'^valentin-mode v\d+, latest is v\d+ \(updates itself within 10 minutes\)$')


def git(cwd, *args):
    """Run git in a throwaway repo without touching the user's config."""
    return subprocess.run(
        ['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
         '-c', 'commit.gpgsign=false', *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=120, check=True).stdout


def run_version(folder, env=None):
    full = dict(os.environ, **(env or {}))
    return subprocess.run(['sh', str(folder / 'version.sh')], capture_output=True,
                          text=True, timeout=60, env=full)


class VersionScript(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)

    def copy_script(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / 'version.sh'
        shutil.copy2(SCRIPT, target)
        return target

    def build_repo(self):
        """A clone pushed to a bare origin, with origin/main tracked."""
        origin = self.tmp / 'origin.git'
        git(self.tmp, 'init', '--bare', str(origin))
        work = self.tmp / 'work'
        git(self.tmp, 'init', '-b', 'main', str(work))
        skill = work / 'skills/valentin-mode'
        self.copy_script(skill)
        (work / 'README.md').write_text('vstack\n')
        git(work, 'add', '-A')
        git(work, 'commit', '-m', 'v1')
        git(work, 'remote', 'add', 'origin', str(origin))
        git(work, 'push', 'origin', 'main')
        git(origin, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        git(work, 'fetch', 'origin')
        return work, origin

    def test_the_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK), 'version.sh must be executable')

    def test_level_with_origin_main_is_latest(self):
        work, _origin = self.build_repo()
        result = run_version(work / 'skills/valentin-mode')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'valentin-mode v1 (latest)')
        self.assertFalse(result.stderr, result.stderr)

    def test_the_count_is_the_number_of_commits_touching_the_folder(self):
        work, _origin = self.build_repo()
        skill = work / 'skills/valentin-mode'
        (skill / 'notes.md').write_text('a second commit on the skill\n')
        git(work, 'add', '-A')
        git(work, 'commit', '-m', 'v2 touches the skill')
        (skill / 'notes.md').write_text('a third commit on the skill\n')
        git(work, 'add', '-A')
        git(work, 'commit', '-m', 'v3 touches the skill')

        result = run_version(skill)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'valentin-mode v3 (latest)')

    def test_one_commit_behind_touching_the_folder_counts(self):
        work, origin = self.build_repo()
        other = self.tmp / 'other'
        git(self.tmp, 'clone', str(origin), str(other))
        with (other / 'skills/valentin-mode/version.sh').open('a') as handle:
            handle.write('\n# a later change\n')
        git(other, 'add', '-A')
        git(other, 'commit', '-m', 'v2 touches the skill')
        git(other, 'push', 'origin', 'main')
        git(work, 'fetch', 'origin')

        result = run_version(work / 'skills/valentin-mode')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            'valentin-mode v1, latest is v2 (updates itself within 10 minutes)')

    def test_a_commit_elsewhere_does_not_count(self):
        work, origin = self.build_repo()
        other = self.tmp / 'other'
        git(self.tmp, 'clone', str(origin), str(other))
        (other / 'README.md').write_text('vstack, but only the readme moved\n')
        git(other, 'add', '-A')
        git(other, 'commit', '-m', 'v2 touches another folder')
        git(other, 'push', 'origin', 'main')
        git(work, 'fetch', 'origin')

        result = run_version(work / 'skills/valentin-mode')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'valentin-mode v1 (latest)')

    def test_outside_git_says_unknown(self):
        folder = self.tmp / 'installed/valentin-mode'
        self.copy_script(folder)
        result = run_version(folder, {'GIT_CEILING_DIRECTORIES': str(self.tmp)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'valentin-mode version unknown')

    def test_this_checkout_prints_a_number(self):
        result = run_version(SKILL_DIR)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = result.stdout.strip()
        self.assertTrue(LATEST.match(line) or BEHIND.match(line), line)


class LoadLine(unittest.TestCase):
    def test_the_skill_turns_on_the_hook_that_loads_the_version(self):
        text = SKILL.read_text()
        self.assertIn(LOAD_HOOK, text)

    def test_the_hook_hands_the_chat_a_version_line(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                ['python3', str(SKILL_DIR / 'context.py')],
                input='{"session_id": "load-line"}', capture_output=True, text=True,
                timeout=60, env=dict(os.environ, HOME=home))
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
        first = context.splitlines()[0]
        self.assertTrue(LATEST.match(first) or BEHIND.match(first),
                        'the hook hands over the version line, got %r' % first)

    def test_the_body_carries_no_shell_load_line(self):
        body = SKILL.read_text().split('---', 2)[2]
        self.assertNotIn('!`', body, 'a line the chat may skip is not a load')

    def test_the_first_reply_names_the_version(self):
        body = SKILL.read_text()
        talking = body.index('## Talking to the user')
        self.assertIn(BULLET, body[talking:])


if __name__ == '__main__':
    unittest.main()
