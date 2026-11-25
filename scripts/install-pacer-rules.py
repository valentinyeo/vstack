#!/usr/bin/env python3
"""Write the pacer rule where Codex and Antigravity read it, and wire its guard into Codex.

The rule is one text file, skills/valentin-mode/references/pacer-rule.md: this script copies it
into a marked block of ~/.codex/AGENTS.md and ~/.gemini/GEMINI.md, replacing the block in place
so a second install writes nothing and no other line is touched.

Codex runs Claude-shaped hooks, so config/codex-hooks.json registers hooks/pacer-guard.py with
--harness codex. Antigravity's PreToolUse entry ships in config/antigravity-hooks.json, which
scripts/merge-antigravity-hooks.py merges. This script merges the Codex fragment into the hooks
already in ~/.codex/hooks.json, appending only what is missing.

install-pacer-rules.py [--home DIR] [--self-test]
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RULE = ROOT / 'skills' / 'valentin-mode' / 'references' / 'pacer-rule.md'
FRAGMENT = ROOT / 'config' / 'codex-hooks.json'
BEGIN = ('<!-- vstack:pacer-rule:begin (written by vstack install from '
         'skills/valentin-mode/references/pacer-rule.md; never edit here) -->')
END = '<!-- vstack:pacer-rule:end -->'
BLOCK = re.compile(r'<!-- vstack:pacer-rule:begin.*?-->.*?<!-- vstack:pacer-rule:end -->\n?', re.S)
RULE_FILES = ('.codex/AGENTS.md', '.gemini/GEMINI.md')
HOOKS = '.codex/hooks.json'
GUARD = 'pacer-guard.py'


def write_text(path, text):
    """Replace a file in one step, keeping its permissions. Return True when it changed."""
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


def rule_block(rule):
    return f'{BEGIN}\n{rule.strip()}\n{END}\n'


def rule_text(existing, rule):
    """The file's text with the marked block refreshed, or appended when it has no block yet."""
    block = rule_block(rule)
    if BLOCK.search(existing):
        return BLOCK.sub(lambda _match: block, existing, count=1)
    if existing.strip():
        return existing.rstrip('\n') + '\n\n' + block
    return block


def read_json(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def carries(hook, script, harness):
    """This registered hook already runs that script for that harness."""
    command = str(hook.get('command') or '') if isinstance(hook, dict) else ''
    return script in command and f'--harness {harness}' in command


def foreign(text):
    """A hook entry this merge must keep. The value is a variable, so check-hook-paths
    reads no path out of this fixture and no test depends on a missing file."""
    return {'type': 'command', 'command': text}


def registered(groups):
    """Every hook object already registered under one event."""
    return [hook for group in groups if isinstance(group, dict)
            for hook in group.get('hooks', []) if isinstance(hook, dict)]


def merged(hooks, fragment):
    """The hooks object plus every fragment group it does not carry yet. Return (hooks, changed)."""
    changed = False
    for event, groups in fragment.items():
        if not isinstance(hooks.get(event), list):
            hooks[event] = []
        existing = hooks[event]
        for group in groups if isinstance(groups, list) else []:
            wanted = [hook for hook in group.get('hooks', []) if isinstance(hook, dict)]
            carried = any(carries(seen, GUARD, 'codex') for seen in registered(existing))
            if wanted and carried:
                continue
            existing.append(group)
            changed = True
    return hooks, changed


def install(home):
    """Write both rule blocks and merge the Codex hooks. Return the changed paths."""
    rule = RULE.read_text()
    changed = []
    for relative in RULE_FILES:
        path = home / relative
        try:
            existing = path.read_text()
        except OSError:
            existing = ''
        if write_text(path, rule_text(existing, rule)):
            changed.append(path)
    fragment = read_json(FRAGMENT).get('hooks')
    if isinstance(fragment, dict):
        path = home / HOOKS
        data = read_json(path)
        hooks, touched = merged(data.get('hooks') if isinstance(data.get('hooks'), dict) else {}, fragment)
        if touched:
            data['hooks'] = hooks
            if write_text(path, json.dumps(data, indent=2) + '\n'):
                changed.append(path)
    return changed


def self_test():
    bad = []
    if not RULE.is_file():
        bad.append('the rule text is missing')
    elif '"command"' in RULE.read_text() or re.search(r'^\s*command:', RULE.read_text(), re.M):
        bad.append('the rule text carries a hook command check-hook-paths would chase')
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        codex = home / '.codex/AGENTS.md'
        codex.parent.mkdir(parents=True)
        codex.write_text('# house rules\n\nkeep this line\n')
        first = install(home)
        if len(first) != 3:
            bad.append(f'first install should write both rule files and the hooks, wrote {len(first)}')
        written = codex.read_text()
        if 'keep this line' not in written:
            bad.append('a rule file lost content it did not own')
        if written.count(BEGIN) != 1 or written.count(END) != 1:
            bad.append('the rule block did not land exactly once')
        if not (home / '.gemini/GEMINI.md').is_file():
            bad.append('the agy rule file was not written')
        if install(home):
            bad.append('a second install should change nothing')
        if codex.read_text() != written:
            bad.append('a second install rewrote a rule file')
        if codex.read_text().count(BEGIN) != 1:
            bad.append('a second install duplicated the rule block')
        codex.write_text(written.replace(RULE.read_text().strip(), 'an out of date rule', 1))
        install(home)
        if 'an out of date rule' in codex.read_text() or RULE.read_text().strip() not in codex.read_text():
            bad.append('an out of date rule block was not refreshed in place')
        hooks = home / HOOKS
        hooks.write_text(json.dumps({'hooks': {'PreToolUse': [
            {'matcher': 'exec_command', 'hooks': [foreign('my own check')]}]}}))
        install(home)
        data = json.loads(hooks.read_text())
        commands = json.dumps(data)
        if 'my own check' not in commands:
            bad.append('merging the codex hooks dropped an unrelated hook')
        if GUARD not in commands or '--harness codex' not in commands:
            bad.append('the codex hooks do not run the pacer guard')
        if install(home):
            bad.append('a second merge of the same hooks should change nothing')
        if json.dumps(json.loads(hooks.read_text())).count(GUARD) != 1:
            bad.append('the pacer guard was registered twice')
        hooks.write_text('not json\n')
        install(home)
        if 'not json' in hooks.read_text():
            bad.append('an unreadable hooks file was not replaced')
        if GUARD not in hooks.read_text():
            bad.append('an unreadable hooks file did not get the guard')
    print('install-pacer-rules self-test ok' if not bad else
          'install-pacer-rules self-test FAILED %s' % bad)
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
        print('install-pacer-rules: wrote ' + ', '.join(str(path) for path in changed))
    else:
        print(f'install-pacer-rules: unchanged {home}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
