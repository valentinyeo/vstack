"""Pacer workers on OpenCode and Antigravity never run Claude hooks, so they get shims.

VSTA-165: the shims come from the same blocked list and the same matcher as the hook,
print the same message and exit 2. They pass a light command through to the real binary.
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

ROOT = Path(__file__).resolve().parents[1]
SHIMS = ROOT / 'scripts/worker-shims'
GUARD = ROOT / 'hooks/heavy-local-guard.py'
DATA = json.loads((ROOT / 'config/heavy-local.json').read_text())
PRETEND = ('gradle', 'gradlew', 'zig', 'npm', 'pytest', 'wine', 'xvfb-run', 'cargo', 'go', 'python3')


def generate(home, *, real=None):
    """Write the shims into a scratch dir, looking for real binaries where the test says."""
    bindir = Path(home) / 'bin'
    bindir.mkdir()
    for name in real or ():
        script = bindir / name
        script.write_text('#!/bin/sh\necho "real %s $*"\n' % name)
        script.chmod(0o755)
    out = Path(home) / 'shims'
    result = subprocess.run([sys.executable, str(SHIMS), '--dir', str(out), '--path', str(bindir)],
                            text=True, capture_output=True, timeout=30,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    return out, result


def load_shims_module():
    """scripts/worker-shims has no .py suffix, so load it from its path."""
    spec = importlib.util.spec_from_loader('worker_shims',
                                           importlib.machinery.SourceFileLoader('worker_shims',
                                                                                str(SHIMS)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(shim, *args, home):
    return subprocess.run([str(shim), *args], text=True, capture_output=True, timeout=30,
                          env=dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE='1'))


def hook_says(command):
    payload = {'tool_name': 'Bash', 'cwd': '/tmp/unit-project', 'tool_input': {'command': command}}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), text=True,
                          capture_output=True, timeout=5,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))


class WorkerShims(unittest.TestCase):
    def test_shims_cover_the_blocked_list(self):
        with tempfile.TemporaryDirectory() as home:
            out, result = generate(home, real=PRETEND)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in PRETEND:
                with self.subTest(name=name):
                    shim = out / name
                    self.assertTrue(shim.is_file(), name)
                    self.assertTrue(os.access(shim, os.X_OK), name)
            # A runner this host lacks still gets a shim: the refusal, not "command not found".
            self.assertIn("not installed", run(out / 'wineserver', '--version', home=home).stderr)
            self.assertEqual(set(PRETEND) - set(DATA['shims']), set())
        self.assertIn('worker-shims', (ROOT / 'install').read_text())

    def test_a_heavy_command_gets_the_hooks_own_refusal(self):
        # Worker shims see only their own argv (never a wrapping `timeout`), so single-file
        # unittest commands keep being refused here even when a chat allows them under timeout <= 90s.
        for shim, args in (('gradlew', ('assembleDebug',)), ('gradle', ('test',)),
                           ('zig', ('build',)), ('npm', ('test',)), ('pytest', ()),
                           ('wine', ('app.exe',)), ('cargo', ('test',)),
                           ('go', ('test', './...',)),
                           ('python3', ('-m', 'unittest', 'discover', '-s', 'tests')),
                           ('python3', ('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_hook_paths.py', '-v')),
                           ('python3', ('-m', 'unittest', 'tests.test_heavy_local_guard'))):
            with self.subTest(shim=shim, args=args):
                with tempfile.TemporaryDirectory() as home:
                    out, _ = generate(home, real=PRETEND)
                    result = run(out / shim, *args, home=home)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stderr, hook_says(' '.join((shim, *args))).stderr)
                    self.assertIn('GitHub', result.stderr)

    def test_a_light_command_runs_the_real_binary(self):
        with tempfile.TemporaryDirectory() as home:
            out, _ = generate(home, real=PRETEND)
            for shim, args in (('zig', ('version',)), ('gradle', ('--version',)),
                               ('zig', ('fmt', '--check', 'src/main.zig')),
                               ('python3', ('-m', 'py_compile', 'hooks/heavy-local-guard.py'))):
                with self.subTest(shim=shim, args=args):
                    result = run(out / shim, *args, home=home)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, 'real %s %s\n' % (shim, ' '.join(args)))

    def test_a_light_command_on_a_missing_runner_says_so(self):
        with tempfile.TemporaryDirectory() as home:
            out, _ = generate(home, real=PRETEND)
            result = run(out / 'dotnet', '--version', home=home)
            self.assertEqual(result.returncode, 127, result.stderr)
            self.assertIn('dotnet is not installed', result.stderr)

    def test_a_refused_command_never_starts_the_real_binary(self):
        with tempfile.TemporaryDirectory() as home:
            out, _ = generate(home, real=PRETEND)
            payload = ('#!/bin/sh\nkill -9 $$\n')
            real = Path(home) / 'bin/npm'
            real.write_text(payload)
            result = run(out / 'npm', 'run', 'build', home=home)
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_a_foreign_worker_shims_dir_never_becomes_the_real_binary(self):
        # plan-pick prepends `<project>/bin/worker-shims` to PATH. If a shim pointed at that
        # folder's `gh`, the two shims would exec each other forever.
        with tempfile.TemporaryDirectory() as home:
            bindir = Path(home) / 'bin'
            bindir.mkdir()
            real_gh = bindir / 'gh'
            real_gh.write_text('#!/bin/sh\necho "real gh $*"\n')
            real_gh.chmod(0o755)
            foreign = Path(home) / 'token-ladder/bin/worker-shims'
            foreign.mkdir(parents=True)
            (foreign / 'gh').write_text('#!/bin/sh\nexec "%s" "$@"\n' % (foreign / 'gh'))
            (foreign / 'gh').chmod(0o755)
            out = Path(home) / 'shims'
            search = os.pathsep.join([str(foreign), str(bindir)])
            module = load_shims_module()
            shims = module.shims_for(out, search, sys.executable)
            self.assertNotIn(str(foreign / 'gh'), shims['gh'])
            self.assertIn(str(real_gh.resolve()), shims['gh'])

    def test_install_generates_the_shims_the_workers_read(self):
        text = (ROOT / 'install').read_text()
        self.assertIn('scripts/worker-shims', text)
        self.assertIn('.local/state/vstack/worker-shims', text)


if __name__ == '__main__':
    unittest.main()
