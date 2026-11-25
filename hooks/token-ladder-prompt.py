#!/usr/bin/env python3
"""Prompt-hook adapter for `token-ladder hook-prompt` on Codex and Antigravity.

Claude Code reads plain stdout from `token-ladder hook-prompt` directly. Codex
expects `hookSpecificOutput.additionalContext` JSON for `UserPromptSubmit`, and
Antigravity (`agy`) expects `injectSteps` JSON for `PreInvocation`. Because
Antigravity fires `PreInvocation` before every model call in a turn, the `agy`
path emits at most once per `(conversationId, initialNumSteps)` turn.

Fails open: missing binary, non-zero exit, timeout or empty output prints `{}`
and exits 0 so a slow or broken collector never stalls a prompt.

token-ladder-prompt.py --harness codex|agy [--ladder PATH] [--timeout SECONDS]
token-ladder-prompt.py --self-test
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

CODEX = 'codex'
AGY = 'agy'
DEFAULT_TIMEOUT = 4.0


def find_ladder(explicit=None, home=None):
    if explicit:
        path = Path(explicit)
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    found = shutil.which('token-ladder')
    if found:
        return found
    local = Path(home or Path.home()) / '.local' / 'bin' / 'token-ladder'
    return str(local) if local.is_file() and os.access(local, os.X_OK) else None


def agy_state_file(home, conversation_id):
    digest = hashlib.sha256(conversation_id.encode('utf-8')).hexdigest()[:32]
    return Path(home) / '.local' / 'state' / 'vstack' / 'ladder-prompt-agy' / f'{digest}.step'


def as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value.strip())
    return None


def should_emit_agy(payload, home):
    conversation_id = payload.get('conversationId')
    initial_steps = as_int(payload.get('initialNumSteps'))
    if (isinstance(conversation_id, str) and conversation_id.strip()
            and initial_steps is not None):
        marker = agy_state_file(home, conversation_id.strip())
        step_text = str(initial_steps)
        try:
            if marker.is_file() and marker.read_text().strip() == step_text:
                return False
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(step_text)
        except OSError:
            pass
        return True
    invocation = as_int(payload.get('invocationNum'))
    if invocation is not None and invocation > 1:
        return False
    return True


def stdin_for_ladder(payload, harness):
    if harness == AGY:
        conversation_id = payload.get('conversationId')
        if isinstance(conversation_id, str) and conversation_id.strip():
            return json.dumps({'session_id': conversation_id.strip()})
        return '{}'
    return json.dumps(payload)


def format_output(text, harness):
    cleaned = text.strip()
    if not cleaned:
        return {}
    if harness == CODEX:
        try:
            parsed = json.loads(cleaned)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get('hookSpecificOutput'), dict):
            return parsed
        return {
            'hookSpecificOutput': {
                'hookEventName': 'UserPromptSubmit',
                'additionalContext': cleaned,
            }
        }
    return {
        'injectSteps': [
            {
                'systemMessage': {
                    'systemMessage': cleaned,
                }
            }
        ],
        'terminationBehavior': '',
    }


def run_prompt(harness, payload, ladder=None, timeout=DEFAULT_TIMEOUT, home=None):
    home = Path(home or Path.home())
    if harness == AGY and not should_emit_agy(payload, home):
        return {}
    binary = find_ladder(ladder, home)
    if not binary:
        return {}
    try:
        done = subprocess.run(
            [binary, 'hook-prompt'],
            input=stdin_for_ladder(payload, harness),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if done.returncode != 0:
        return {}
    return format_output(done.stdout, harness)


def self_test():
    bad = []
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        fake = home / '.local' / 'bin' / 'token-ladder'
        fake.parent.mkdir(parents=True)
        fake.write_text(
            '#!/usr/bin/env python3\n'
            'import json, sys\n'
            'if sys.argv[1:] != ["hook-prompt"]:\n'
            '    sys.exit(2)\n'
            'data = json.loads(sys.stdin.read() or "{}")\n'
            'print("Token ladder: Claude ON; Codex ON sid=" + str(data.get("session_id", "")))\n'
        )
        fake.chmod(0o755)

        codex_out = run_prompt(CODEX, {'session_id': 's1'}, ladder=str(fake), home=home)
        specific = codex_out.get('hookSpecificOutput', {})
        if specific.get('hookEventName') != 'UserPromptSubmit' or 'sid=s1' not in specific.get('additionalContext', ''):
            bad.append(f'codex output wrong: {codex_out!r}')

        agy_first = run_prompt(AGY, {'conversationId': 'c1', 'initialNumSteps': 4, 'invocationNum': 1},
                               ladder=str(fake), home=home)
        steps = agy_first.get('injectSteps') or []
        if not steps or 'sid=c1' not in steps[0].get('systemMessage', {}).get('systemMessage', ''):
            bad.append(f'agy first turn wrong: {agy_first!r}')

        agy_repeat = run_prompt(AGY, {'conversationId': 'c1', 'initialNumSteps': 4, 'invocationNum': 2},
                                ladder=str(fake), home=home)
        if agy_repeat != {}:
            bad.append(f'agy repeat in same turn should be empty: {agy_repeat!r}')

        agy_string_first = run_prompt(AGY, {'conversationId': 'c2', 'initialNumSteps': '4', 'invocationNum': 1},
                                      ladder=str(fake), home=home)
        if not agy_string_first.get('injectSteps'):
            bad.append(f'agy numeric-string steps should emit once: {agy_string_first!r}')

        agy_string_repeat = run_prompt(AGY, {'conversationId': 'c2', 'initialNumSteps': '4', 'invocationNum': 1},
                                       ladder=str(fake), home=home)
        if agy_string_repeat != {}:
            bad.append(f'agy numeric-string steps should dedupe: {agy_string_repeat!r}')

        agy_next = run_prompt(AGY, {'conversationId': 'c1', 'initialNumSteps': 9, 'invocationNum': 1},
                              ladder=str(fake), home=home)
        if not agy_next.get('injectSteps'):
            bad.append(f'agy next turn should emit again: {agy_next!r}')

        if run_prompt(CODEX, {}, ladder=str(home / 'missing'), home=home) != {}:
            bad.append('missing binary should fail open to {}')

        silent = home / 'silent-ladder'
        silent.write_text('#!/bin/sh\nexit 0\n')
        silent.chmod(0o755)
        if run_prompt(CODEX, {}, ladder=str(silent), home=home) != {}:
            bad.append('empty stdout should return {}')

        slow = home / 'slow-ladder'
        slow.write_text('#!/bin/sh\nsleep 2\necho late\n')
        slow.chmod(0o755)
        if run_prompt(CODEX, {}, ladder=str(slow), timeout=0.1, home=home) != {}:
            bad.append('timeout should fail open to {}')

    print('token-ladder-prompt self-test ok' if not bad else
          f'token-ladder-prompt self-test FAILED {bad}')
    return 1 if bad else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', choices=(CODEX, AGY))
    parser.add_argument('--ladder', default=None)
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.harness:
        parser.error('--harness is required unless --self-test is passed')
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ''
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    answer = run_prompt(args.harness, payload, ladder=args.ladder, timeout=args.timeout)
    print(json.dumps(answer))
    return 0


if __name__ == '__main__':
    sys.exit(main())
