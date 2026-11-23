#!/usr/bin/env python3
"""Install hook commands through run-hook, preserving unrelated registrations.

Skill frontmatter is rendered at install time so its source needs no second,
hand-maintained command format. Scripts and supporting files remain symlinks.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = '"$HOME/.local/share/vstack/hooks/run-hook"'


def wrap(command):
    """Wrap a direct script command, or vstack's former missing-file shell guard."""
    words = shlex.split(command)
    if not words or any(Path(word).name == 'run-hook' for word in words):
        return command
    if words[:2] == ['sh', '-c'] and len(words) == 3:
        match = re.fullmatch(r'f="([^"]+)"; \[ -f "\$f" \] \|\| exit 0; exec (.+)', words[2])
        if not match:
            return command
        command = match[2].replace('"$f"', '"' + match[1] + '"')
        words = shlex.split(command)
    if Path(words[0]).name in ('python3', 'python', 'sh', 'bash', 'node'):
        if len(words) < 2 or words[1].startswith('-'):
            raise ValueError(f'cannot wrap {command!r}; use run-hook <script> args')
        command = command[len(words[0]):].lstrip()
    elif '/' not in words[0]:
        raise ValueError(f'cannot wrap {command!r}; use run-hook <script> args')
    return LAUNCHER + ' ' + command


def install_skill(skill, home):
    text = (skill / 'SKILL.md').read_text()
    front, body = text.removeprefix('---\n').split('\n---', 1)
    front = re.sub(r'^(\s*command:)\s*(.+)$',
                   lambda match: match[1] + ' ' + wrap(match[2]), front, flags=re.M)
    target = home / '.local/state/vstack/skills' / skill.name
    if target.is_symlink():
        target.unlink()
    target.mkdir(parents=True, exist_ok=True)
    for source in skill.iterdir():
        if source.name == 'SKILL.md':
            continue
        link = target / source.name
        temporary = link.with_name(link.name + '.vstack-tmp')
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(source.resolve())
        os.replace(temporary, link)
    temporary = target / 'SKILL.md.vstack-tmp'
    temporary.write_text('---\n' + front + '\n---' + body)
    os.replace(temporary, target / 'SKILL.md')
    return target


def owned(command, home):
    """Only scripts this checkout ships are migrated in user settings."""
    expanded = command.replace('$HOME', str(home)).replace('~/', str(home) + '/')
    expanded = expanded.replace('${HOME}', str(home)).replace('$CLAUDE_PROJECT_DIR', str(ROOT))
    roots = ((home / '.claude/hooks', ROOT / 'hooks'),
             (home / '.local/share/vstack', ROOT), (ROOT, ROOT))
    # Paths can be inside the quoted body of a legacy sh -c command.
    for token in re.findall(r'[^\s\'";=]+', expanded):
        path = Path(token)
        for prefix, source in roots:
            if path.is_relative_to(prefix) and (source / path.relative_to(prefix)).is_file():
                return True
    return False


def migrate(path, home):
    if path.resolve().is_relative_to(Path('/home/inne')):
        return
    if not path.is_file():
        return
    data = json.loads(path.read_text())
    changed = False
    for groups in data.get('hooks', {}).values():
        for group in groups:
            for hook in group.get('hooks', []):
                command = hook.get('command')
                if not isinstance(command, str) or not owned(command, home):
                    continue
                replacement = wrap(command)
                if replacement != command:
                    hook['command'] = replacement
                    changed = True
    if changed:
        temporary = path.with_name(path.name + '.vstack-tmp')
        temporary.write_text(json.dumps(data, indent=2) + '\n')
        temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill', type=Path)
    args = parser.parse_args()
    home = Path.home()
    if args.skill:
        print(install_skill(args.skill.resolve(), home))
    else:
        for directory in (home / '.claude', ROOT / '.claude'):
            for path in directory.glob('settings*.json'):
                migrate(path, home)


if __name__ == '__main__':
    main()
