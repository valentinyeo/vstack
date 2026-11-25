#!/usr/bin/env python3
"""Register a vstack hook for every chat on this server, once, in user settings.

A hook named only in a repo's .claude/settings.json fires only in chats whose cwd is that
repo. Multi Bot chats run from their own project, so the hook never ran there (VSTA-204,
VSTA-207). ./install calls this for each hook a chat must carry wherever it runs, and a
second run registers nothing. Unrelated registrations are preserved.

register-user-hook.py --event PreToolUse --matcher Bash \
  --matcher 'mcp__.*create_pull_request' --entry '{"type": "command", ...}'

--replace also drops an older registration of the same script that this entry supersedes, such
as a loose hook wired by its full path before vstack shipped it (VSTA-289).
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import sys


def hook_name(entry):
    """The script an entry runs: the run-hook operand, by file name."""
    words = shlex.split(str(entry.get('command') or ''))
    return Path(words[-1]).name if words else ''


def already(data, event, matcher, name):
    """True when this event and matcher already carries this script."""
    for group in data.get('hooks', {}).get(event, []):
        if not isinstance(group, dict) or group.get('matcher') != matcher:
            continue
        for hook in group.get('hooks', []):
            if isinstance(hook, dict) and name in str(hook.get('command') or ''):
                return True
    return False


def register(data, entry, events, matchers, replace=False):
    """Add the entry only where it is missing. Return True when the file must be written."""
    name = hook_name(entry)
    command = str(entry.get('command') or '')
    changed = False
    for event in events:
        groups = data.setdefault('hooks', {}).setdefault(event, [])
        if replace:
            for group in groups:
                hooks = group.get('hooks') or []
                kept = [hook for hook in hooks
                        if not (isinstance(hook, dict) and hook_name(hook) == name
                                and str(hook.get('command') or '') != command)]
                if len(kept) != len(hooks):
                    group['hooks'] = kept
                    changed = True
            groups[:] = [group for group in groups if group.get('hooks')]
        for matcher in matchers or [None]:
            if already(data, event, matcher, name):
                continue
            # Join the group with the same matcher so one event keeps one list.
            group = next((group for group in groups if isinstance(group, dict)
                          and group.get('matcher') == matcher), None)
            if group is None:
                group = {'hooks': []} if matcher is None else {'matcher': matcher, 'hooks': []}
                groups.append(group)
            group.setdefault('hooks', []).append(dict(entry))
            changed = True
    return changed


def load(path):
    """The existing settings, or None when a file this cannot read must be left alone."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        print(f'register-user-hook: {path} is not JSON; left alone', file=sys.stderr)
        return None
    if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict):
        print(f'register-user-hook: {path} has no hooks object; left alone', file=sys.stderr)
        return None
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', required=True,
                        help='the JSON hook entry install publishes, written verbatim')
    parser.add_argument('--event', action='append', required=True, dest='events',
                        help='Claude Code hook event, repeatable')
    parser.add_argument('--matcher', action='append', default=[], dest='matchers',
                        help='tool matcher applied to every event, repeatable; omit for all')
    parser.add_argument('--settings', type=Path,
                        default=Path.home() / '.claude/settings.json')
    parser.add_argument('--replace', action='store_true',
                        help='drop an older registration of this script that this entry supersedes')
    args = parser.parse_args(argv)

    try:
        entry = json.loads(args.entry)
    except ValueError:
        print('register-user-hook: --entry is not JSON', file=sys.stderr)
        return 1
    name = hook_name(entry) if isinstance(entry, dict) else ''
    if not name:
        print('register-user-hook: --entry names no hook script', file=sys.stderr)
        return 1

    path = args.settings
    data = load(path)
    if data is None:
        return 0
    if not register(data, entry, args.events, args.matchers, replace=args.replace):
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.vstack-tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    if path.is_file():
        temporary.chmod(path.stat().st_mode & 0o777)
    os.replace(temporary, path)
    print(f'register-user-hook: registered {name} in {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
