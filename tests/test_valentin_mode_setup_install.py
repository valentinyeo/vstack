#!/usr/bin/env python3
"""Every hook named in skills/valentin-mode/setup.md must be linked by install."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / 'skills' / 'valentin-mode' / 'setup.md'
INSTALL = ROOT / 'install'


def hooks_named_in_setup():
    text = SETUP.read_text()
    return re.findall(r'\|\s*`([^`]+\.py)`\s*\|', text)


class ValentinModeSetupInstall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)

    def run_install(self):
        env = {k: v for k, v in os.environ.items() if k not in ('VSTACK_DIR', 'VSTACK_INSTALL_ANYWHERE')}
        env['HOME'] = str(self.home)
        env['VSTACK_DIR'] = str(self.home / '.local' / 'share' / 'vstack')
        env['VSTACK_INSTALL_ANYWHERE'] = '1'
        return subprocess.run(
            ['bash', str(INSTALL)], env=env, text=True, capture_output=True, timeout=120,
        )

    def test_install_links_every_hook_named_in_setup(self):
        hooks = hooks_named_in_setup()
        self.assertGreater(len(hooks), 0, 'setup.md names no .py hooks in its table')
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        hooks_dir = self.home / '.claude' / 'hooks'
        for name in hooks:
            link = hooks_dir / name
            with self.subTest(hook=name):
                self.assertTrue(link.is_symlink(), f'missing link {link}')
                self.assertEqual(link.resolve(), (ROOT / 'hooks' / name).resolve())


if __name__ == '__main__':
    unittest.main()