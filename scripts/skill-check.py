#!/usr/bin/env python3
"""skill-check: what a new Claude Code session loads stays lean.

  skill-check.py [--home DIR] [--extra-skills-dir DIR ...] [--extra-commands-dir DIR ...]
                 [--budget N] [--retired-file F] [--allow-file F] [--json] [--out FILE]
                 [--host-label NAME]

It reads the loaded set: user skills and commands, plus the skills and commands of
plugins that settings.json enables. It reports dead symlinks, duplicate skill names,
retired terms in user files, and a visible description budget over the limit.

Exit 0 with no findings, 1 with findings, 2 on a usage error or an unexpected
failure. A crash never looks like a healthy run. Standard library only.
"""
import argparse
import datetime
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_BUDGET = 20000
USER_SKILLS = 'user skills'
USER_COMMANDS = 'user commands'
PLUGINS = 'plugins'
SOURCES = (USER_SKILLS, USER_COMMANDS, PLUGINS)


class Item:
    """One skill or command a session can see, hidden or not."""

    def __init__(self, kind, name, description, hidden, origin, source, path):
        self.kind = kind
        self.name = name
        self.description = description
        self.hidden = hidden
        self.origin = origin
        self.source = source
        self.path = path

    @property
    def bytes(self):
        if self.hidden:
            return 0
        return len((self.name + self.description).encode('utf-8'))


def read_lines(path):
    try:
        return path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []


def read_entries(path):
    """One entry per line, `#` starts a comment."""
    entries = set()
    for line in read_lines(path):
        entry = line.split('#', 1)[0].strip()
        if entry:
            entries.add(entry)
    return entries


def parse_block(lines):
    """Parse simple YAML frontmatter lines by hand: plain, quoted, folded, literal."""
    meta = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line[:1].isspace():
            continue
        key, sep, rest = line.partition(':')
        if not sep or not key.strip():
            continue
        key = key.strip().lower()
        rest = rest.strip()
        if rest in ('>', '>-', '>+', '|', '|-', '|+'):
            block = []
            while index < len(lines) and (not lines[index].strip()
                                          or lines[index][:1].isspace()):
                block.append(lines[index].strip())
                index += 1
            if rest.startswith('>'):
                meta[key] = ' '.join(part for part in block if part)
            else:
                meta[key] = '\n'.join(block).strip()
        elif rest[:1] in ('"', "'"):
            quote = rest[0]
            if len(rest) >= 2 and rest.endswith(quote):
                meta[key] = rest[1:-1]
            else:
                meta[key] = rest[1:]
        else:
            meta[key] = rest
    return meta


