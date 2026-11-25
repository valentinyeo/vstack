#!/usr/bin/env python3
"""Wire the valentin-mode start and re-arm lines into Codex.

Claude loads valentin-mode from the skill's own frontmatter hook. Codex runs no skill frontmatter,
so a chat switched from Claude to Codex dropped the mode and its board drain loop (VSTA-305). This
merges the two entries into ~/.codex/hooks.json, the file Codex already reads, and a second install
writes nothing. Antigravity's entry is config/antigravity-hooks.json; ./install links the Pi
extension.

install-mode-start-hook.py [--home DIR] [--self-test]
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

LAUNCHER = '"$HOME/.local/share/vstack/hooks/run-hook"'
ADAPTER = '"$HOME/.claude/hooks/harness-start.py"'
HOOK_TIMEOUT = 5
SCRIPT = 'harness-start.py'
EVENTS = {'start': 'SessionStart', 'prompt': 'UserPromptSubmit'}


def entry(harness, event):
    return {
        'type': 'command',
        'command': f'{LAUNCHER} {ADAPTER} --harness {harness} --event {event}',
        'timeout': HOOK_TIMEOUT,
    }


def is_mode_start_command(command, harness, event):
    text = str(command or '')
    return (SCRIPT in text and f'--harness {harness}' in text and f'--event {event}' in text)


def load_json_dict(path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        print(f'install-mode-start-hook: {path} is not JSON; left alone', file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f'install-mode-start-hook: {path} is not a JSON object; left alone', file=sys.stderr)
        return None
    if not isinstance(data.get('hooks'), dict):
        print(f'install-mode-start-hook: {path} has no hooks object; left alone', file=sys.stderr)
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


def merge(path, harness, events):
    data = load_json_dict(path)
    if data is None:
        return False
    changed = False
    hooks = data.setdefault('hooks', {})
    for event in events:
        name = EVENTS[event]
        groups = hooks.setdefault(name, [])
        if not isinstance(groups, list):
            print(f'install-mode-start-hook: {path} {name} is not a list; left alone', file=sys.stderr)
            return False
        if any(is_mode_start_command(hook.get('command'), harness, event)
               for group in groups if isinstance(group, dict)
               for hook in group.get('hooks', []) if isinstance(hook, dict)):
            continue
        group = next((g for g in groups if isinstance(g, dict) and g.get('matcher') is None), None)
        if group is None:
            group = {'hooks': []}
            groups.append(group)
        group.setdefault('hooks', []).append(entry(harness, event))
        changed = True
    if not changed:
        return False
    atomic_write_json(path, data)
    return True


def install(home):
    target = home / '.codex' / 'hooks.json'
    return [target] if merge(target, 'codex', ('start', 'prompt')) else []


def self_test():
    bad = []
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        codex = home / '.codex' / 'hooks.json'
        codex.parent.mkdir(parents=True)
        codex.write_text(json.dumps({'hooks': {
            'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo keep-start',
                                         'timeout': 10}]}],
            'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'echo keep-prompt'}]}],
        }}))
        codex.chmod(0o600)

        first = install(home)
        if len(first) != 1:
            bad.append(f'the first install wires the Codex hook file, got {first!r}')
        if install(home):
            bad.append('a second install changes nothing')
        if codex.stat().st_mode & 0o777 != 0o600:
            bad.append('the hook file keeps its permissions')

        data = json.loads(codex.read_text())
        for event in ('SessionStart', 'UserPromptSubmit'):
            hooks = [hook for group in data['hooks'][event] for hook in group['hooks']]
            mine = [hook for hook in hooks if SCRIPT in hook.get('command', '')]
            if len(mine) != 1:
                bad.append(f'{event} carries exactly one harness-start entry, got {len(mine)}')
            elif mine[0].get('timeout') != HOOK_TIMEOUT:
                bad.append(f'{event} entry is capped at {HOOK_TIMEOUT}s')
            if not any('echo keep' in hook.get('command', '') for hook in hooks):
                bad.append(f'{event} lost the hook that was already registered')

        broken = home / 'broken' / 'hooks.json'
        broken.parent.mkdir(parents=True)
        broken.write_text('{not json')
        if merge(broken, 'codex', ('start',)) or broken.read_text() != '{not json':
            bad.append('an unreadable hook file is left alone')

        empty = home / 'empty' / 'hooks.json'
        empty.parent.mkdir(parents=True)
        empty.write_text('[]')
        if merge(empty, 'codex', ('start',)) or empty.read_text() != '[]':
            bad.append('a non-object hook file is left alone')

        fresh = home / 'fresh'
        if not install(fresh):
            bad.append('a missing hook file is created')
        else:
            created = json.loads((fresh / '.codex/hooks.json').read_text())
            if sorted(created['hooks']) != ['SessionStart', 'UserPromptSubmit']:
                bad.append(f'a fresh file gets both events, got {sorted(created["hooks"])}')
    print('install-mode-start-hook self-test ok' if not bad else
          f'install-mode-start-hook self-test FAILED {bad}')
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
        print('install-mode-start-hook: updated ' + ', '.join(str(p) for p in changed))
    return 0


if __name__ == '__main__':
    sys.exit(main())
