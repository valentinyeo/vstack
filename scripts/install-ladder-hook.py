#!/usr/bin/env python3
"""Wire `token-ladder hook-prompt` into Claude Code, Codex and Antigravity.

Resolves `token-ladder` through `scripts/bin_path.py` (PATH first, then
`~/.local/bin`). Skips cleanly with a note when `token-ladder` is not installed.
Merges into each harness's hook config idempotently without dropping unrelated
hooks, using a 5-second timeout so a slow collector never stalls a prompt.

install-ladder-hook.py [--home DIR] [--self-test]
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import bin_path

LAUNCHER = '"$HOME/.local/share/vstack/hooks/run-hook"'
ADAPTER = '"$HOME/.claude/hooks/token-ladder-prompt.py"'
HOOK_TIMEOUT = 5
AGY_KEY = 'vstack-token-ladder'


def find_token_ladder(home):
    found = bin_path.find('token-ladder', home)
    if not found:
        return None
    path = Path(found)
    return str(path) if path.is_file() and os.access(path, os.X_OK) else None


def claude_entry(ladder):
    return {
        'type': 'command',
        'command': f'{LAUNCHER} {shlex.quote(ladder)} hook-prompt',
        'timeout': HOOK_TIMEOUT,
    }


def adapter_entry(harness, ladder):
    return {
        'type': 'command',
        'command': f'{LAUNCHER} {ADAPTER} --harness {harness} --ladder {shlex.quote(ladder)}',
        'timeout': HOOK_TIMEOUT,
    }


def is_ladder_prompt_command(command, harness=None):
    text = str(command or '')
    if 'token-ladder-prompt.py' in text:
        return harness is None or f'--harness {harness}' in text
    try:
        words = shlex.split(text)
    except ValueError:
        return 'token-ladder' in text and 'hook-prompt' in text
    has_binary = any(Path(word).name == 'token-ladder' for word in words)
    return has_binary and 'hook-prompt' in words


def load_json_dict(path, label, require_hooks_dict=False):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        print(f'install-ladder-hook: {path} is not JSON; left alone ({label})', file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f'install-ladder-hook: {path} is not a JSON object; left alone ({label})', file=sys.stderr)
        return None
    if require_hooks_dict and not isinstance(data.get('hooks', {}), dict):
        print(f'install-ladder-hook: {path} has no hooks object; left alone ({label})', file=sys.stderr)
        return None
    return data


def atomic_write_json(path, data):
    text = json.dumps(data, indent=2) + '\n'
    try:
        if path.read_text() == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.vstack-tmp')
    temporary.write_text(text)
    if path.is_file():
        temporary.chmod(path.stat().st_mode & 0o777)
    os.replace(temporary, path)
    return True


def merge_user_prompt_submit(path, entry, label, harness=None):
    data = load_json_dict(path, label, require_hooks_dict=True)
    if data is None:
        return False
    groups = data.setdefault('hooks', {}).setdefault('UserPromptSubmit', [])
    if not isinstance(groups, list):
        print(f'install-ladder-hook: {path} UserPromptSubmit is not a list; left alone ({label})',
              file=sys.stderr)
        return False
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get('hooks', []):
            if isinstance(hook, dict) and is_ladder_prompt_command(hook.get('command'), harness):
                return False
    group = next((g for g in groups if isinstance(g, dict) and g.get('matcher') is None), None)
    if group is None:
        group = {'hooks': []}
        groups.append(group)
    group.setdefault('hooks', []).append(dict(entry))
    return atomic_write_json(path, data)


def merge_agy_pre_invocation(path, entry):
    data = load_json_dict(path, 'agy')
    if data is None:
        return False
    desired = {'PreInvocation': [dict(entry)]}
    if data.get(AGY_KEY) == desired:
        return False
    data[AGY_KEY] = desired
    return atomic_write_json(path, data)


def install(home):
    ladder = find_token_ladder(home)
    if not ladder:
        print('install-ladder-hook: token-ladder not installed; skipping prompt hook', file=sys.stderr)
        return []
    changed = []
    targets = (
        (home / '.claude' / 'settings.json',
         lambda p: merge_user_prompt_submit(p, claude_entry(ladder), 'claude')),
        (home / '.codex' / 'hooks.json',
         lambda p: merge_user_prompt_submit(p, adapter_entry('codex', ladder), 'codex', harness='codex')),
        (home / '.gemini' / 'config' / 'hooks.json',
         lambda p: merge_agy_pre_invocation(p, adapter_entry('agy', ladder))),
    )
    for path, apply_fn in targets:
        if apply_fn(path):
            changed.append(path)
    return changed


def self_test():
    bad = []
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        saved_path = os.environ.get('PATH')
        os.environ['PATH'] = '/usr/bin:/bin'
        try:
            if install(home):
                bad.append('missing token-ladder should write nothing')
            if (home / '.claude' / 'settings.json').exists() or (home / '.codex' / 'hooks.json').exists():
                bad.append('missing token-ladder created hook files')

            ladder = home / '.local' / 'bin' / 'token-ladder'
            ladder.parent.mkdir(parents=True)
            ladder.write_text('#!/bin/sh\nexit 0\n')
            ladder.chmod(0o755)

            claude = home / '.claude' / 'settings.json'
            claude.parent.mkdir(parents=True)
            claude.write_text(json.dumps({
                'env': {'KEEP': '1'},
                'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'echo keep'}]}]},
            }))
            claude.chmod(0o600)

            codex = home / '.codex' / 'hooks.json'
            codex.parent.mkdir(parents=True)
            codex.write_text(json.dumps({
                'hooks': {'PreToolUse': [{'hooks': [{'type': 'command', 'command': 'echo pre'}]}]},
            }))

            agy = home / '.gemini' / 'config' / 'hooks.json'
            agy.parent.mkdir(parents=True)
            agy.write_text(json.dumps({'other': {'enabled': True}}))

            first = install(home)
            if len(first) != 3:
                bad.append(f'first install expected 3 writes, got {len(first)}')
            if claude.stat().st_mode & 0o777 != 0o600:
                bad.append('claude settings mode changed')
            if install(home):
                bad.append('second install should be idempotent')

            c_data = json.loads(claude.read_text())
            if c_data.get('env') != {'KEEP': '1'}:
                bad.append('claude env lost')
            c_hooks = [h for g in c_data['hooks']['UserPromptSubmit'] for h in g['hooks']]
            if len(c_hooks) != 2 or c_hooks[1].get('timeout') != 5:
                bad.append(f'claude UserPromptSubmit wrong: {c_hooks!r}')

            x_data = json.loads(codex.read_text())
            if 'PreToolUse' not in x_data['hooks']:
                bad.append('codex existing hook lost')
            x_hooks = [h for g in x_data['hooks']['UserPromptSubmit'] for h in g['hooks']]
            if len(x_hooks) != 1 or '--harness codex' not in x_hooks[0]['command']:
                bad.append(f'codex UserPromptSubmit wrong: {x_hooks!r}')

            a_data = json.loads(agy.read_text())
            if a_data.get('other') != {'enabled': True}:
                bad.append('agy existing hook lost')
            a_hooks = a_data.get(AGY_KEY, {}).get('PreInvocation', [])
            if len(a_hooks) != 1 or '--harness agy' not in a_hooks[0]['command']:
                bad.append(f'agy PreInvocation wrong: {a_hooks!r}')
        finally:
            if saved_path is None:
                os.environ.pop('PATH', None)
            else:
                os.environ['PATH'] = saved_path
    print('install-ladder-hook self-test ok' if not bad else
          f'install-ladder-hook self-test FAILED {bad}')
    return 1 if bad else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=None,
                        help='home to write into; defaults to $HOME')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    home = args.home or Path(os.environ.get('HOME') or Path.home())
    changed = install(home)
    if changed:
        print('install-ladder-hook: updated ' + ', '.join(str(p) for p in changed))
    return 0


if __name__ == '__main__':
    sys.exit(main())
