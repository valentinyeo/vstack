#!/usr/bin/env python3
"""Merge vstack's Antigravity hook fragment into ~/.gemini/config/hooks.json.

AGY reads global hooks only from ~/.gemini/config/hooks.json, not
~/.gemini/antigravity-cli/settings.json. ./install calls this after linking skills.

merge-antigravity-hooks.py --self-test
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = ROOT / 'config' / 'antigravity-hooks.json'


def merge_into(target_path: Path, fragment: dict) -> bool:
    """Return True when the file changed."""
    if target_path.is_file():
        try:
            existing = json.loads(target_path.read_text())
        except (OSError, json.JSONDecodeError):
            existing = {}
    else:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    changed = False
    for key, value in fragment.items():
        if existing.get(key) != value:
            existing[key] = value
            changed = True
    if not changed:
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_suffix(target_path.suffix + '.vstack-tmp')
    temporary.write_text(json.dumps(existing, indent=2) + '\n')
    os.replace(temporary, target_path)
    return True


def self_test():
    bad = []
    if not FRAGMENT.is_file():
        bad.append('fragment file missing')
    else:
        fragment = json.loads(FRAGMENT.read_text())
        block = fragment.get('vstack-valentin-mode', {})
        if 'PreToolUse' not in block or 'Stop' not in block:
            bad.append('fragment missing valentin-mode events')
        commands = json.dumps(block)
        if 'context.py' not in commands or 'idle-stop.py' not in commands:
            bad.append('fragment missing hook commands')
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        target = home / '.gemini' / 'config' / 'hooks.json'
        target.parent.mkdir(parents=True)
        target.write_text('{"other-hook":{"enabled":false}}\n')
        if not merge_into(target, {'vstack-valentin-mode': {'Stop': []}}):
            bad.append('first merge should change file')
        data = json.loads(target.read_text())
        if data.get('other-hook', {}).get('enabled') is not False:
            bad.append('unrelated hook should be preserved')
        if 'vstack-valentin-mode' not in data:
            bad.append('fragment key should land')
        if merge_into(target, {'vstack-valentin-mode': {'Stop': []}}):
            bad.append('identical merge should be a no-op')
        target.chmod(0o600)
        target.write_bytes(b'{')
        merge_into(target, {'vstack-valentin-mode': {'PreToolUse': []}})
        data = json.loads(target.read_text())
        if 'vstack-valentin-mode' not in data:
            bad.append('bad json should be replaced')
    print('merge-antigravity-hooks self-test ok' if not bad else
          'merge-antigravity-hooks self-test FAILED %s' % bad)
    return 1 if bad else 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if argv == ['--self-test']:
        return self_test()
    if len(argv) > 1:
        print('usage: merge-antigravity-hooks.py [hooks.json]', file=sys.stderr)
        return 2
    home = Path(os.environ.get('HOME', '~')).expanduser()
    target = Path(argv[0]) if argv else home / '.gemini' / 'config' / 'hooks.json'
    if not FRAGMENT.is_file():
        print('merge-antigravity-hooks: missing %s' % FRAGMENT, file=sys.stderr)
        return 1
    fragment = json.loads(FRAGMENT.read_text())
    if merge_into(target, fragment):
        print('merge-antigravity-hooks: updated %s' % target)
    else:
        print('merge-antigravity-hooks: unchanged %s' % target)
    return 0


if __name__ == '__main__':
    sys.exit(main())