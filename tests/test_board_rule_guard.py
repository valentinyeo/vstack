import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'scripts/board-rule-guard.py'
RULES = ROOT / 'skills/valentin-mode/board-rules.json'
TEST = 'tests/test_valentin_mode_rules.py'
COPIED = ('skills', 'scripts', 'evals', 'hooks')
WORKFLOWS = ROOT / '.github/workflows'
PASSING_TEST = ('import unittest\n\n\nclass Nothing(unittest.TestCase):\n'
                '    def test_nothing(self):\n        self.assertTrue(True)\n')
WRAPPERS = {'trap', 'timeout', 'sudo', 'env', 'nice', 'command', 'exec', 'nohup'}
COPY = {'cp', 'mv', 'tee'}


def run_guard(root=None):
    command = [sys.executable, str(GUARD)]
    if root is not None:
        command += ['--root', str(root)]
    return subprocess.run(command, capture_output=True, text=True, timeout=600)


def digest(root):
    paths = [TEST] + [str(path.relative_to(root)) for name in COPIED
                      for path in sorted((root / name).rglob('*')) if path.is_file()]
    hasher = hashlib.sha256()
    for relative in sorted(paths):
        hasher.update(relative.encode() + b'\0' + (root / relative).read_bytes() + b'\0')
    return hasher.hexdigest()


def copy_checkout(into):
    into.mkdir(parents=True)
    for name in COPIED:
        shutil.copytree(ROOT / name, into / name)
    (into / TEST).parent.mkdir(parents=True)
    shutil.copy2(ROOT / TEST, into / TEST)


def rule_ids():
    return [row['id'] for row in json.loads(RULES.read_text())]


def tracked_files():
    done = subprocess.run(['git', '-C', str(ROOT), 'ls-files'], check=True,
                          capture_output=True, text=True)
    return set(done.stdout.split())


def words(line):
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def unwrap(parts):
    """The command a wrapper line runs: `trap '<command>' EXIT`, `timeout 300 <command>`."""
    while parts and Path(parts[0]).name in WRAPPERS:
        name, rest = Path(parts[0]).name, parts[1:]
        if name == 'trap':
            parts = words(rest[0]) if rest else []
            continue
        rest = [word for word in rest if not word.startswith('-')]
        if name == 'timeout' and rest:
            rest = rest[1:]
        while name == 'env' and rest and '=' in rest[0]:
            rest = rest[1:]
        parts = rest
    return parts


def copy_destination(line):
    parts = unwrap(words(line))
    if not parts or Path(parts[0]).name not in COPY:
        return []
    arguments = [word for word in parts[1:] if not word.startswith('-')]
    return arguments[-1:]


def redirect_targets(line):
    return [word.strip('\'"') for word in re.findall(r'>>?\s*([^\s|;&)>\'"]+)', line)]


class BoardRuleGuard(unittest.TestCase):
    def test_every_rule_id_fails_by_name_when_its_sentence_is_removed(self):
        result = run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in rule_ids():
            with self.subTest(rule=name):
                self.assertIn(f'board-rule-guard: {name} deletion caught', result.stdout)
        self.assertNotIn('AssertionError', result.stdout + result.stderr)

    def test_the_guard_leaves_the_checkout_byte_identical(self):
        before = digest(ROOT)
        result = run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(digest(ROOT), before)

    def test_a_contract_that_cannot_fail_is_reported(self):
        with tempfile.TemporaryDirectory() as where:
            root = Path(where) / 'checkout'
            copy_checkout(root)
            (root / TEST).write_text(PASSING_TEST)
            result = run_guard(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(f"board-rule-guard: FAIL removing {rule_ids()[0]}", result.stdout)
            self.assertIn('still passes the contract', result.stdout)

    def test_a_sentence_missing_from_the_skill_is_named(self):
        with tempfile.TemporaryDirectory() as where:
            root = Path(where) / 'checkout'
            copy_checkout(root)
            rules = json.loads((root / RULES).read_text())
            skill = root / 'skills/valentin-mode/SKILL.md'
            skill.write_text(skill.read_text().replace(rules[0]['sentence'], '', 1))
            result = run_guard(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(f"board-rule-guard: FAIL {rules[0]['id']}'s sentence is not in", result.stdout)


class WorkflowOwnership(unittest.TestCase):
    def workflows(self):
        return sorted(WORKFLOWS.glob('*.yml'))

    def test_no_workflow_writes_a_tracked_file(self):
        tracked = tracked_files()
        for workflow in self.workflows():
            for number, line in enumerate(workflow.read_text().splitlines(), 1):
                for target in redirect_targets(line) + copy_destination(line):
                    with self.subTest(workflow=workflow.name, line=number, target=target):
                        self.assertNotIn(target, tracked)

    def test_board_rule_data_belongs_to_a_script(self):
        for workflow in self.workflows():
            with self.subTest(workflow=workflow.name):
                self.assertNotIn('board-rules.json', workflow.read_text())


if __name__ == '__main__':
    unittest.main()
