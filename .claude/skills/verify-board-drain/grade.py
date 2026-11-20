#!/usr/bin/env python3
"""Grade one verify-board-drain run from its evidence directory.

Reads the evidence written by `run` and prints one PASS/FAIL line per check,
then VERDICT PASS or VERDICT FAIL. Exit 0 on PASS, 1 on FAIL, 2 on usage or
missing evidence. Never prints secrets: only the reason lines below.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PASS = 'PASS'
FAIL = 'FAIL'

SKILL_NAMES = ('board-drain', 'vstack:board-drain')
PROMPT_START = '/board-drain'
LOOP_SKILL = 'loop'
MARKER = 'full autopilot on this queue'
FIFTEEN = 15
WEEK = timedelta(days=7)
WEEK_SLACK = timedelta(hours=1)

SEPARATORS = re.compile(r';|&&|\|\||\n')
ASSIGNMENT = re.compile(r'(?<![\w$])([A-Za-z_][A-Za-z0-9_]*)=([^\s;&|"\']+)')
SCRIPTS = frozenset({'loop-state', 'drain-check', 'reconcile'})
WRITES = (
    (re.compile(r'(?<![\w-])task\s+move(?![\w-])'), 'task move'),
    (re.compile(r'(?<![\w-])task\s+update(?![\w-])'), 'task update'),
    (re.compile(r'(?<![\w-])comment\s+add(?![\w-])'), 'comment add'),
    (re.compile(r'(?<![\w-])plan-pick[^\n;&|]*\s--run(?![\w-])'), 'plan-pick --run'),
)
JOB_ID = re.compile(r'Scheduled recurring job ([A-Za-z0-9_-]+)')
FIFTEEN_MINUTES = re.compile(r'(?<![\w.])15\s*(?:m|min|mins|minute|minutes)(?![\w])')


def parse_time(value):
    """Return a timezone-aware datetime, or None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def read_text(path):
    try:
        return path.read_text(errors='replace')
    except OSError:
        return ''


def read_jsonl(path):
    """Parse JSON objects, skipping blank, non-JSON and non-object lines."""
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
        if event.get('type') != 'assistant':
            continue
        uses.extend(content_blocks(event, 'tool_use'))
    return uses


def tool_results(events):
    results = {}
    for event in events:
        if event.get('type') != 'user':
            continue
        for block in content_blocks(event, 'tool_result'):
            tool_use_id = block.get('tool_use_id')
            if isinstance(tool_use_id, str):
                results[tool_use_id] = block
    return results


def result_text(block):
    content = block.get('content')
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    parts = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get('text'), str):
            parts.append(item['text'])
        elif isinstance(item, str):
            parts.append(item)
    return '\n'.join(parts)


def tool_input(tool_use):
    tool_input = tool_use.get('input')
    return tool_input if isinstance(tool_input, dict) else {}


def command_of(tool_use):
    command = tool_input(tool_use).get('command')
    return command if isinstance(command, str) else ''


def bash_commands(events):
    return [command_of(tool_use) for tool_use in tool_uses(events)
            if tool_use.get('name') == 'Bash']


def flag_value(command, name, value):
    pattern = (r'(?<![\w-])--' + re.escape(name) + r'(?:=|\s+)'
               + re.escape(str(value)) + r'(?=\s|$)')
    return re.search(pattern, command) is not None


def bare_flag(command, name):
    return re.search(r'(?<![\w-])--' + re.escape(name) + r'(?=\s|$)', command) is not None


def resolve_path_variables(command):
    """Expand $NAME and ${NAME} where NAME=<path ending in one of SCRIPTS."""
    paths = {name: value for name, value in ASSIGNMENT.findall(command)
             if value.rsplit('/', 1)[-1] in SCRIPTS}
    for name, value in paths.items():
        command = re.sub(r'\$\{' + re.escape(name) + r'\}|\$' + re.escape(name) + r'(?!\w)',
                         value, command)
    return command


def shell_parts(command):
    """Split one Bash command into the calls a shell would run in order."""
    command = resolve_path_variables(command)
    return [part.strip() for part in SEPARATORS.split(command) if part.strip()]


def skill_name(tool_use):
    if tool_use.get('name') != 'Skill':
        return None
    skill = tool_input(tool_use).get('skill')
    return skill if isinstance(skill, str) else None


def find_session(events):
    for event in events:
        if event.get('type') != 'system' or event.get('subtype') != 'init':
            continue
        session_id = event.get('session_id')
        if isinstance(session_id, str) and session_id.strip():
            return session_id.strip()
    return None


