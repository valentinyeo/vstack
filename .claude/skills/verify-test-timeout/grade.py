#!/usr/bin/env python3
"""Grade one verify-test-timeout run from its evidence directory.

Reads what `run` saved, prints one PASS/FAIL line per check, then VERDICT PASS or
VERDICT FAIL. Exit 0 on PASS, 1 on FAIL, 2 on usage or missing evidence. Every
check reads an exit code or a measured second; never a chat's claim.
"""
import argparse
import json
import sys
from pathlib import Path

PASS = 'PASS'
FAIL = 'FAIL'
FIX = 'timeout'
KILL = 124
FASTEST = 4.0
SLOWEST = 9.0


def read_text(path):
    try:
        return path.read_text(errors='replace')
    except OSError:
        return ''


def read_number(path, kind):
    """A saved exit code or second count, or None when the file is missing or not a number."""
    text = read_text(path).strip()
    try:
        return kind(text)
    except ValueError:
        return None


def check_blocked(evidence):
    code = read_number(evidence / 'blocked.exit', int)
    why = read_text(evidence / 'blocked.err')
    if code is None:
        return FAIL, 'no blocked.exit, so the blocked command was never fed to the hook'
    if code != 2:
        return FAIL, 'the hook exited %d on a hung test command, not 2' % code
    lines = why.splitlines()
    if len(lines) != 1:
        return FAIL, 'the block was %d lines, not one' % len(lines)
    if FIX not in why:
        return FAIL, 'the block names no fix, so the chat does not learn to add a timeout'
    if 'unittest' not in why:
        return FAIL, 'the block does not name the runner it caught'
    return PASS, 'exit 2, one line naming the runner and the timeout fix'


def check_allowed(evidence):
    code = read_number(evidence / 'allowed.exit', int)
    why = read_text(evidence / 'allowed.err')
    if code is None:
        return FAIL, 'no allowed.exit, so the wrapped command was never fed to the hook'
    if code != 0:
        return FAIL, 'the hook exited %d on a command already under timeout, not 0' % code
    if why.strip():
        return FAIL, 'the hook printed on stderr for an allowed command: %s' % why.strip()[:80]
    return PASS, 'a command already under timeout passes with no output'


def check_killed(evidence):
    code = read_number(evidence / 'killed.exit', int)
    seconds = read_number(evidence / 'killed.seconds', float)
    if code is None or seconds is None:
        return FAIL, 'no killed.exit or killed.seconds, so no timeout was measured'
    if code != KILL:
        return FAIL, 'the wrapped sleep exited %d, not %d, so it did not run out of time' % (code, KILL)
    if not FASTEST <= seconds <= SLOWEST:
        return FAIL, 'the sleep died after %.1fs, outside the %.0fs to %.0fs a 5s timeout gives' % (
            seconds, FASTEST, SLOWEST)
    return PASS, 'a 60s sleep died after %.1fs with exit %d' % (seconds, KILL)


def grade(evidence):
    return [
        ('blocked', check_blocked(evidence)),
        ('allowed', check_allowed(evidence)),
        ('killed', check_killed(evidence)),
    ]


def main(argv):
    parser = argparse.ArgumentParser(description='Grade a verify-test-timeout run.')
    parser.add_argument('evidence', help='evidence directory written by run')
    args = parser.parse_args(argv)

    evidence = Path(args.evidence).expanduser()
    if not evidence.is_dir():
        print('grade.py: evidence directory not found: %s' % evidence, file=sys.stderr)
        return 2
    for name in ('blocked.exit', 'allowed.exit', 'killed.exit', 'killed.seconds', 'meta.json'):
        if not (evidence / name).is_file():
            print('grade.py: no %s in %s' % (name, evidence), file=sys.stderr)
            return 2
    try:
        meta = json.loads(read_text(evidence / 'meta.json'))
    except ValueError:
        meta = None
    if not isinstance(meta, dict):
        print('grade.py: no readable meta.json in %s' % evidence, file=sys.stderr)
        return 2

    checks = grade(evidence)
    verdict = PASS if all(result[0] == PASS for _name, result in checks) else FAIL
    lines = ['%s %s: %s' % (result[0], name, result[1]) for name, result in checks]
    lines.append('VERDICT %s' % verdict)
    output = '\n'.join(lines) + '\n'

    (evidence / 'verdict.txt').write_text(output)
    print(output, end='')
    return 0 if verdict == PASS else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
