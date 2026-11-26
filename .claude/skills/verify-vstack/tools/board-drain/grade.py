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
MARKER = 'full autopilot on this queue'
SAFETY_HOURS = 6
MIN_LOOP_HOURS = 2
MINUTES_A_DAY = 24 * 60
WEEK = timedelta(days=7)
WEEK_SLACK = timedelta(hours=1)

SEPARATORS = re.compile(r';|&&|\|\||\n')
QUOTES = re.compile(r'["\']')
WATCH_SCRIPT = re.compile(r'(?:skills/board-drain/watch|(?<![\w./-])\./watch)(?![\w-])')
ASSIGNMENT = re.compile(r'(?<![\w$])([A-Za-z_][A-Za-z0-9_]*)=([^\s;&|"\']+)')
SCRIPTS = frozenset({'loop-state', 'drain-check', 'reconcile'})
WRITES = (
    (re.compile(r'(?<![\w-])task\s+move(?![\w-])'), 'task move'),
    (re.compile(r'(?<![\w-])task\s+update(?![\w-])'), 'task update'),
    (re.compile(r'(?<![\w-])comment\s+add(?![\w-])'), 'comment add'),
    (re.compile(r'(?<![\w-])plan-pick[^\n;&|]*\s--run(?![\w-])'), 'plan-pick --run'),
)
JOB_ID = re.compile(r'Scheduled recurring job ([A-Za-z0-9_-]+)')


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


def prompt_ok(prompt, board):
    """The loop prompt names the queue and this chat's own view."""
    if not isinstance(prompt, str) or MARKER not in prompt.lower():
        return False
    return str(board) in prompt


def cron_creates(events):
    return [tool_use for tool_use in tool_uses(events)
            if tool_use.get('name') == 'CronCreate']


def unquoted(command):
    """The command without its quotes, so --label "two words" reads as a flag value."""
    return QUOTES.sub('', command)


def background_watch(events):
    """Every Bash call that starts the watcher: (tool_use, command without quotes)."""
    found = []
    for tool_use in tool_uses(events):
        if tool_use.get('name') != 'Bash':
            continue
        command = unquoted(command_of(tool_use))
        if WATCH_SCRIPT.search(command.strip()):
            found.append((tool_use, command))
    return found


def watch_on_view(watches, board, label):
    """True when one of these watcher calls is this chat's own view, in the background."""
    return any(tool_input(tool_use).get('run_in_background') is True
               and flag_value(command, 'board', board)
               and flag_value(command, 'label', label)
               for tool_use, command in watches)


def detached_on_view(watches, board, label):
    return any(bare_flag(command, 'detach')
               and flag_value(command, 'board', board)
               and flag_value(command, 'label', label)
               for _tool_use, command in watches)


def cron_firings(cron):
    """Every firing of a 5-field cron as minutes past midnight, or None when unreadable."""
    fields = cron.split() if isinstance(cron, str) else []
    if len(fields) != 5:
        return None
    try:
        hours = expand_field(fields[1], 0, 23)
        minutes = expand_field(fields[0], 0, 59)
    except (ValueError, TypeError):
        return None
    return sorted(hour * 60 + minute for hour in hours for minute in minutes)


def fires_within(firings, hours):
    """True when no gap between firings is longer than this many hours."""
    if not firings:
        return False
    gaps = [later - earlier for earlier, later in zip(firings, firings[1:])]
    gaps.append(firings[0] + MINUTES_A_DAY - firings[-1])
    return max(gaps) <= hours * 60


def fires_no_sooner_than(firings, hours):
    """True when every gap between firings is at least this many hours."""
    if not firings:
        return False
    gaps = [later - earlier for earlier, later in zip(firings, firings[1:])]
    gaps.append(firings[0] + MINUTES_A_DAY - firings[-1])
    return min(gaps) >= hours * 60


def cron_job_id(events, tool_use):
    """The job id CronCreate printed for this call, or None."""
    block = tool_results(events).get(tool_use.get('id'))
    if block is None:
        return None
    match = JOB_ID.search(result_text(block))
    return match.group(1) if match else None


def safety_cron(events):
    """(the safety cron, its job id, the reasons the other crons are no safety net)."""
    reasons = []
    for tool_use in cron_creates(events):
        fields = tool_input(tool_use)
        if fields.get('recurring') is False:
            reasons.append('a one-shot safety job instead of a recurring one')
            continue
        firings = cron_firings(fields.get('cron'))
        if firings is None or not fires_within(firings, SAFETY_HOURS):
            reasons.append('a safety job that does not fire within %d hours: %s'
                           % (SAFETY_HOURS, fields.get('cron')))
            continue
        return tool_use, cron_job_id(events, tool_use), reasons
    return None, None, reasons


def check_armed(events, board, label='vvm-test'):
    """PASS when the chat armed a loop over its own view, one of three ways.

    A detached `watch` on this chat's board and label (its own systemd unit), or a tracked
    background `watch` on them plus a safety cron at most every 6 hours, or a recurring
    cron on the plan pace (at least every 2 hours). A cron that fires more often than
    every 2 hours FAILS.
    Returns (result, cron job id or None).
    """
    reasons = []
    watches = background_watch(events)
    if detached_on_view(watches, board, label):
        return (PASS, 'a detached watcher on this view'), None
    if watch_on_view(watches, board, label):
        tool_use, job, safety_reasons = safety_cron(events)
        if tool_use is not None:
            return (PASS, 'a background watcher on this view, with a safety cron'), job
        reason = (safety_reasons or ['a watcher with no safety cron'])[0]
        return (FAIL, 'armed ' + reason), None
    if watches:
        backgrounded = any(tool_input(use).get('run_in_background') is True
                           for use, _command in watches)
        detached = any(bare_flag(command, 'detach') for _use, command in watches)
        reason = ('a detached watch for another view' if detached else
                  'a watch job for another view' if backgrounded
                  else 'a watch call that did not run in the background')
        return (FAIL, 'armed ' + reason), None
    for tool_use in cron_creates(events):
        fields = tool_input(tool_use)
        if fields.get('recurring') is False:
            reasons.append('a one-shot job instead of a recurring loop')
            continue
        firings = cron_firings(fields.get('cron'))
        if firings is None:
            reasons.append('a job with an unreadable cron: %s' % fields.get('cron'))
            continue
        if not fires_no_sooner_than(firings, MIN_LOOP_HOURS):
            reasons.append('a job that fires more often than every %d hours drains '
                           'the Claude plan: %s' % (MIN_LOOP_HOURS, fields.get('cron')))
            continue
        if not prompt_ok(fields.get('prompt'), board):
            reasons.append('a job whose prompt is not the board-drain loop prompt')
            continue
        return (PASS, 'CronCreate armed the loop on the plan pace'), cron_job_id(events, tool_use)
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


def grade(evidence, board, label='vvm-test'):
    events = read_jsonl(evidence / 'stream.jsonl')
    started_at = parse_time(read_text(evidence / 'started_at').strip())

    armed, job = check_armed(events, board, label)
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
    parser.add_argument('--label', default='vvm-test')
    args = parser.parse_args(argv)

    evidence = Path(args.evidence).expanduser()
    if not evidence.is_dir():
        print('grade.py: evidence directory not found: %s' % evidence, file=sys.stderr)
        return 2
    if not (evidence / 'stream.jsonl').is_file():
        print('grade.py: no stream.jsonl in %s' % evidence, file=sys.stderr)
        return 2

    session_id, checks = grade(evidence, args.board, args.label)
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
