"""valentin-mode prints its version when it loads.

The version is a plain number: commits that touched the skill folder. version.sh
lives next to the skill and is run here in throwaway repos: one level with
origin/main, one a commit behind it, and one with no git at all. The load line in
SKILL.md has to keep calling it.
"""

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
LOAD_LINE = '!`sh "${CLAUDE_SKILL_DIR}/version.sh"`'
BULLET = '- **Version:** your first reply after loading names the version line above.'
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
    def test_the_skill_runs_the_version_script_at_load(self):
        text = SKILL.read_text()
        self.assertIn(LOAD_LINE, text)
        self.assertLess(text.index('# Valentin mode'), text.index(LOAD_LINE))

    def test_the_line_carries_no_version_prefix(self):
        text = SKILL.read_text()
        self.assertNotIn('Version: !`', text)
        self.assertIn('\n' + LOAD_LINE + '\n', text)

    def test_the_first_reply_names_the_version(self):
        body = SKILL.read_text()
        talking = body.index('## Talking to the user')
        self.assertIn(BULLET, body[talking:])


if __name__ == '__main__':
    unittest.main()
