"""tests/test_test_timeout_guard.py: the guard's command table, and the verify skill's grade.

2026-11-20: four `python3 -m unittest discover -s scripts` runs hung for 10 to 15 hours and each
kept a core busy. With parallel builds the 18 core VPS reached load 38 and no chat answered the
owner. The host watchdog only stops node and bun runners, so nothing here stopped python.
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'hooks/test-timeout-guard.py'
VERIFY = ROOT / '.claude/skills/verify-test-timeout'
GRADE = VERIFY / 'grade.py'
RUN = VERIFY / 'run'

# Every one of these starts a runner with no timeout in front of it, so it can hang a core.
BLOCKED = (
    # The exact command from 2026-11-20, and the same shapes from this repo's own CI.
    'python3 -m unittest discover -s scripts',
    "python3 -m unittest discover -s tests -p 'test_*.py' -v",
    'python3 -m unittest discover -s tests -p test_verify_reconcile.py -v',
    'python3 -m unittest',
    'python -m unittest discover',
    # pytest, by every name it answers to.
    'python3 -m pytest tests/',
    'pytest',
    'py.test -q tests',
    '.venv/bin/pytest tests',
    # Package scripts.
    'npm test',
    'npm run test',
    'pnpm test',
    'pnpm run test',
    'yarn test',
    'bun test',
    'bun run test',
    # Test and build runners on their own.
    'vitest run',
    'vitest',
    'jest --ci',
    './node_modules/.bin/jest',
    'playwright test',
    'cargo test',
    'cargo build --release',
    'go test ./...',
    'zig build',
    'make test',
    'make check',
    'make -j4 test',
    'bash tests/install.sh',
    'bash tests/*.sh',
    'node --test',
    'node --test tests/x.test.js',
    'tsc -b',
    'tsc --build',
    'tsc -p tsconfig.json',
    # Wrapped in something that is not a timeout, or nothing at all.
    'cd tests && pytest',
    'cd /workspace/repo && python3 -m unittest discover -s tests',
    'FOO=1 pytest',
    'env FOO=1 pytest',
    'env -i pytest',
    'env -i python3 -m unittest discover -s scripts',
    'env -u HOME pytest',
    'sudo -u val pytest',
    'nice pytest',
    'nohup pytest',
    'setsid pytest',
    '(pytest)',
    'echo start; pytest',
    'pytest | tee out.log',
    'pytest > out.log 2>&1',
    'go test ./... > out.log 2>&1',
    'ls && cargo test',
    'timeout 600 pytest; pytest',
    'pytest && timeout 600 true',
)

# Every one of these is either wrapped in a timeout or never starts a runner at all.
ALLOWED = (
    # The two commands this change runs, and CI's own shapes under a timeout.
    "timeout 600 python3 -m unittest discover -s tests -p 'test_*.py'",
    'timeout 600 python3 -m unittest discover -s scripts',
    'timeout 300 bash tests/install.sh',
    'timeout 600 bash tests/*.sh',
    'timeout 1800 cargo build --release',
    'timeout 600 make check',
    'timeout 600 tsc -b',
    'timeout 300 jest --ci',
    'timeout 1200 gh pr checks 176 --watch',
    # The timeout still counts through a wrapper or a cd chain.
    'cd tests && timeout 600 pytest',
    'env CI=1 timeout 600 npm test',
    'env -i timeout 600 python3 -m unittest discover -s scripts',
    'sudo -u val timeout 600 pytest',
    'FOO=1 timeout 600 pytest',
    'nice -n 10 timeout 600 pytest',
    'nohup timeout 1800 cargo build --release',
    'setsid timeout 600 go test ./...',
    'timeout -s KILL 600 pytest',
    '(cd tests && timeout 600 pytest)',
    'timeout 600 pytest 2>&1 | tee out.log',
    # Merely naming a runner starts nothing.
    'grep -rn "python3 -m unittest" .',
    'grep pytest hooks/*.py',
    'cat tests/install.sh',
    'ls tests',
    'echo pytest',
    'echo "run pytest later"',
    'git log --oneline -- pytest',
    'git log --grep cargo',
    'git commit -m "run pytest before merge"',
    'gh pr create --body "cargo test, then push"',
    'gh pr checks 176 --watch',
    'python3 hooks/test-timeout-guard.py --self-test',
    'python3 hooks/book-check.py --self-test',
    'python3 tests/test_pacer_enforce.py',
    'python3 -m json.tool package.json',
    'python3 -m pip install pytest',
    'npm install vitest',
    # Not a runner this guard owns: the watchdog already stops node builds.
    'npm run build',
    'yarn build',
    'go build ./...',
    'cargo run',
    'make install',
    'node build.js',
    'ls',
    'git status',
)


def guard(command, tool='Bash'):
    """Run the real hook on real PreToolUse JSON, the way Claude Code calls it."""
    with tempfile.TemporaryDirectory() as home:
        env = {'PATH': os.environ['PATH'], 'HOME': home}
        payload = json.dumps({'tool_name': tool, 'tool_input': {'command': command}})
        result = subprocess.run([sys.executable, str(GUARD)], input=payload, text=True,
                                capture_output=True, env=env, cwd=str(ROOT))
    return result.returncode, result.stderr


class TestTimeoutGuard(unittest.TestCase):
    def test_every_unwrapped_runner_is_blocked(self):
        for command in BLOCKED:
            with self.subTest(command=command):
                code, why = guard(command)
                self.assertEqual(code, 2, command)
                self.assertIn('timeout', why, command)

    def test_every_wrapped_or_mentioning_command_passes(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(guard(command), (0, ''), command)

    def test_the_hung_command_from_2026_11_20_is_blocked(self):
        code, why = guard('python3 -m unittest discover -s scripts')
        self.assertEqual(code, 2)
        self.assertIn('python3 -m unittest', why)

    def test_the_block_names_the_fix_on_one_line(self):
        code, why = guard('pytest')
        self.assertEqual(code, 2)
        self.assertEqual(why.count('\n'), 1, why)
        self.assertIn('timeout 600', why)

    def test_another_tool_passes(self):
        self.assertEqual(guard('python3 -m unittest', tool='Write'), (0, ''))

    def test_broken_input_passes(self):
        with tempfile.TemporaryDirectory() as home:
            env = {'PATH': os.environ['PATH'], 'HOME': home}
            result = subprocess.run([sys.executable, str(GUARD)], input='not json', text=True,
                                    capture_output=True, env=env, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0)

    def test_the_self_test_runs(self):
        result = subprocess.run([sys.executable, str(GUARD), '--self-test'], text=True,
                                capture_output=True, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('self-test ok', result.stdout)


class VerifyTestTimeoutGrade(unittest.TestCase):
    """The verify skill's grade path, on synthetic evidence: no hook run, no sleep."""

    def grade(self, blocked_exit=2,
              blocked_err='BLOCKED by test-timeout-guard: python3 -m unittest can hang for hours. '
                          'Prefix it with `timeout 600`.\n', allowed_exit=0,
              allowed_err='', killed_exit=124, seconds=5.1):
        evidence = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(['rm', '-rf', str(evidence)]))
        (evidence / 'blocked.exit').write_text(f'{blocked_exit}\n')
        (evidence / 'blocked.err').write_text(blocked_err)
        (evidence / 'allowed.exit').write_text(f'{allowed_exit}\n')
        (evidence / 'allowed.err').write_text(allowed_err)
        (evidence / 'killed.exit').write_text(f'{killed_exit}\n')
        (evidence / 'killed.seconds').write_text(f'{seconds}\n')
        (evidence / 'meta.json').write_text(json.dumps({'hook': str(GUARD), 'timeout_seconds': 5}))
        result = subprocess.run([sys.executable, str(GRADE), str(evidence)],
                                capture_output=True, text=True, check=False)
        return result.returncode, result.stdout

    def assert_passes(self, code, output, check):
        self.assertEqual(code, 0, output)
        self.assertIn('VERDICT PASS', output)
        self.assertIn('PASS ' + check + ':', output)

    def assert_fails(self, output, check):
        lines = output.splitlines()
        self.assertIn('VERDICT FAIL', lines, output)
        self.assertTrue(any(line.startswith('FAIL ' + check + ':') for line in lines), output)

    def test_a_good_run_passes(self):
        code, output = self.grade()
        self.assert_passes(code, output, 'blocked')
        for check in ('blocked', 'allowed', 'killed'):
            self.assertIn('PASS ' + check + ':', output)
        self.assertIn('VERDICT PASS', output)

    def test_an_unblocked_hung_command_fails(self):
        self.assert_fails(self.grade(blocked_exit=0)[1], 'blocked')

    def test_a_block_without_the_fix_fails(self):
        self.assert_fails(self.grade(blocked_err='no\n')[1], 'blocked')

    def test_a_two_line_block_fails(self):
        self.assert_fails(self.grade(blocked_err='timeout\nsecond line\n')[1], 'blocked')

    def test_a_blocked_good_command_fails(self):
        self.assert_fails(self.grade(allowed_exit=2)[1], 'allowed')

    def test_a_good_command_with_stderr_fails(self):
        self.assert_fails(self.grade(allowed_err='warning\n')[1], 'allowed')

    def test_a_timeout_that_does_not_kill_fails(self):
        self.assert_fails(self.grade(killed_exit=1)[1], 'killed')

    def test_a_sleep_that_never_ends_fails(self):
        self.assert_fails(self.grade(seconds=60.0)[1], 'killed')

    def test_no_evidence_is_a_usage_error(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(['rm', '-rf', str(empty)]))
        result = subprocess.run([sys.executable, str(GRADE), str(empty)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stdout)


class VerifyTestTimeoutRun(unittest.TestCase):
    """run is not launched here: it writes to the state dir and sleeps 5 seconds.
    Its own text is checked, and the real run happens on the PR."""

    def setUp(self):
        self.text = RUN.read_text()

    def test_run_is_executable(self):
        self.assertTrue(RUN.stat().st_mode & stat.S_IXUSR)

    def test_run_feeds_the_real_hook_real_pretooluse_json(self):
        self.assertIn('tool_name', self.text)
        self.assertIn('tool_input', self.text)

    def test_run_checks_the_exact_hung_command(self):
        self.assertIn('python3 -m unittest discover -s scripts', self.text)

    def test_run_proves_a_real_timeout_kills(self):
        self.assertIn("timeout 5 python3 -c 'import time; time.sleep(60)'", self.text)

    def test_run_keeps_its_evidence(self):
        for name in ('meta.json', 'verdict.txt', 'verify-test-timeout'):
            self.assertIn(name, self.text, name)

    def test_the_feature_map_names_every_check_and_its_file(self):
        features = VERIFY / 'features'
        readme = (features / 'README.md').read_text()
        rows = re.findall(r'\[([\w-]+\.md)\]\(([\w-]+\.md)\)[^\n|]*\|\s*`([\w ]+)`', readme)
        self.assertEqual(sorted(check.strip() for _name, _file, check in rows),
                         ['allowed', 'blocked', 'killed'])
        for name, filename, _check in rows:
            with self.subTest(file=filename):
                self.assertEqual(name, filename)
                self.assertTrue((features / filename).is_file(), filename)


class TestTimeoutSkill(unittest.TestCase):
    """A rule in a document is not a check. These pin the one instruction a chat must never get:
    `./install` from a worker's worktree repointed every chat's skills at that branch."""

    def setUp(self):
        self.skill = ROOT / 'skills/test-timeout/SKILL.md'
        self.text = self.skill.read_text()

    def test_the_skill_never_sends_a_chat_to_install(self):
        for line in self.text.splitlines():
            if './install' in line:
                with self.subTest(line=line):
                    self.assertIn('Never run `./install`', line)

    def test_the_skill_names_the_hook_the_shared_install_already_linked(self):
        self.assertIn('$HOME/.claude/hooks/test-timeout-guard.py', self.text)
        self.assertIn('~/.local/share/vstack', self.text)

    def test_the_skill_still_tells_a_chat_to_register_the_hook_per_project(self):
        self.assertIn('.claude/settings.json', self.text)
        self.assertIn('PreToolUse', self.text)


if __name__ == '__main__':
    unittest.main()
