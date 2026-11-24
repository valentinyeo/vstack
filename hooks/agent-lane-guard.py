#!/usr/bin/env python3
"""PreToolUse guard and worker shim: the agent lane is coordination only, never results.

Valentin's rule (VSTA-249): `hypertask activity add` carries only agent-to-agent
coordination chatter (claims, Next:, branch names, resume commands). Results, verdicts,
proof, done summaries and screenshot or video links belong in a people comment
(`hypertask comment add --kind done|qa`). Real case: the Seamless Session Transitioning
chat posted its MUBO-517 done summary in the agent lane.

agent-lane-guard.py --self-test
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shell = load('test_timeout_guard', Path(__file__).resolve().with_name('test-timeout-guard.py'))

SHELLS = {'bash', 'sh', 'zsh'}
GLOBAL_VALUE_FLAGS = {'--token', '--api-url', '--profile', '--format', '--output'}
TEXT_FLAGS = {'--text', '-t', '--message', '-m'}
TEXT_PREFIXES = ('--text=', '--message=')
FILE_FLAGS = {'--text-file'}
FILE_PREFIXES = ('--text-file=',)

QA_VERDICT = re.compile(r'\bqa[- ]?(?:pass|fail)\b', re.IGNORECASE)
RESULT_WORD = re.compile(
    r'(?<![A-Za-z0-9_/-])'
    r'(?:pass|passed|fail|failed|verified|fixed|done|confirmed|proof|verdict|evidence|shipped)'
    r'(?![A-Za-z0-9_/-])',
    re.IGNORECASE,
)
MEDIA_LINK = re.compile(
    r'https?://\S*(?:screencast2\.com/|loom\.com/|vimeo\.com/|youtu\.?be(?:\.com)?/'
    r'|imgur\.com/|cloudinary\.com/|/attachments?/|/screenshots?/|/videos?/)'
    r'|https?://\S+\.(?:png|jpe?g|webp|gif|svg|mp4|webm|mov|m4v|mkv)(?:[?#\s"\')]|$)'
    r'|(?:^|[\s(])screencast2\.com/\S+',
    re.IGNORECASE,
)
URL = re.compile(r'https?://\S+')
MESSAGE = (
    'BLOCKED by agent-lane-guard: the agent lane is coordination only, not results ({reason}); '
    'post evidence, verdicts and done summaries in plain words with `hypertask comment add --kind done|qa`.'
)


def read_text_file(raw_path, cwd):
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path(cwd) / path
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def activity_text(rest, cwd):
    """Extract the message text for `hypertask activity add`, or None for any other command."""
    words = []
    index = 0
    while index < len(rest) and len(words) < 2:
        word = rest[index]
        if word in ('--help', '-h'):
            return None
        if word in GLOBAL_VALUE_FLAGS:
            index += 2
            continue
        if word.startswith('-'):
            index += 1
            continue
        words.append(word)
        index += 1
    if words != ['activity', 'add']:
        return None
    parts = []
    while index < len(rest):
        word = rest[index]
        if word in ('--help', '-h'):
            return None
        if word in TEXT_FLAGS and index + 1 < len(rest):
            parts.append(rest[index + 1])
            index += 2
            continue
        if word.startswith(TEXT_PREFIXES):
            parts.append(word.split('=', 1)[1])
            index += 1
            continue
        if word in FILE_FLAGS and index + 1 < len(rest):
            parts.append(read_text_file(rest[index + 1], cwd))
            index += 2
            continue
        if word.startswith(FILE_PREFIXES):
            parts.append(read_text_file(word.split('=', 1)[1], cwd))
            index += 1
            continue
        index += 1
    return '\n'.join(part for part in parts if part)


def reason_for(text):
    """Why `activity add` text reads like a result, or None when it is coordination chatter."""
    if not text:
        return None
    if MEDIA_LINK.search(text):
        return 'screenshot or video link'
    cleaned = URL.sub(' ', text)
    qa = QA_VERDICT.search(cleaned)
    if qa:
        return f"result word '{qa.group(0)}'"
    match = RESULT_WORD.search(cleaned)
    if match:
        return f"result word '{match.group(0)}'"
    return None


def check(args, cwd):
    if not args or Path(args[0]).name != 'hypertask':
        return None
    reason = reason_for(activity_text(args[1:], cwd))
    return MESSAGE.format(reason=reason) if reason else None


def verdict(command, cwd='/tmp', depth=0):
    if depth > 8:
        return None
    for args in shell.simple_commands(command):
        args, _wrapped = shell.strip_wrappers(args)
        if not args:
            continue
        if args[0] == 'cd' and len(args) == 2:
            cwd = str(Path(cwd) / args[1])
            continue
        if Path(args[0]).name in SHELLS:
            rest = args[1:]
            while rest:
                word, rest = rest[0], rest[1:]
                if word in {'-o', '-O', '--rcfile', '--init-file'}:
                    rest = rest[1:]
                elif word.startswith('-') and not word.startswith('--') and 'c' in word:
                    if rest:
                        why = verdict(rest[0], cwd, depth + 1)
                        if why:
                            return why
                    break
            continue
        why = check(args, cwd)
        if why:
            return why
    return None


def shim(argv):
    """Stand in for `hypertask` in a worker's PATH: refuse result notes in activity add."""
    if len(argv) < 1:
        print('agent-lane-guard --shim needs REAL, empty when the host lacks it', file=sys.stderr)
        return 2
    real, args = argv[0], argv[1:]
    why = check(['hypertask'] + args, os.getcwd())
    if why:
        print(why, file=sys.stderr)
        return 2
    if not real:
        print('agent-lane-guard: hypertask is not installed on this host', file=sys.stderr)
        return 127
    try:
        os.execv(real, [real] + args)
    except OSError as error:
        print(f'agent-lane-guard: cannot run {real}: {error}', file=sys.stderr)
        return 127


def self_test():
    tests = load('test_agent_lane_guard', ROOT / 'tests/test_agent_lane_guard.py')
    assert Path(tests.HOOK).resolve() == Path(__file__).resolve(), 'self-test must exercise this file'
    suite = unittest.defaultTestLoader.loadTestsFromModule(tests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), 'agent-lane-guard self-test failed'
    blocked = verdict(
        'hypertask activity add MUBO-517 --text '
        '"Done: seamless session transitioning fixed and verified. Proof: https://screencast2.com/v/mubo517"'
    )
    allowed = verdict('hypertask activity add VSTA-249 --text "Next: rebase"')
    assert blocked and allowed is None
    print(f'blocked: {blocked}')
    print(f'allowed: {allowed}')
    print('agent-lane-guard self-test ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
    if sys.argv[1:2] == ['--shim']:
        return shim(sys.argv[2:])
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict) or payload.get('tool_name') != 'Bash':
        return 0
    tool_input = payload.get('tool_input')
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get('command'), str):
        return 0
    cwd = payload.get('cwd')
    why = verdict(tool_input['command'], cwd if isinstance(cwd, str) else '/tmp')
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
