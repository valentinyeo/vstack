"""Heavy jobs move to GitHub; this hook never starts the commands it inspects.

VSTA-165: the blocked list lives in config/heavy-local.json so pacer worker shims and
this hook cannot drift apart, and the only exceptions are the lines in
config/heavy-local-allow.txt, each one carrying its reason.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'hooks/heavy-local-guard.py'

BLOCKED = (
    # Gradle and the Android build that put this server on HOLD today.
    'gradle build', './gradlew assembleDebug', '/opt/android/gradlew test',
    '/opt/android/gradlew assembleRelease',
    'sh ./gradlew assembleRelease', 'bash android/gradlew test',
    'cd android && ./gradlew assembleDebug', 'timeout 900 ./gradlew verifyRelease',
    'java -cp gradle.jar org.gradle.launcher.GradleMain build',
    # Zig and the Windows desktop app.
    'zig build', 'zig test src/main.zig', '/opt/zig/zig build -Doptimize=ReleaseFast',
    'zig build-exe app.zig', 'zig run app.zig',
    'zig build -Dtarget=x86_64-windows-gnu',
    'wine app.exe', 'wine64 app.exe', 'wineserver', 'wineserver64',
    'wine-preloader app.exe', 'wine64-preloader app.exe', 'wineboot -u', 'winetricks corefonts',
    './zig-out/bin/multiprompt.exe', 'zig-out/bin/zigshell-bridge.exe',
    'xvfb-run -a wine zig-out/bin/multiprompt.exe', 'xvfb-run -a ./tools/test-windows-wine.sh',
    './tools/test-windows-wine.sh', 'bash tools/test-windows-wine.sh',
    'node tools/chat-bench/run.mjs', 'cd . && tools/test-windows-wine.sh',
    # Test runners, everywhere: GitHub Actions runs them.
    'npm test', 'npm run test -- unit', 'npm t', 'pnpm test', 'yarn test', 'bun test',
    'npm run test:unit', 'pytest', 'pytest tests/unit', 'timeout 600 pytest',
    'python3 -m pytest tests/unit', 'py.test tests',
    'cargo test', 'cargo test single_unit', 'go test ./...', 'go test ./unit',
    'python3 -m unittest discover -s tests', 'timeout 600 python3 -m unittest discover -s tests',
    'cd /tmp && python3 -m unittest discover', 'timeout 600 pytest tests/test_x.py',
    # Builds, still.
    'npm run build', 'pnpm build', 'yarn build', 'bun run build',
    'npm --prefix web run build', 'npm run build:android',
    'npx next build', 'next build', 'vite build', 'ng build',
    'cargo build --release', 'go build ./...', 'make', 'make -j4 all',
    'cmake --build build', 'dotnet build', 'flutter build apk', 'xcodebuild test',
    'timeout 600 nice -n 19 ./gradlew test', 'env CI=1 zig build',
    'GITHUB_ACTIONS=true wine64 app.exe', 'command zig test x.zig',
    'echo starting; zig build', 'true\nzig test x.zig', '(zig build) | tee output',
    "bash -lc 'timeout 600 zig build'", "sh -c 'wine app.exe'",
    "bash -o pipefail -c 'zig build'", 'npm run -- build',
    'npm exec -- next build', 'node node_modules/next/dist/bin/next build',
    'node /usr/lib/node_modules/npm/bin/npm-cli.js run build',
)
ALLOWED = (
    # The only three exceptions, each a line in config/heavy-local-allow.txt.
    'python3 -m py_compile hooks/heavy-local-guard.py', 'node --check app.js',
    'bash -n install', 'sh -n ./deploy', 'zig fmt --check src/main.zig',
    'zig version', 'zig --version', 'zig fmt build.zig', 'gradle --version',
    'timeout 60 python3 -m unittest tests.test_heavy_local_guard',
    'timeout 60 python3 -m unittest tests.test_a.TestPicks.b -v',
    'timeout 45 pytest tests/test_heavy_local_guard.py',
    'timeout 1m python3 -m pytest tests/test_one.py',
    # Mentions never start anything.
    'git status', 'git log --grep gradle', 'grep "zig build" README.md',
    'rg wine .', 'echo "./gradlew build"', 'cat gradlew',
    'python3 hooks/heavy-local-guard.py --self-test',
    'npm install', 'npm run builder', 'make help', 'make clean',
    'cmake --version', 'java --version', 'go version', 'cargo metadata',
    'gh workflow run build.yml', 'git push origin HEAD',
    'gh pr create --body "zig build runs on GitHub"',
    "ssh builder 'zig build'", "bash -c 'echo wine64'",
)


def feed(command, *, tool='Bash', cwd='/tmp/unit-project'):
    payload = {'tool_name': tool, 'cwd': cwd, 'tool_input': {'command': command}}
    with tempfile.TemporaryDirectory() as home:
        return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                              text=True, capture_output=True, timeout=5, cwd=home,
                              env=dict(os.environ, HOME=home, PYTHONDONTWRITEBYTECODE='1'))


class HeavyLocalGuard(unittest.TestCase):
    def test_heavy_commands_block_even_under_timeout(self):
        for command in BLOCKED:
            with self.subTest(command=command):
                result = feed(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertIn('GitHub', result.stderr)
                self.assertIn('gh workflow run', result.stderr)
                self.assertIn('push', result.stderr)

    def test_light_commands_and_mentions_pass(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                result = feed(command)
                self.assertEqual((result.returncode, result.stderr), (0, ''))

    def test_hypertask_full_suites_follow_the_reference(self):
        for command in ('npm test', 'npm run lint', 'npx vitest run',
                        'node --test', 'next dev', 'tsc --noEmit'):
            with self.subTest(command=command):
                self.assertEqual(feed(command, cwd='/home/valentin/projects/hypertask').returncode, 2)
        self.assertEqual(feed('cd /home/valentin/projects/hypertask && npm test').returncode, 2)
        self.assertEqual(feed('npm --prefix /home/valentin/projects/hypertask test').returncode, 2)
        self.assertEqual(feed('npm test', cwd='/home/valentin/projects/hypertask-other').returncode, 2)
        self.assertEqual(feed('npm test', cwd='/home/valentin/projects/hypertask/../unit-project').returncode, 2)
        self.assertEqual(feed('node node_modules/vitest/vitest.mjs run',
                              cwd='/home/valentin/projects/hypertask').returncode, 2)

    def test_other_tools_and_malformed_payloads_pass(self):
        self.assertEqual(feed('zig build', tool='Read').returncode, 0)
        for payload in ('not json', '[]', '{}', '{"tool_name":"Bash","tool_input":null}',
                        '{"tool_name":"Bash","tool_input":{"command":12}}'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as home:
                result = subprocess.run([sys.executable, str(GUARD)], input=payload,
                                        text=True, capture_output=True, timeout=5, cwd=home,
                                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
                self.assertEqual((result.returncode, result.stderr), (0, ''))

    def test_rule_requires_each_chat_to_register_its_guard(self):
        text = (ROOT / 'skills/test-timeout/SKILL.md').read_text().split('## Heavy work stays on GitHub')[1]
        text = text.split('\n## ')[0]
        for phrase in ('Each chat', "own project's", 'PreToolUse', 'heavy-local-guard.py',
                       'Light tests still pass', 'gh workflow run'):
            self.assertIn(phrase, text)

    def test_the_rule_sends_full_suites_to_github(self):
        text = (ROOT / 'skills/test-timeout/SKILL.md').read_text()
        self.assertIn('config/heavy-local.json', text)
        self.assertIn('config/heavy-local-allow.txt', text)
        self.assertIn('worker-shims', text)
        self.assertIn('unittest discover -s tests` on this host', text)
        brief = (ROOT / 'scripts/worker.md').read_text()
        self.assertIn('GitHub Actions', brief)
        self.assertIn('gh pr checks', brief)
        self.assertIn('heavy-local-guard.py`, `config/heavy-local.json`, `scripts/worker-shims`',
                      (ROOT / 'CLAUDE.md').read_text())


class HeavyLocalData(unittest.TestCase):
    def test_one_data_file_holds_the_blocked_list(self):
        data = json.loads((ROOT / 'config/heavy-local.json').read_text())
        for key in ('message', 'always', 'verbs', 'package_managers', 'python_modules',
                    'scripts', 'suffixes', 'shims'):
            self.assertIn(key, data)
        self.assertIn('{runner}', data['message'])
        for runner in ('gradle', 'wine', 'wine64', 'wineserver', 'xvfb-run'):
            self.assertIn(runner, data['always'], runner)
        for runner, verb in (('zig', 'test'), ('cargo', 'test'), ('go', 'test')):
            self.assertIn(verb, data['verbs'][runner], runner)
        self.assertLessEqual({'npm', 'pnpm', 'yarn', 'bun'}, set(data['package_managers']))
        self.assertIn('unittest', data['python_modules'])
        self.assertIn('tools/test-windows-wine.sh', data['scripts'])
        self.assertIn('.exe', data['suffixes'])
        self.assertLessEqual({'gradlew', 'xvfb-run', 'zig', 'npm', 'pytest'},
                             set(data['shims']))

    def test_every_exception_names_its_reason(self):
        lines = [line.strip() for line in (ROOT / 'config/heavy-local-allow.txt').read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith('#')]
        self.assertGreaterEqual(len(lines), 5)
        for line in lines:
            with self.subTest(line=line):
                pattern, reason = line.rsplit(' | ', 1)
                self.assertTrue(pattern.startswith('^') and pattern.endswith('$'), line)
                self.assertGreater(len(reason.split()), 3, line)

    def test_a_hook_with_no_data_file_still_lets_bash_through(self):
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp)
            (checkout / 'hooks').mkdir()
            shutil.copyfile(GUARD, checkout / 'hooks/heavy-local-guard.py')
            shutil.copyfile(ROOT / 'hooks/test-timeout-guard.py',
                            checkout / 'hooks/test-timeout-guard.py')
            payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'zig build'}})
            result = subprocess.run([sys.executable, str(checkout / 'hooks/heavy-local-guard.py')],
                                    input=payload, text=True, capture_output=True, timeout=5,
                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            self.assertEqual((result.returncode, result.stderr), (0, ''))


class HeavyLocalWiring(unittest.TestCase):
    def test_own_project_settings_block_before_execution(self):
        """Drive the real registered command through its installed link, in a scratch HOME."""
        settings = json.loads((ROOT / '.claude/settings.json').read_text())
        commands = [hook['command'] for group in settings['hooks']['PreToolUse']
                    if group.get('matcher') == 'Bash' for hook in group['hooks']
                    if 'heavy-local-guard.py' in hook['command']]
        self.assertEqual(len(commands), 1)
        doc = (ROOT / 'skills/test-timeout/SKILL.md').read_text()
        self.assertIn(json.dumps(commands[0])[1:-1], doc)
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            hooks = home / '.claude/hooks'
            env = dict(os.environ, HOME=temp, PYTHONDONTWRITEBYTECODE='1',
                       VSTACK_INSTALL_ANYWHERE='1', VSTACK_DIR=str(home / '.local/share/vstack'))
            install = subprocess.run([str(ROOT / 'install')], env=env, capture_output=True,
                                     text=True, timeout=60)
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertTrue((hooks / 'heavy-local-guard.py').samefile(ROOT / 'hooks/heavy-local-guard.py'))
            for command, expected in (('./gradlew test', 2), ('zig test app.zig', 2),
                                      ('wine64 app.exe', 2), ('npm test', 2),
                                      ('pytest', 2), ('python3 -m py_compile x.py', 0),
                                      ('gh workflow run build.yml', 0)):
                payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}})
                result = subprocess.run(['sh', '-c', commands[0]], input=payload, text=True,
                                        capture_output=True, timeout=5, env=env, cwd=temp)
                self.assertEqual(result.returncode, expected, result.stderr)
            (hooks / 'heavy-local-guard.py').unlink()
            result = subprocess.run(['sh', '-c', commands[0]], input=payload, text=True,
                                    capture_output=True, timeout=5, env=env, cwd=temp)
            self.assertEqual(result.returncode, 0)
            self.assertIn('hook missing or not executable', result.stderr)
            self.assertEqual((home / '.local/state/vstack/hook-missing.log').read_text(), result.stderr)
        print('PASS heavy-local: installed hook blocks heavy jobs; light commands and missing links pass')


if __name__ == '__main__':
    unittest.main()
