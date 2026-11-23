#!/usr/bin/env python3
"""Grade one verify-hypertask run from its evidence directory.

Prints one PASS/FAIL line per check, then VERDICT PASS or VERDICT FAIL.
Exit 0 on PASS, 1 on FAIL, 2 on usage or missing evidence. Never prints secrets.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PASS = 'PASS'
FAIL = 'FAIL'
BOARD_LINE = re.compile(r'^Hypertask board:\s*(\d+)(?:\s*,\s*label:\s*(.+?))?\s*$')


def parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


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


def read_json(path, default):
    try:
        data = json.loads(read_text(path))
    except ValueError:
        return default
    return data if isinstance(data, dict) else default


def content_blocks(event, kind):
    message = event.get('message')
    if not isinstance(message, dict):
        return []
    content = message.get('content')
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict) and block.get('type') == kind]


def tool_uses(events):
    uses = []
    for event in events:
        if event.get('type') == 'assistant':
            uses.extend(content_blocks(event, 'tool_use'))
    return uses


def tool_results(events):
    results = {}
    for event in events:
        if event.get('type') != 'user':
            continue
        for block in content_blocks(event, 'tool_result'):
            if isinstance(block.get('tool_use_id'), str):
                results[block['tool_use_id']] = block
    return results


def result_text(block):
    content = block.get('content')
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    return '\n'.join(item.get('text', '') for item in content if isinstance(item, dict))


def command_of(tool_use):
    tool_input = tool_use.get('input')
    if not isinstance(tool_input, dict):
        return ''
    command = tool_input.get('command')
    return command if isinstance(command, str) else ''


def flag_value(command, name, value):
    pattern = (r'(?<![\w-])--' + re.escape(name) + r'(?:=|\s+)'
               + re.escape(str(value)) + r'(?=\s|$)')
    return re.search(pattern, command) is not None


def bare_flag(command, name):
    return re.search(r'(?<![\w-])--' + re.escape(name) + r'(?=\s|$)', command) is not None


def find_session(events):
    for event in events:
        if event.get('type') == 'system' and event.get('subtype') == 'init':
            session_id = event.get('session_id')
            if isinstance(session_id, str) and session_id.strip():
                return session_id.strip()
    return None


def check_read(events):
    """PASS when the chat reads or loads the hypertask skill."""
    for tool_use in tool_uses(events):
        name = tool_use.get('name')
        tool_input = tool_use.get('input')
        if not isinstance(tool_input, dict):
            continue
        if name == 'Skill':
            skill = tool_input.get('skill')
            if isinstance(skill, str) and (skill in ('hypertask', 'vstack:hypertask')
                                           or skill.endswith(':hypertask')):
                return PASS, 'the skill was loaded by the Skill tool'
        if name == 'Read':
            path = tool_input.get('file_path') or tool_input.get('path') or ''
            if isinstance(path, str) and path.endswith('skills/hypertask/SKILL.md'):
                return PASS, 'the chat read skills/hypertask/SKILL.md'
    return FAIL, 'the chat never read skills/hypertask/SKILL.md'


def recent(created, started_at):
    stamp = parse_time(created)
    return started_at is None or stamp is None or stamp >= started_at


def comment_author(comment):
    for field in ('agent', 'creator'):
        holder = comment.get(field)
        if isinstance(holder, dict) and isinstance(holder.get('displayName'), str):
            return holder['displayName'].strip()
    return None


def board_writes(evidence, started_at):
    writes = []
    for activity in read_json(evidence / 'agent-log.json', {}).get('activities') or ():
        if isinstance(activity, dict) and recent(activity.get('createdAt'), started_at):
            name = activity.get('agentName')
            writes.append(name if isinstance(name, str) else None)
    for comment in read_json(evidence / 'comments.json', {}).get('comments') or ():
        if isinstance(comment, dict) and recent(comment.get('createdAt'), started_at):
            writes.append(comment_author(comment))
    return writes


def check_login(evidence, started_at, agent):
    writes = board_writes(evidence, started_at)
    if not writes:
        return FAIL, 'no board write by the test chat'
    for author in writes:
        if author != agent:
            return FAIL, 'board write by %s instead of %s' % (author or 'nobody', agent)
    return PASS, 'board write by %s' % agent


def shell_calls(events):
    for tool_use in tool_uses(events):
        if tool_use.get('name') == 'Bash':
            yield tool_use, command_of(tool_use)


def check_view(events, board, label):
    """PASS when the chat created or found its own view with the label."""
    results = tool_results(events)
    for tool_use, command in shell_calls(events):
        if 'view create' in command and flag_value(command, 'project', board) \
                and flag_value(command, 'label', label):
            result = results.get(tool_use.get('id') or '')
            if result is not None and result.get('is_error') is False:
                return PASS, 'view created with label %s' % label
    for tool_use, command in shell_calls(events):
        if 'view list' not in command or not flag_value(command, 'project', board):
            continue
        result = results.get(tool_use.get('id') or '')
        if result is not None and label.lower() in result_text(result).lower():
            return PASS, 'view list shows label %s' % label
    return FAIL, 'no view created or found with label %s' % label


def check_board_line(evidence, board, label):
    """PASS when the scratch repo has the board line, with the label or without."""
    for line in read_text(evidence / 'notes.md').splitlines():
        found = BOARD_LINE.match(line.strip())
        if not found:
            continue
        if int(found[1]) != int(board):
            return FAIL, 'board line names board %s instead of %s' % (found[1], board)
        if found[2] and found[2].strip().lower() != label.lower():
            return FAIL, 'board line names label %s instead of %s' % (found[2].strip(), label)
        return PASS, 'notes carry Hypertask board: %s' % board
    return FAIL, 'no Hypertask board: %s line in the project notes' % board


def check_ticket(evidence, started_at, board, label):
    """PASS when exactly one ticket was filed in the label after the run started."""
    tasks = read_json(evidence / 'tasks.json', {}).get('tasks') or []
    filed = []
    for task in tasks:
        if not isinstance(task, dict) or not recent(task.get('createdAt'), started_at):
            continue
        labels = {str(row.get('name') or '').strip().lower()
                  for row in task.get('labels') or () if isinstance(row, dict)}
        if label.lower() in labels and str(task.get('projectId')) == str(board):
            filed.append(task.get('ticketNumber') or 'unknown')
    if not filed:
        return FAIL, 'no ticket filed in label %s' % label
    if len(filed) > 1:
        return FAIL, 'more than one ticket filed: %s' % ', '.join(map(str, filed))
    return PASS, 'one ticket filed: %s' % filed[0]


SYNC_SEPARATORS = re.compile(r';|&&|\|\||\n')
ASSIGNMENT = re.compile(r'(?<![\w$])([A-Za-z_][A-Za-z0-9_]*)=([^\s;&|"\']+)')


def sync_invocations(command):
    """Split one Bash command into the calls a shell would run in order."""
    paths = {name: value for name, value in ASSIGNMENT.findall(command)
             if value.rsplit('/', 1)[-1] == 'reconcile'}
    for name, value in paths.items():
        command = re.sub(r'\$\{' + re.escape(name) + r'\}|\$' + re.escape(name) + r'(?!\w)',
                         value, command)
    return [part.strip() for part in SYNC_SEPARATORS.split(command) if part.strip()]


def classify_sync(command, board, label):
    if 'reconcile' not in command:
        return None
    if not flag_value(command, 'board', board) or not flag_value(command, 'label', label):
        return None
    if not bare_flag(command, 'apply'):
        return 'dry'
    return 'apply' if flag_value(command, 'limit', 5) else None


def check_sync(events, board, label):
    syncs = []
    for call, tool_use in enumerate(tool_uses(events)):
        if tool_use.get('name') != 'Bash':
            continue
        command = command_of(tool_use)
        tool_use_id = tool_use.get('id') if isinstance(tool_use.get('id'), str) else ''
        for index, invocation in enumerate(sync_invocations(command)):
            if ('reconcile' in invocation and bare_flag(invocation, 'apply')
                    and not flag_value(invocation, 'label', label)):
                return FAIL, 'sync apply without --label %s can move real tickets' % label
            kind = classify_sync(invocation, board, label)
            if kind:
                syncs.append(((call, index), kind, tool_use_id))
    dry = [entry for entry in syncs if entry[1] == 'dry']
    apply = [entry for entry in syncs if entry[1] == 'apply']
    if not dry:
        return FAIL, 'no board sync dry run'
    if not apply:
        return FAIL, 'no board sync apply with --limit 5'
    ordered = [entry for entry in apply if any(d[0] < entry[0] for d in dry)]
    if not ordered:
        return FAIL, 'apply ran before the dry run'
    result = tool_results(events).get(ordered[0][2])
    if result is None:
        return FAIL, 'board sync apply failed: no tool result'
    text = result_text(result)
    if result.get('is_error') is not False or re.search(r'(?m)^\s*(?:[\w .-]+:\s*)?error:', text):
        detail = ' '.join(text.split())[:120] or 'is_error true'
        return FAIL, 'board sync apply failed: %s' % detail
    return PASS, 'dry run then apply, apply clean'


def grade(evidence, agent, board, label):
    events = read_jsonl(evidence / 'stream.jsonl')
    started_at = parse_time(read_text(evidence / 'started_at'))
    session_id = find_session(events)
    checks = [('read', check_read(events)),
              ('login', check_login(evidence, started_at, agent)),
              ('view', check_view(events, board, label)),
              ('board line', check_board_line(evidence, board, label)),
              ('ticket', check_ticket(evidence, started_at, board, label)),
              ('sync', check_sync(events, board, label))]
    return session_id, checks


def main(argv):
    parser = argparse.ArgumentParser(description='Grade a verify-hypertask run.')
    parser.add_argument('evidence', help='evidence directory written by run')
    parser.add_argument('--agent', default='VVM Test Agent')
    parser.add_argument('--board', default='2060')
    parser.add_argument('--label', default='vvm-test')
    args = parser.parse_args(argv)

    evidence = Path(args.evidence).expanduser()
    if not evidence.is_dir():
        print('grade.py: evidence directory not found: %s' % evidence, file=sys.stderr)
        return 2
    if not (evidence / 'stream.jsonl').is_file():
        print('grade.py: no stream.jsonl in %s' % evidence, file=sys.stderr)
        return 2

    session_id, checks = grade(evidence, args.agent, args.board, args.label)
    verdict = PASS if all(result[0] == PASS for _name, result in checks) else FAIL
    lines = ['%s %s: %s' % (result[0], name, result[1]) for name, result in checks]
    lines.append('VERDICT %s' % verdict)
    output = '\n'.join(lines) + '\n'
    (evidence / 'verdict.txt').write_text(output)
    (evidence / 'verdict.json').write_text(json.dumps({
        'verdict': verdict,
        'session_id': session_id,
        'checks': [{'name': name, 'pass': result[0] == PASS, 'reason': result[1]}
                   for name, result in checks]}, indent=2) + '\n')
    sys.stdout.write(output)
    return 0 if verdict == PASS else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
