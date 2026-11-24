"""A chat whose PATH leaves out ~/.local/bin still finds yeo-key and hypertask (VSTA-234).

Each case runs the real tool with PATH=/usr/bin:/bin and a fake binary in
$HOME/.local/bin, which is where this server installs both CLIs.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
BARE_PATH = '/usr/bin:/bin'
KEY = 'sk-test-key-do-not-log'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def plant(home, name, body):
    path = Path(home) / '.local' / 'bin' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\n' + body)
    path.chmod(0o755)
    return path


class Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, self.dir, ignore_errors=True)
        self.home = self.dir / 'home'
        self.home.mkdir()
        patcher = patch.dict(os.environ, {'HOME': str(self.home), 'PATH': BARE_PATH})
        patcher.start()
        self.addCleanup(patcher.stop)


class FindTest(Scratch):
    def setUp(self):
        super().setUp()
        self.module = load('bin_path_under_test', SCRIPTS / 'bin_path.py')

    def test_finds_the_servers_own_copy_when_path_has_none(self):
        path = plant(self.home, 'yeo-key', 'exit 0\n')
        self.assertEqual(self.module.find('yeo-key'), str(path))
        self.assertEqual(self.module.yeo_key(), str(path))

    def test_path_still_wins(self):
        elsewhere = self.dir / 'elsewhere'
        elsewhere.mkdir()
        first = elsewhere / 'yeo-key'
        first.write_text('#!/bin/sh\nexit 0\n')
        first.chmod(0o755)
        plant(self.home, 'yeo-key', 'exit 0\n')
        with patch.dict(os.environ, {'PATH': str(elsewhere) + ':' + BARE_PATH}):
            self.assertEqual(self.module.find('yeo-key'), str(first))

    def test_answers_none_when_nowhere_has_it(self):
        self.assertIsNone(self.module.find('yeo-key'))
        self.assertIsNone(self.module.hypertask())


class ExcalidrawTest(Scratch):
    def setUp(self):
        super().setUp()
        plant(self.home, 'yeo-key', 'printf "%s\\n" ' + KEY + '\n')
        self.module = load('excalidraw_path_under_test',
                           ROOT / 'skills/excalidraw/excalidraw-share')

    def test_read_key_reaches_yeo_key_in_local_bin(self):
        self.assertEqual(self.module.read_key(), KEY)

    def test_missing_yeo_key_still_names_the_install(self):
        (self.home / '.local' / 'bin' / 'yeo-key').unlink()
        with self.assertRaises(self.module.ShareError) as caught:
            self.module.read_key()
        self.assertIn('~/.local/share/vstack/install', str(caught.exception))


class BoardDrainTest(Scratch):
    """pr-park and wip-cap read the board through reconcile.api, off PATH."""

    def setUp(self):
        super().setUp()
        self.log = self.dir / 'calls.log'
        plant(self.home, 'hypertask',
              'printf "%s\\n" "$*" >> ' + str(self.log) + '\n'
              'printf \'{"success": true, "connected_agent": {"id": "agent-1"}}\'\n')
        self.reconcile = load('reconcile_path_under_test',
                              ROOT / 'skills/hypertask-work/reconcile')

    def test_api_calls_the_copy_in_local_bin(self):
        self.assertEqual(self.reconcile.api('context')['connected_agent']['id'], 'agent-1')
        self.assertEqual(self.log.read_text().strip(), '--json context')

    def test_wip_cap_loads_with_the_same_bare_path(self):
        wip = load('wip_cap_path_under_test', ROOT / 'skills/board-drain/wip-cap')
        self.assertEqual(wip.cap_for('Vstack'), 5)


class LeaseTest(Scratch):
    def setUp(self):
        super().setUp()
        self.token = self.dir / 'token'
        self.token.write_text('stub-token\n')
        plant(self.home, 'hypertask', 'printf \'{"tasks": [{}]}\'\nexit 0\n')
        self.lease = load('lease_path_under_test', ROOT / 'skills/hypertask-work/lease')

    def test_take_card_reaches_the_copy_in_local_bin(self):
        self.assertTrue(self.lease.take_card('VSTA-234', 'Vstack', self.token,
                                             env=dict(os.environ)))


class IdleStopTest(Scratch):
    def setUp(self):
        super().setUp()
        self.path = plant(self.home, 'hypertask', 'exit 0\n')
        self.module = load('idle_stop_path_under_test',
                           ROOT / 'skills/responsive-mode/idle-stop.py')

    def test_cli_falls_back_to_local_bin(self):
        os.environ.pop('IDLE_STOP_CLI', None)
        self.assertEqual(self.module.cli(), str(self.path))

    def test_the_stub_still_wins(self):
        self.assertEqual(self.module.cli(), str(self.path))
        with patch.dict(os.environ, {'IDLE_STOP_CLI': '/bin/true'}):
            self.assertEqual(self.module.cli(), '/bin/true')


if __name__ == '__main__':
    unittest.main()