def split_frontmatter(text):
    """Return (meta, body lines). Broken or absent frontmatter gives an empty meta."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {}, lines
    for index in range(1, len(lines)):
        if lines[index].strip() == '---':
            return parse_block(lines[1:index]), lines[index + 1:]
    return {}, lines


def first_body_line(body):
    for line in body:
        if line.strip():
            return line.strip()
    return ''


def make_item(kind, path, fallback_name, origin, source):
    """Build an item from a file. Never raises on broken frontmatter."""
    text = ''
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        pass
    meta, body = split_frontmatter(text)
    name = meta.get('name', '').strip() or fallback_name
    description = meta.get('description', '').strip() or first_body_line(body)
    hidden = meta.get('disable-model-invocation', '').strip().lower() == 'true'
    return Item(kind, name, description, hidden, origin, source, path)


def broken_links(root):
    if not root.is_dir():
        return []
    found = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for entry in list(dirnames) + list(filenames):
            path = Path(dirpath) / entry
            if path.is_symlink() and not path.exists():
                found.append(path)
    return found


def collect_user(paths, kind, source, problems):
    """User skills (a directory or symlink per skill) or user commands (recursive *.md)."""
    items = []
    for root in paths:
        for path in broken_links(root):
            problems.append(('dead-link', path.stem,
                             '%s -> %s' % (path, os.readlink(path))))
        if not root.is_dir():
            continue
        if kind == 'skill':
            for entry in sorted(root.iterdir()):
                skill = entry / 'SKILL.md'
                if not skill.is_file():
                    continue
                items.append(make_item(kind, skill, entry.name,
                                       '%s: %s' % (source, skill), source))
        else:
            for path in sorted(root.rglob('*.md')):
                if path.is_symlink() and not path.exists():
                    continue
                items.append(make_item(kind, path, path.stem,
                                       '%s: %s' % (source, path), source))
    return items


def load_plugins(home, problems):
    """Only enabled plugins, and only their installPath: never the cache directory."""
    installed_path = home / '.claude/plugins/installed_plugins.json'
    settings_path = home / '.claude/settings.json'
    try:
        installed = json.loads(installed_path.read_text()).get('plugins', {})
    except (OSError, ValueError):
        return []
    try:
        enabled = json.loads(settings_path.read_text()).get('enabledPlugins', {})
    except (OSError, ValueError):
        return []
    items = []
    if not isinstance(installed, dict) or not isinstance(enabled, dict):
        return items
    for key in sorted(installed):
        if enabled.get(key) is not True:
            continue
        records = installed.get(key)
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            install = record.get('installPath')
            if not isinstance(install, str) or not install:
                continue
            base = Path(install)
            for skill in sorted((base / 'skills').glob('*/SKILL.md')):
                if skill.is_file():
                    items.append(make_item('skill', skill, skill.parent.name,
                                           'plugin %s: %s' % (key, skill), PLUGINS))
            for command in sorted((base / 'commands').glob('*.md')):
                if command.is_file():
                    items.append(make_item('command', command, command.stem,
                                           'plugin %s: %s' % (key, command), PLUGINS))
    return items


def scan_retired(items, terms, allowed, problems):
    lowered = [(term, term.lower()) for term in terms]
    allowed = {entry.lower() for entry in allowed}
    for item in items:
        if item.source == PLUGINS or not lowered:
            continue
        for number, line in enumerate(read_lines(item.path), start=1):
            lowline = line.lower()
            for term, lowterm in lowered:
                if lowterm in lowline:
                    if ('retired-term:%s:%s' % (item.name, term)).lower() in allowed:
                        continue
                    problems.append(('retired-term', item.name,
                                     '%s at line %d' % (term, number)))


def collect(args, problems):
    home = Path(args.home).expanduser()
    items = []
    items += collect_user([home / '.claude/skills'] + args.extra_skills_dir,
                          'skill', USER_SKILLS, problems)
    items += collect_user([home / '.claude/commands'] + args.extra_commands_dir,
                          'command', USER_COMMANDS, problems)
    items += load_plugins(home, problems)
    return items


def duplicates(items, allowed, problems):
    groups = {}
    for item in items:
        if item.kind == 'skill':
            groups.setdefault(item.name, []).append(item)
    for name in sorted(groups):
        group = groups[name]
        if len(group) < 2 or not any(i.source == USER_SKILLS for i in group):
            continue
        if 'duplicate-name:%s' % name in allowed:
            continue
        problems.append(('duplicate-name', name,
                         '; '.join(sorted(i.origin for i in group))))


def totals(items, budget):
    visible = [i for i in items if not i.hidden]
    by_source = {source: 0 for source in SOURCES}
    for item in visible:
        by_source[item.source] = by_source.get(item.source, 0) + item.bytes
    top = sorted(visible, key=lambda i: (-i.bytes, i.name))[:10]
    return {
        'visible_bytes': sum(by_source.values()),
        'visible_items': len(visible),
        'hidden_items': len(items) - len(visible),
        'budget': budget,
        'by_source': by_source,
        'top': [{'name': i.name, 'source': i.source, 'bytes': i.bytes} for i in top],
    }


def finding_lines(findings):
    return ['%s: %s: %s' % (kind, subject, detail)
            for kind, subject, detail in sorted(findings)]


def digest_of(lines):
    return hashlib.sha256(('\n'.join(lines) + '\n').encode('utf-8')).hexdigest()


def parse_args(argv):
    parser = argparse.ArgumentParser(description='Check what a Claude Code session loads.')
    parser.add_argument('--home', default=os.environ.get('HOME', str(Path.home())))
    parser.add_argument('--extra-skills-dir', action='append', default=[],
                        type=Path)
    parser.add_argument('--extra-commands-dir', action='append', default=[],
                        type=Path)
    parser.add_argument('--budget', type=int, default=DEFAULT_BUDGET)
    parser.add_argument('--retired-file', type=Path,
                        default=HERE / 'skill-check-retired.txt')
    parser.add_argument('--allow-file', type=Path,
                        default=HERE / 'skill-check-allow.txt')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--host-label', default=socket.gethostname())
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    problems = []
    items = collect(args, problems)
    duplicates(items, read_entries(args.allow_file), problems)
    scan_retired(items, sorted(read_entries(args.retired_file)),
                 read_entries(args.allow_file), problems)
    summary = totals(items, args.budget)
    if summary['visible_bytes'] > args.budget:
        problems.append(('over-budget', 'visible descriptions',
                         'over the budget of %d bytes' % args.budget))

    lines = finding_lines(problems)
    report = {
        'host': args.host_label,
        'time': datetime.datetime.now(datetime.timezone.utc)
                        .strftime('%Y-%m-%dT%H:%M:%SZ'),
        'home': str(Path(args.home).expanduser()),
        'findings': [{'kind': kind, 'subject': subject, 'detail': detail}
                     for kind, subject, detail in sorted(problems)],
        'totals': summary,
        'digest': digest_of(lines),
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + '\n')
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for line in lines:
            print(line)
        print('skill-check %s: %d findings, %d visible description bytes '
              '(budget %d), %d visible, %d hidden'
              % (report['host'], len(problems), summary['visible_bytes'],
                 summary['budget'], summary['visible_items'],
                 summary['hidden_items']))
    return 1 if problems else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('skill-check: unexpected failure: %s'
              % ' '.join(str(error).split()), file=sys.stderr)
        sys.exit(2)
