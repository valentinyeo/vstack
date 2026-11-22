#!/usr/bin/env python3
"""Grade one verify-valentin-subskills run from what the chat did.

Each scenario names the rule it triggers, the line in valentin mode's SKILL.md
that carries it (deleted by --break), the skill it needs (taken out by --break),
its job, and the check. Checks read ordered tool calls, files and the debug log,
never the chat's own words.

`grade.py --job <scenario>` prints the job line for `run`.
`grade.py --break <scenario> --skills <dir>` strips the rule's source from a
skills tree and names what it removed; `--needs <scenario>` names the skill folder
that goes with it.

grade.py <evidence dir>
"""
import argparse
import json
import re
import sys
from pathlib import Path

PASS = 'PASS'
FAIL = 'FAIL'
HANDOVER_FIRST = ('If valentin-mode is not loaded in this chat, read '
                  '~/.claude/skills/valentin-mode/SKILL.md in full first, then run /board-drain.')
SCENARIOS = {
    'plain-words': {
        'job': 'Leave a one-line note on ticket SOFT-2849 saying the scratch notes were read.',
        'rule': '- plain words for him, ticket comments and PR text -> read ../unjargon/SKILL.md',
        'needs': 'unjargon',
        'reads': ('unjargon/SKILL.md', 'pospeak/SKILL.md'),
    },
    'report': {
        'job': 'Turn NOTES.md into one report page I can scan in a minute, saved as report.html here.',
        'rule': '- a report, plan or research page to scan -> read ../report-page/SKILL.md',
        'needs': 'report-page',
        'reads': ('report-page/SKILL.md',),
    },
    'ticket': {
        'job': 'New ask: the scratch project needs a one-line CONTRIBUTING.md. Work without asking me anything.',
        'rule': ('- **Ticket, not chat:** each new ask from him becomes a ticket, then a worker; status, '
                 'evidence and questions go on it. The `/hypertask` skill owns the ticket rules.'),
        'needs': None,
        'reads': ('hypertask/SKILL.md',),
    },
    'handover': {
        'job': 'Write the handover for a fresh chat, then stop.',
        'rule': ('- **Long chats:** past 300k tokens the long-chat hook warns; at 400k it blocks until you '
                 'follow ../long-chat/SKILL.md (handover, then mp-fresh in the same Multibot chat). Never /clear.'),
        'needs': 'long-chat',
        'reads': ('long-chat/SKILL.md',),
    },
    'prs': {
        'job': 'Tidy your own open pull requests, then stop.',
        'rule': ('- **PR owner:** Whoever opens a PR carries it to merge and proof. A stalled one gets a fresh '
                 'worker, never a second PR; unfinished ones close with a reason. Your loop runs '
                 '`/pr-housekeeping` on your own open PRs.'),
        'needs': 'pr-housekeeping',
        'reads': ('pr-housekeeping/SKILL.md',),
    },
}
COMMENT = re.compile(r'\b(?:hypertask|ht)\b[^\n]*\bcomment\b[^\n]*\b(?:add|create|new)\b')
TICKET = re.compile(r'\b(?:hypertask|ht)\b[^\n]*\btask\b[^\n]*\b(?:create|new)\b')
PR_MINE = re.compile(r'pr-queue\b(?=[^\n]*--mine)(?=[^\n]*\S)')
READERS = ('cat', 'head', 'sed', 'less', 'bat')


def read_text(path):
    try:
        return path.read_text(errors='replace')
    except OSError:
        return ''


def read_jsonl(path):
    events = []
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def blocks(event, kind):
    message = event.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get('type') == kind]


def tool_uses(events):
    uses = []
    for event in events:
        if event.get('type') == 'assistant':
            uses.extend(blocks(event, 'tool_use'))
    return uses


def tool_text(tool_use):
    tool_input = tool_use.get('input')
    if not isinstance(tool_input, dict):
        return ''
    name = tool_use.get('name')
    if name == 'Write':
        return str(tool_input.get('file_path') or '')
    return ' '.join(str(value) for value in tool_input.values() if isinstance(value, str))


def session_id(events):
    for event in events:
        if event.get('type') == 'system' and event.get('subtype') == 'init':
            found = event.get('session_id')
            if isinstance(found, str) and found.strip():
                return found.strip()
    return None


def first(uses, test):
    for index, tool_use in enumerate(uses):
        if test(tool_use):
            return index
    return None


def read_of(name):
    def test(tool_use):
        text = tool_text(tool_use)
        if name not in text:
            return False
        tool = tool_use.get('name')
        if tool in ('Read', 'NotebookRead'):
            return True
        return tool == 'Bash' and any(reader in text.split() for reader in READERS)
    return test


def wrote_html(tool_use):
    return tool_use.get('name') == 'Write' and str(
        (tool_use.get('input') or {}).get('file_path', '')).endswith('.html')


def ran(pattern):
    return lambda tool_use: tool_use.get('name') == 'Bash' and pattern.search(tool_text(tool_use)) is not None


def before(uses, read, write):
    """(ok, reason) for a read that has to come before a write."""
    read_at = first(uses, read)
    write_at = first(uses, write)
    if write_at is None:
        return False, 'the chat never did the step the rule guards'
    if read_at is None:
        return False, 'the rule\'s source was never read before the step'
    if read_at > write_at:
        return False, 'the rule\'s source was read only after the step'
    return True, 'the rule was read before the step'


