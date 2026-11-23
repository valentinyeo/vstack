#!/usr/bin/env python3
"""Launch verify-vstack: build the scratch HOME a chat runs in, then install the checkout.

Launch means: a temp HOME with its own .claude and .local/bin, the hook wiring shape a chat
on this server has (hook entries only, no tokens or credentials), and one run of the
checkout's own ./install into it. The real ~/.claude and ~/.local/bin are never touched.

pstack create-verification-skill, "Launch": reach a usable state from an empty data dir.
Root cause: VSTA-137, https://app.hypertask.ai/detail/project-13556/137

launch.py --checkout DIR --scratch DIR [--base REF] [--wiring FILE] [--evidence DIR]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

GLOBAL_WIRING = Path.home() / '.claude/settings.json'
HOOK_FILE = re.compile(r'[\w./$~-]*/hooks/([\w.-]+)')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], text=True,
                          capture_output=True, check=False)


def base_commit(checkout, base):
    """The commit a change is measured against: the named ref, else its merge base with HEAD."""
    for args in (('rev-parse', base), ('merge-base', base, 'HEAD')):
        result = git(checkout, *args)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return ''


def tree(path):
    """Path -> text, or empty when the file is absent."""
    try:
        return Path(path).read_text()
    except OSError:
        return ''


def parse_settings(text):
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def hook_commands(settings):
    """Every command a settings file registers, as (event, matcher, command)."""
    for event, groups in (settings.get('hooks') or {}).items():
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            for hook in group.get('hooks') or []:
                if isinstance(hook, dict) and isinstance(hook.get('command'), str):
                    yield event, group.get('matcher'), hook['command']


def shipped_hooks(checkout):
    folder = Path(checkout) / 'hooks'
    return {path.name for path in folder.iterdir()} if folder.is_dir() else set()


def base_hooks(checkout, commit):
    if not commit:
        return set()
    result = git(checkout, 'ls-tree', '--name-only', commit, 'hooks/')
    return {Path(line).name for line in result.stdout.split() if line}


def retired_hooks(checkout):
    """The hook names the checkout's install retires, read from the script itself."""
    text = tree(Path(checkout) / 'install')
    match = re.search(r'^retired_hooks=\(([^)]*)\)', text, re.M)
    return set(match.group(1).split()) if match else set()


def base_settings(checkout, commit):
    if not commit:
        return {}
    result = git(checkout, 'show', f'{commit}:.claude/settings.json')
    return parse_settings(result.stdout) if result.returncode == 0 else {}


def rewrite(command, scratch):
    """Point the command at the scratch HOME. Never leave a command aimed at the real one."""
    home = str(Path.home())
    return command.replace(home, scratch)


def seed(checkout, scratch, commit, wiring_file):
    """Build the scratch global settings from the wiring a chat already has.

    Entries are kept only when they name a hook this repo ships, shipped at base, or
    retired by install. That keeps a personal hook out of the scratch chat, and every
    entry left is one the checkout is responsible for.
    """
    owned = shipped_hooks(checkout) | base_hooks(checkout, commit) | retired_hooks(checkout)
    sources = [wiring_file] if wiring_file else [GLOBAL_WIRING]
    settings = {'hooks': {}}
    seen = set()
    for source in sources:
        for event, matcher, command in hook_commands(parse_settings(tree(source))):
            match = HOOK_FILE.search(command)
            if not match or match.group(1) not in owned or command in seen:
                continue
            seen.add(command)
            group = {'hooks': [{'type': 'command', 'command': rewrite(command, scratch)}]}
            if matcher:
                group['matcher'] = matcher
            settings['hooks'].setdefault(event, []).append(group)
    project = base_settings(checkout, commit)
    for event, matcher, command in hook_commands(project):
        match = HOOK_FILE.search(command)
        if not match or match.group(1) not in owned or command in seen:
            continue
        seen.add(command)
        group = {'hooks': [{'type': 'command', 'command': rewrite(command, scratch)}]}
        if matcher:
            group['matcher'] = matcher
        settings['hooks'].setdefault(event, []).append(group)
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', required=True)
    parser.add_argument('--scratch', required=True)
    parser.add_argument('--base', default='origin/main')
    parser.add_argument('--wiring', help='settings file to take the global wiring shape from')
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()

    checkout = Path(args.checkout).resolve()
    scratch = Path(args.scratch).resolve()
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    commit = git(checkout, 'rev-parse', 'HEAD').stdout.strip()
    base = base_commit(checkout, args.base)

    for folder in ('.claude/hooks', '.claude/skills', '.local/bin', '.local/share',
                   '.local/state', '.config'):
        (scratch / folder).mkdir(parents=True, exist_ok=True)

    settings = seed(checkout, str(scratch), base, args.wiring and str(Path(args.wiring).resolve()))
    (scratch / '.claude/settings.json').write_text(json.dumps(settings, indent=2) + '\n')

    env = {key: value for key, value in os.environ.items()
           if key not in ('VSTACK_DIR', 'VSTACK_INSTALL_ANYWHERE')}
    env.update(HOME=str(scratch), VSTACK_INSTALL_ANYWHERE='1',
               VSTACK_DIR=str(scratch / '.local/share/vstack'))
    install = subprocess.run(['bash', str(checkout / 'install')], env=env,
                             capture_output=True, text=True)
    (evidence / 'install.txt').write_text(
        f'$ HOME={scratch} VSTACK_INSTALL_ANYWHERE=1 VSTACK_DIR={scratch}/.local/share/vstack '
        f'bash {checkout}/install\n{install.stdout}{install.stderr}'
        f'exit: {install.returncode}\n')

    record = {
        'checkout': str(checkout), 'commit': commit, 'base_ref': args.base, 'base': base,
        'install_exit': install.returncode,
        'seed_source': str(args.wiring or GLOBAL_WIRING),
        'seeded_commands': sum(len(group['hooks']) for groups in settings['hooks'].values()
                               for group in groups),
    }
    (evidence / 'launch.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f"launch: {checkout} at {commit or 'unknown'}, base {base or 'none'}, "
          f"{record['seeded_commands']} wiring entries, install exit {install.returncode}")
    return 0 if install.returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
