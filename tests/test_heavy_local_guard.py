"""Heavy jobs move to GitHub; this hook never starts the commands it inspects."""
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
    'gradle build', './gradlew assembleDebug', '/opt/android/gradlew test',
    'gradle --version', 'sh ./gradlew assembleRelease', 'bash android/gradlew test',
    'zig build', 'zig test src/main.zig', '/opt/zig/zig build -Doptimize=ReleaseFast',
    'zig build-exe app.zig', 'zig run app.zig',
    'wine app.exe', 'wine64 app.exe', 'wineserver', 'wineserver64',
    'wine-preloader app.exe', 'wine64-preloader app.exe',
    'java -cp gradle.jar org.gradle.launcher.GradleMain build',
    'npm run build', 'pnpm build', 'yarn build', 'bun run build',
    'npm --prefix web run build', 'npm run build:android',
    'npx next build', 'next build', 'vite build', 'ng build',
    'cargo build --release', 'go build ./...', 'make', 'make -j4 all',
    'cmake --build build', 'dotnet build', 'flutter build apk', 'xcodebuild test',
    'timeout 600 nice -n 19 ./gradlew test', 'env CI=1 zig build',
    'GITHUB_ACTIONS=true wine64 app.exe', 'command zig test x.zig',
    'cd android && ./gradlew test', 'echo starting; zig build',
    'true\nzig test x.zig', '(zig build) | tee output',
    "bash -lc 'timeout 600 zig build'", "sh -c 'wine app.exe'",
    "bash -o pipefail -c 'zig build'", 'npm run -- build',
    'npm exec -- next build', 'node node_modules/next/dist/bin/next build',
    'node /usr/lib/node_modules/npm/bin/npm-cli.js run build',
)
ALLOWED = (
    'timeout 600 python3 -m unittest discover -s tests',
    'python3 -m unittest', 'pytest tests/unit', 'timeout 600 pytest',
    'npm test', 'npm run test -- unit', 'pnpm test', 'yarn test', 'bun test',
    'git status', 'git log --grep gradle', 'grep "zig build" README.md',
    'rg wine .', 'echo "./gradlew build"', 'cat gradlew',
    'python3 hooks/heavy-local-guard.py --self-test',
    'zig version', 'zig fmt src/main.zig', 'npm install', 'npm run builder',
    'make help', 'make clean', 'cmake --version', 'go test ./unit',
    'cargo test single_unit', 'java --version',
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
        self.assertEqual(feed('npm test', cwd='/home/valentin/projects/hypertask-other').returncode, 0)
        self.assertEqual(feed('npm test', cwd='/home/valentin/projects/hypertask/../unit-project').returncode, 0)
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
        self.assertIn('link_one heavy-local-guard.py "$ROOT/hooks/heavy-local-guard.py"',
                      (ROOT / 'install').read_text())


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
            hooks.mkdir(parents=True)
            checkout = home / 'checkout/hooks'
            checkout.mkdir(parents=True)
            for name in ('heavy-local-guard.py', 'test-timeout-guard.py'):
                shutil.copyfile(ROOT / 'hooks' / name, checkout / name)
                (hooks / name).symlink_to(checkout / name)
            env = dict(os.environ, HOME=temp, PYTHONDONTWRITEBYTECODE='1')
            for command, expected in (('./gradlew test', 2), ('zig test app.zig', 2),
                                      ('wine64 app.exe', 2), ('npm test', 0),
                                      ('gh workflow run build.yml', 0)):
                payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}})
                result = subprocess.run(['sh', '-c', commands[0]], input=payload, text=True,
                                        capture_output=True, timeout=5, env=env, cwd=temp)
                self.assertEqual(result.returncode, expected, result.stderr)
            (hooks / 'heavy-local-guard.py').unlink()
            result = subprocess.run(['sh', '-c', commands[0]], input=payload, text=True,
                                    capture_output=True, timeout=5, env=env, cwd=temp)
            self.assertEqual((result.returncode, result.stderr), (0, ''))
        print('PASS heavy-local: installed hook blocks heavy jobs; light commands and missing links pass')


if __name__ == '__main__':
    unittest.main()
