#!/usr/bin/env python3
"""Prove tests/test_valentin_mode_rules.py fails, by name, for every board rule id whose sentence is removed.

The sentence is removed in a throwaway copy of the checkout, never in the checkout itself, so a
green run prints one line per rule instead of a test failure a reader can mistake for a flake
(VSTA-304). The checkout it reads is hashed before and after, and a change fails the run.

    board-rule-guard.py [--root DIR]
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIED = ('skills', 'scripts', 'evals', 'hooks')
TEST = 'tests/test_valentin_mode_rules.py'
PATTERN = 'test_valentin_mode_rules.py'
RULES = 'skills/valentin-mode/board-rules.json'
SKILL = 'skills/valentin-mode/SKILL.md'
CONTRACT_TIMEOUT = 120


def digest(root):
    """A hash over the files this guard reads, so a run can prove it changed none of them."""
    paths = [TEST] + [str(path.relative_to(root)) for name in COPIED
                      for path in sorted((root / name).rglob('*')) if path.is_file()]
    hasher = hashlib.sha256()
    for relative in sorted(paths):
        hasher.update(relative.encode() + b'\0' + (root / relative).read_bytes() + b'\0')
    return hasher.hexdigest()


def copy_root(source, into):
    for name in COPIED:
        shutil.copytree(source / name, into / name)
    (into / TEST).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / TEST, into / TEST)


def contract(root):
    """(exit code, output) of the board rule contract run against one root."""
    done = subprocess.run(
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', PATTERN],
        cwd=str(root), capture_output=True, text=True, timeout=CONTRACT_TIMEOUT)
    return done.returncode, done.stdout + done.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    rules = json.loads((root / RULES).read_text())
    if not rules:
        print(f'board-rule-guard: FAIL {RULES} holds no rules')
        return 1
    before = digest(root)
    with tempfile.TemporaryDirectory(prefix='board-rule-guard-') as where:
        work = Path(where) / 'checkout'
        copy_root(root, work)
        intact = (work / SKILL).read_text()
        for row in rules:
            if row['sentence'] not in intact:
                print(f"board-rule-guard: FAIL {row['id']}'s sentence is not in {SKILL}")
                return 1
        code, output = contract(work)
        if code:
            print(f'board-rule-guard: FAIL the contract fails on an unedited copy\n{output}')
            return 1
        for row in rules:
            (work / SKILL).write_text(intact.replace(row['sentence'], '', 1))
            code, output = contract(work)
            (work / SKILL).write_text(intact)
            if code == 0:
                print(f"board-rule-guard: FAIL removing {row['id']}'s sentence still passes the contract")
                return 1
            if f"Missing sentence for {row['id']}" not in output:
                print(f"board-rule-guard: FAIL a {row['id']} deletion is not reported by name\n{output}")
                return 1
            print(f"board-rule-guard: {row['id']} deletion caught")
    if digest(root) != before:
        print(f'board-rule-guard: FAIL the guard changed files under {root}')
        return 1
    print(f'board-rule-guard: PASS {len(rules)} rule ids fail by name when removed, checkout unchanged')
    return 0


if __name__ == '__main__':
    sys.exit(main())
