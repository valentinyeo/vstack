#!/usr/bin/env python3
"""install links every chat onto one checkout, so only the shared one may run it.

A git worktree that ran install relinked every chat onto an unmerged branch
(VSTA-47). The guard compares the script's own resolved directory with
$HOME/.local/share/vstack and refuses anywhere else.

VSTA-135: VSTACK_INSTALL_ANYWHERE=1 must use a throwaway HOME so a worker test
install never rewires every chat's skills and bin links.
"""
import os
import pwd
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallGuard(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)

    def run_install(self, script, **extra):
        env = {k: v for k, v in os.environ.items()
               if k not in ('VSTACK_DIR', 'VSTACK_INSTALL_ANYWHERE')}
        env['HOME'] = str(self.home)
        env.update(extra)
        return subprocess.run(['bash', str(script)], env=env, text=True, capture_output=True)

    def shared_checkout(self):
        """A fake shared checkout: this install plus one skill, all under $HOME."""
        share = self.home / '.local' / 'share' / 'vstack'
        skill = share / 'skills' / 'valentin-mode'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('name: valentin-mode\n')
        shutil.copy2(ROOT / 'install', share / 'install')
        return share

    def test_refuses_a_checkout_that_is_not_the_shared_one(self):
        result = self.run_install(ROOT / 'install')
        self.assertEqual(result.returncode, 2, result.stderr)
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertIn('~/.local/share/vstack', lines[0])
        self.assertIn('throwaway HOME', lines[0])
        self.assertFalse((self.home / '.claude').exists())
        self.assertFalse((self.home / '.local' / 'share' / 'vstack').exists())

    def test_links_from_the_shared_checkout(self):
        share = self.shared_checkout()
        result = self.run_install(share / 'install')
        self.assertEqual(result.returncode, 0, result.stderr)
        link = self.home / '.claude' / 'skills' / 'valentin-mode'
        self.assertTrue(link.is_symlink(), result.stdout)
        self.assertEqual(link.resolve(), (share / 'skills' / 'valentin-mode').resolve())

    def test_escape_links_from_any_checkout(self):
        result = self.run_install(ROOT / 'install', VSTACK_INSTALL_ANYWHERE='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        link = self.home / '.claude' / 'skills' / 'valentin-mode'
        self.assertEqual(link.resolve(), (ROOT / 'skills' / 'valentin-mode').resolve())

    def test_escape_refuses_the_real_home(self):
        """A worker ran install with VSTACK_INSTALL_ANYWHERE=1 and rewired every chat."""
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        # The canonical share still points at the main checkout, not this worktree.
        share = self.home / '.local' / 'share' / 'vstack'
        share.mkdir(parents=True)
        env = {k: v for k, v in os.environ.items()
               if k not in ('VSTACK_DIR', 'VSTACK_INSTALL_ANYWHERE', 'HOME')}
        env['HOME'] = str(real_home)
        env['VSTACK_DIR'] = str(share)
        env['VSTACK_INSTALL_ANYWHERE'] = '1'
        result = subprocess.run(
            ['bash', str(ROOT / 'install')], env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('throwaway HOME', result.stderr)


if __name__ == '__main__':
    unittest.main()