def check_loaded(evidence, events):
    """PASS when the chat loaded board-drain, by the slash command or the Skill tool."""
    for tool_use in tool_uses(events):
        skill = skill_name(tool_use)
        if skill is not None and (skill in SKILL_NAMES or skill.endswith(':board-drain')):
            return PASS, 'board-drain loaded by the Skill tool'
    prompt = read_text(evidence / 'prompt.txt').strip()
    if prompt.startswith(PROMPT_START):
        return PASS, 'the chat was started with /board-drain'
    return FAIL, 'board-drain not loaded: no Skill call and no /board-drain prompt'


def check_status_read(events):
    """PASS when a Bash call asks loop-state for this chat's status."""
    for command in bash_commands(events):
        for invocation in shell_parts(command):
            if 'loop-state' not in invocation:
                continue
            if re.search(r'(?<![\w-])status(?![\w-])', invocation) and bare_flag(invocation, 'name'):
                return PASS, 'the chat read its loop status'
    return FAIL, 'the chat never ran loop-state status --name'


def expand_field(field, low, high):
    """Expand one cron field into its set of values."""
    values = set()
    for part in field.split(','):
        step = 1
        if '/' in part:
            part, step_text = part.split('/', 1)
            step = int(step_text)
        if step < 1:
            raise ValueError('cron step below 1')
        if part == '*':
            start, end = low, high
        elif '-' in part:
            start_text, end_text = part.split('-', 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(part)
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError('empty cron field')
    return values


def spaced_every_fifteen(minutes):
    """True for four firings an hour, 15 minutes apart, wherever they start.

    Claude Code's /loop offsets its cron to avoid the top of the hour, so
    7,22,37,52 is a 15-minute loop just as 0,15,30,45 is.
    """
    if len(minutes) != 4:
        return False
    ordered = sorted(minutes)
    gaps = [later - earlier for earlier, later in zip(ordered, ordered[1:])]
    gaps.append(ordered[0] + 60 - ordered[-1])
    return all(gap == FIFTEEN for gap in gaps)


def every_fifteen_minutes(cron):
    """True when a 5-field cron fires every 15 minutes of every hour."""
    if not isinstance(cron, str):
        return False
    fields = cron.split()
    if len(fields) != 5:
        return False
    try:
        minutes = expand_field(fields[0], 0, 59)
        hours = expand_field(fields[1], 0, 23)
    except (ValueError, TypeError):
        return False
    return spaced_every_fifteen(minutes) and hours == set(range(24))


def prompt_ok(prompt, board):
    """The loop prompt names the queue and this chat's own view."""
    if not isinstance(prompt, str) or MARKER not in prompt.lower():
        return False
    return str(board) in prompt


def loop_skill_prompt(tool_use, board):
    """A Skill call to loop carries the interval and the prompt in its input."""
    text = ' '.join(value for value in tool_input(tool_use).values() if isinstance(value, str))
    if not FIFTEEN_MINUTES.search(text):
        return False
    return prompt_ok(text, board)


def cron_creates(events):
    return [tool_use for tool_use in tool_uses(events)
            if tool_use.get('name') == 'CronCreate']


def cron_job_id(events, tool_use):
    """The job id CronCreate printed for this call, or None."""
    block = tool_results(events).get(tool_use.get('id'))
    if block is None:
        return None
    match = JOB_ID.search(result_text(block))
    return match.group(1) if match else None


def check_armed(events, board):
    """PASS when the chat armed a 15-minute loop over its own view.

    Returns (result, cron job id or None).
    """
    reasons = []
    for tool_use in cron_creates(events):
        fields = tool_input(tool_use)
        if fields.get('recurring') is False:
            reasons.append('a one-shot job instead of a recurring loop')
            continue
        if not every_fifteen_minutes(fields.get('cron')):
            reasons.append('a job that does not fire every 15 minutes: %s' % fields.get('cron'))
            continue
        if not prompt_ok(fields.get('prompt'), board):
            reasons.append('a job whose prompt is not the board-drain loop prompt')
            continue
        return (PASS, 'CronCreate armed the loop every 15 minutes'), cron_job_id(events, tool_use)
    for tool_use in tool_uses(events):
        skill = skill_name(tool_use)
        if skill is None or skill not in (LOOP_SKILL, 'vstack:' + LOOP_SKILL):
            continue
        if not loop_skill_prompt(tool_use, board):
            reasons.append('a /loop call without 15m and the board-drain loop prompt')
            continue
        return (PASS, '/loop armed the loop every 15 minutes'), None
    if reasons:
        return (FAIL, 'armed ' + reasons[0]), None
    return (FAIL, 'the chat never armed a loop'), None


def check_recorded(evidence, started_at, job):
    """PASS when the state file records a fresh 7-day arm, with the cron job id."""
    state = read_json(evidence / 'state.json', {})
    armed_at = parse_time(state.get('armed_at'))
    expires_at = parse_time(state.get('expires_at'))
    if armed_at is None or expires_at is None:
        return FAIL, 'loop-state arm never wrote the state file'
    if started_at is not None and armed_at < started_at:
        return FAIL, 'the state file was not armed in this run'
    if not WEEK - WEEK_SLACK <= expires_at - armed_at <= WEEK + WEEK_SLACK:
        return FAIL, 'expires_at is not about 7 days after armed_at'
    if job is not None and state.get('job') != job:
        return FAIL, 'the state file holds job %s, not the arming job %s' % (
            state.get('job') or 'none', job)
    return PASS, 'armed in this run, expires in about 7 days%s' % (
        ', job %s recorded' % job if job else '')


def check_synced(evidence, started_at):
    """PASS when the sync recorded a fresh success, so drain-check can pass."""
    state = read_json(evidence / 'state.json', {})
    record = state.get('last_sync')
    if not isinstance(record, dict):
        return FAIL, 'the chat never ran ./sync'
    if record.get('ok') is not True:
        return FAIL, 'the last sync failed: %s' % (record.get('reason') or 'no reason recorded')
    at = parse_time(record.get('at'))
    if at is None:
        return FAIL, 'the last sync has no time'
    if started_at is not None and at < started_at:
        return FAIL, 'the recorded sync is older than this run'
    return PASS, 'sync recorded ok at %s' % record.get('at')


def check_checked(events):
    """PASS when a Bash call ran drain-check on this chat's state."""
    for command in bash_commands(events):
        for invocation in shell_parts(command):
            if 'drain-check' in invocation and bare_flag(invocation, 'state-name'):
                return PASS, 'the chat ran drain-check --state-name'
    return FAIL, 'the chat never ran drain-check --state-name'


def check_no_writes(events):
    """PASS when the chat moved no ticket and started no code worker."""
    for command in bash_commands(events):
        for pattern, label in WRITES:
            if pattern.search(command):
                return FAIL, 'the chat ran %s' % label
    return PASS, 'no ticket moves, no comments, no plan-pick workers'


def grade(evidence, board):
    events = read_jsonl(evidence / 'stream.jsonl')
    started_at = parse_time(read_text(evidence / 'started_at').strip())

    armed, job = check_armed(events, board)
    checks = [
        ('loaded', check_loaded(evidence, events)),
        ('status-read', check_status_read(events)),
        ('armed', armed),
        ('recorded', check_recorded(evidence, started_at, job)),
        ('synced', check_synced(evidence, started_at)),
        ('checked', check_checked(events)),
        ('no-writes', check_no_writes(events)),
    ]
    return find_session(events), checks


def main(argv):
    parser = argparse.ArgumentParser(description='Grade a verify-board-drain run.')
    parser.add_argument('evidence', help='evidence directory written by run')
    parser.add_argument('--board', default='2060')
    args = parser.parse_args(argv)

    evidence = Path(args.evidence).expanduser()
    if not evidence.is_dir():
        print('grade.py: evidence directory not found: %s' % evidence, file=sys.stderr)
        return 2
    if not (evidence / 'stream.jsonl').is_file():
        print('grade.py: no stream.jsonl in %s' % evidence, file=sys.stderr)
        return 2

    session_id, checks = grade(evidence, args.board)
    verdict = PASS if all(result[0] == PASS for _name, result in checks) else FAIL

    lines = ['%s %s: %s' % (result[0], name, result[1]) for name, result in checks]
    lines.append('VERDICT %s' % verdict)
    output = '\n'.join(lines) + '\n'

    (evidence / 'verdict.txt').write_text(output)
    payload = {
        'verdict': verdict,
        'session_id': session_id,
        'checks': [
            {'name': name, 'pass': result[0] == PASS, 'reason': result[1]}
            for name, result in checks
        ],
    }
    (evidence / 'verdict.json').write_text(json.dumps(payload, indent=2) + '\n')

    sys.stdout.write(output)
    return 0 if verdict == PASS else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
