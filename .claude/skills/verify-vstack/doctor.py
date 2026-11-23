#!/usr/bin/env python3
"""Doctor: is this scratch chat worth driving?

Reads only. One line per check, `CHECK <name> PASS|FAIL <detail>`, then `DOCTOR PASS|FAIL`.
A doctor failure stops a run before any chat starts: driving a chat wired to missing hooks
proves nothing, and the chat itself is what breaks.

pstack create-verification-skill, "Doctor": one read-only check that answers "is this
instance worth driving?" Root cause: VSTA-137,
https://app.hypertask.ai/detail/project-13556/137

doctor.py --checkout DIR --scratch DIR --evidence DIR
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HOOK_PATH = re.compile(r'/hooks/([\w.-]+)')
PLUGIN_PATH = re.compile(r'\$CLAUDE_PLUGIN_ROOT/([\w./-]+)')


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def commands(settings):
    """Every registered command, as (event, command)."""
    for event, groups in (settings.get('hooks') or {}).items():
        for group in groups or []:
            for hook in (group or {}).get('hooks') or []:
                if isinstance(hook, dict) and isinstance(hook.get('command'), str):
                    yield event, hook['command']


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], text=True,
                          capture_output=True, check=False)


def base_wiring(checkout, commit):
    """The hook names this checkout's base registered, and the hook files it shipped then."""
    if not commit:
        return set(), set()
    settings = read_json_text(git(checkout, 'show', f'{commit}:.claude/settings.json').stdout)
    registered = {match.group(1) for _, command in commands(settings)
                  for match in [HOOK_PATH.search(command)] if match}
    shipped = {Path(line).name for line in
               git(checkout, 'ls-tree', '--name-only', commit, 'hooks/').stdout.split() if line}
    return registered, shipped


def read_json_text(text):
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def check_settings(scratch, launch):
    path = Path(scratch) / '.claude/settings.json'
    settings = read_json(path)
    if settings is None:
        return False, f'{path} is not JSON'
    return True, f'{launch.get("seeded_commands", 0)} wiring entries from {launch.get("seed_source", "?")}'


def check_base_wiring(checkout, launch):
    """A change must not orphan a hook that chats were already wired to.

    The base wiring is the wiring every chat had before this change. install repairs the
    two settings files this repo owns; the same registration sits in each project's own
    settings, so a hook deleted here stops running there with no error to the user.
    """
    registered, _shipped = base_wiring(checkout, launch.get('base', ''))
    current = {path.name for path in (Path(checkout) / 'hooks').iterdir()}
    missing = sorted(registered - current)
    if missing:
        return False, ('base wiring registers ' + ', '.join(missing)
                       + '; this checkout does not ship them')
    return True, f'{len(registered)} hook names wired at base still ship'


def check_wiring(scratch, checkout):
    settings = read_json(Path(scratch) / '.claude/settings.json') or {}
    home = Path(scratch)
    missing = []
    for event, command in commands(settings):
        match = HOOK_PATH.search(command)
        if not match:
            continue
        name = match.group(1)
        path = (Path(checkout) / 'hooks' / name
                if 'CLAUDE_PROJECT_DIR' in command else home / '.claude/hooks' / name)
        if not path.exists():
            missing.append(f'{event} {name}')
    if missing:
        return False, 'missing hook files: ' + ', '.join(sorted(set(missing)))
    return True, 'every registered hook command names an existing file'


def check_links(scratch, folder):
    """Every link a chat follows must resolve. hypertask-work holds scripts only, no SKILL.md."""
    root = Path(scratch) / folder
    broken = [path.name for path in root.iterdir() if not path.exists()]
    if broken:
        return False, f'{folder}: ' + ', '.join(sorted(broken))
    return True, f'{folder}: {len(list(root.iterdir()))} links resolve'


def check_drive_skill(scratch):
    """The skill Drive loads is the one that must be whole."""
    skill = Path(scratch) / '.claude/skills/valentin-mode/SKILL.md'
    if not skill.is_file():
        return False, f'{skill} is missing'
    return True, 'valentin-mode/SKILL.md is readable through its link'


def check_install(scratch, launch):
    record = read_json(Path(scratch) / '.local/state/vstack/install.json')
    if not record:
        return False, 'install wrote no record at ~/.local/state/vstack/install.json'
    if record.get('commit') != launch.get('commit'):
        return False, f'recorded {record.get("commit")!r}, checkout is {launch.get("commit")!r}'
    return True, f'install recorded {record["commit"][:12]} from {record.get("root")}'


def check_frontmatter(scratch):
    """A skill's own hooks must resolve inside the folder a chat links to."""
    problems = []
    for skill in sorted((Path(scratch) / '.claude/skills').iterdir()):
        document = skill / 'SKILL.md'
        if not document.is_file():
            continue
        text = document.read_text(errors='replace')
        header = text.split('---', 2)[1] if text.startswith('---') else ''
        for target in PLUGIN_PATH.findall(header):
            candidate = skill / target
            if not candidate.exists():
                problems.append(f'{skill.name}: {target}')
    if problems:
        return False, 'frontmatter hooks missing: ' + ', '.join(problems)
    return True, 'skill frontmatter hooks resolve'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', required=True)
    parser.add_argument('--scratch', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    launch = read_json(evidence / 'launch.json') or {}

    checks = [
        ('settings', check_settings(args.scratch, launch)),
        ('base-wiring', check_base_wiring(args.checkout, launch)),
        ('wiring', check_wiring(args.scratch, args.checkout)),
        ('hook-links', check_links(args.scratch, '.claude/hooks')),
        ('skill-links', check_links(args.scratch, '.claude/skills')),
        ('bin-links', check_links(args.scratch, '.local/bin')),
        ('drive-skill', check_drive_skill(args.scratch)),
        ('install', check_install(args.scratch, launch)),
        ('frontmatter', check_frontmatter(args.scratch)),
    ]
    lines = []
    for name, (passed, detail) in checks:
        lines.append(f'CHECK {name} {"PASS" if passed else "FAIL"} {detail}')
    verdict = 'PASS' if all(passed for _, (passed, _detail) in checks) else 'FAIL'
    lines.append(f'DOCTOR {verdict}')
    text = '\n'.join(lines) + '\n'
    (evidence / 'doctor.txt').write_text(text)
    sys.stdout.write(text)
    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
