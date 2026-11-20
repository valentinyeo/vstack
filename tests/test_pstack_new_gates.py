#!/usr/bin/env python3
"""Drive hooks/pstack-new-gates.py through Claude's PreToolUse protocol."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/pstack-new-gates.py'
FIXTURES = Path(__file__).resolve().parent / 'fixtures/pstack-diff'
PSTACK = FIXTURES / 'pstack'
SCORECARD = (
    '  scorecard:\n'
    '    runs-on: ubuntu-latest\n'
    '    steps:\n'
    '      - run: python3 scripts/scorecard.py\n'
)


def git(root, *args):
    subprocess.run(
        ['git', '-C', str(root), '-c', 'user.name=test',
         '-c', 'user.email=test@example.invalid', *args],
        check=True,
        capture_output=True,
    )


def build_repo(test):
    holder = tempfile.TemporaryDirectory(prefix='pstack-new-gates-')
    test.addCleanup(holder.cleanup)
    root = Path(holder.name)
    source = FIXTURES / 'clean'
    for path in source.rglob('*'):
        if path.is_file():
            target = root / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(path.read_text())
    workflow = root / '.github/workflows/ci.yml'
    git(root, 'init', '-q')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'base')
    workflow.write_text(workflow.read_text().rstrip('\n') + '\n' + SCORECARD)
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'head')
    return root


def run_hook(command, cwd):
    env = os.environ.copy()
    env['PSTACK_GATE_BASE'] = 'HEAD~1'
    env['PSTACK_DIFF_PSTACK'] = str(PSTACK)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({'tool_name': 'Bash', 'cwd': str(cwd), 'tool_input': {'command': command}}),
        capture_output=True,
        text=True,
        env=env,
    )


class PstackNewGates(unittest.TestCase):
    def test_self_test(self):
        result = subprocess.run(
            [sys.executable, str(HOOK), '--self-test'],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('self-test ok', result.stdout)

    def test_pr_create_with_new_extra_gate_is_blocked(self):
        root = build_repo(self)
        result = run_hook('gh pr create --title t --body b', root)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('EXTRA workflow: .github/workflows/ci.yml job scorecard', result.stderr)
        self.assertIn("house file", result.stderr)

    def test_other_commands_pass(self):
        root = build_repo(self)
        for command in ('git status', 'gh pr view 1', 'gh pr merge 1'):
            with self.subTest(command=command):
                result = run_hook(command, root)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_gap_pstack_blocks_pr_create(self):
        root = build_repo(self)
        env = os.environ.copy()
        env['PSTACK_GATE_BASE'] = 'HEAD~1'
        env['PSTACK_DIFF_PSTACK'] = str(FIXTURES / 'no-such-pstack')
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({
                'tool_name': 'Bash',
                'cwd': str(root),
                'tool_input': {'command': 'gh pr create --title t --body b'},
            }),
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('pstack recipe', result.stderr)


if __name__ == '__main__':
    unittest.main()