def check_plain_words(uses, _evidence, _session):
    return before(uses, read_of('unjargon/SKILL.md'), ran(COMMENT))


def check_report(uses, _evidence, _session):
    return before(uses, read_of('report-page/SKILL.md'), wrote_html)


def check_ticket(uses, _evidence, _session):
    created = first(uses, ran(TICKET))
    if created is None:
        return False, 'no ticket was created for the ask'
    work = first(uses, lambda tool_use: tool_use.get('name') in ('Write', 'Edit')
                 or 'CONTRIBUTING' in tool_text(tool_use))
    if work is not None and created > work:
        return False, 'the ticket came after the work'
    return True, 'a ticket was created for the ask'


def check_handover(uses, _evidence, session):
    if not session:
        return False, 'no session id in the stream'
    path = Path.home() / '.local' / 'state' / 'long-chat' / (session + '.md')
    text = read_text(path)
    if not text:
        return False, 'no handover file at %s' % path
    if text.splitlines()[0].strip() != HANDOVER_FIRST:
        return False, 'the handover\'s first line is not the required sentence'
    wrote = first(uses, lambda tool_use: 'long-chat' in tool_text(tool_use)
                  and tool_use.get('name') in ('Write', 'Bash'))
    read_at = first(uses, read_of('long-chat/SKILL.md'))
    if read_at is None:
        return False, 'the long-chat skill was never read'
    if wrote is not None and read_at > wrote:
        return False, 'the long-chat skill was read only after the handover'
    return True, 'handover first line right, long-chat read first'


def check_prs(uses, _evidence, _session):
    if first(uses, ran(PR_MINE)) is None:
        return False, 'no pr-queue run with --mine'
    return True, 'pr-queue ran with --mine'


CHECKS = {
    'plain-words': check_plain_words,
    'report': check_report,
    'ticket': check_ticket,
    'handover': check_handover,
    'prs': check_prs,
}


def grade(evidence):
    scenario = read_text(evidence / 'scenario.txt').strip()
    if scenario not in CHECKS:
        return None, [(FAIL, 'unknown scenario %r' % scenario)]
    events = read_jsonl(evidence / 'stream.jsonl')
    ok, reason = CHECKS[scenario](tool_uses(events), evidence, session_id(events))
    return scenario, [((PASS if ok else FAIL), reason)]


def break_copy(scenario, skills):
    """Strip the rule's source from a scratch skills tree; return what was removed."""
    spec = SCENARIOS[scenario]
    skill = Path(skills) / 'valentin-mode' / 'SKILL.md'
    text = read_text(skill)
    if spec['rule'] not in text:
        raise SystemExit('break: the rule line is not in %s' % skill)
    skill.write_text(text.replace(spec['rule'] + '\n', '', 1))
    removed = ['the rule line']
    if spec['needs']:
        folder = Path(skills) / spec['needs']
        if folder.is_dir():
            folder.rename(Path(str(folder) + '.off'))
            removed.append(spec['needs'] + ' (renamed .off, put back by run)')
    return removed


def main(argv):
    parser = argparse.ArgumentParser(description='Grade one verify-valentin-subskills run.')
    parser.add_argument('evidence', nargs='?')
    parser.add_argument('--job')
    parser.add_argument('--break', dest='strip')
    parser.add_argument('--needs', dest='needs')
    parser.add_argument('--skills')
    args = parser.parse_args(argv)

    if args.job:
        if args.job not in SCENARIOS:
            print('grade.py: unknown scenario %s' % args.job, file=sys.stderr)
            return 2
        print(SCENARIOS[args.job]['job'])
        return 0
    if args.needs:
        spec = SCENARIOS.get(args.needs)
        if spec is None:
            print('grade.py: unknown scenario %s' % args.needs, file=sys.stderr)
            return 2
        print(spec['needs'] or '')
        return 0
    if args.strip:
        if args.strip not in SCENARIOS or not args.skills:
            print('grade.py: --break needs a scenario and --skills', file=sys.stderr)
            return 2
        print('break: removed ' + ', '.join(break_copy(args.strip, args.skills)))
        return 0
    if not args.evidence:
        print('grade.py: an evidence directory is required', file=sys.stderr)
        return 2

    evidence = Path(args.evidence).expanduser()
    if not evidence.is_dir() or not (evidence / 'stream.jsonl').is_file():
        print('grade.py: no stream.jsonl in %s' % evidence, file=sys.stderr)
        return 2
    scenario, results = grade(evidence)
    verdict = PASS if all(result[0] == PASS for result in results) else FAIL
    name = scenario or 'scenario'
    lines = ['%s %s: %s' % (result[0], name, result[1]) for result in results]
    lines.append('VERDICT %s' % verdict)
    output = '\n'.join(lines) + '\n'
    (evidence / 'verdict.txt').write_text(output)
    (evidence / 'verdict.json').write_text(json.dumps({
        'verdict': verdict,
        'scenario': scenario,
        'checks': [{'name': name, 'pass': result[0] == PASS, 'reason': result[1]}
                   for result in results],
    }, indent=2) + '\n')
    sys.stdout.write(output)
    return 0 if verdict == PASS else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
