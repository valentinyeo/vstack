#!/usr/bin/env python3
"""Grade one verify-valentin-mode run from its evidence directory.

Reads the evidence written by `run` and prints one PASS/FAIL line per check,
then VERDICT PASS or VERDICT FAIL. Exit 0 on PASS, 1 on FAIL, 2 on usage or
missing evidence. Never prints secrets: only the reason lines below.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PASS = 'PASS'
FAIL = 'FAIL'
SKILL_NAMES = ('valentin-mode', 'vstack:valentin-mode')
SKILL_BODY_MARKER = '## Three tools'
COMMAND = 'valentin-mode'
PROMPT_START = '/' + COMMAND
RESPONSIVE = 'responsive-mode'
RESPONSIVE_PROMPT = re.compile(r'\s*/' + re.escape(RESPONSIVE) + r'(?=\s|$)')
INSTALLED_NAME = 'installed-valentin-mode.md'
DISABLE_LINE = 'disable-model-invocation: true'
NO_SESSION = 'no session id in stream'
TASK_LINE = 'hello from the worker'
HOOK_FILE = re.compile(r'[^\s"\'`]+\.[a-z]{2}\b')
# A debug log line per hook run: "Hooks: <Event>[:<matcher>] [<command>] finished".
DEBUG_HOOK = re.compile(r'Hooks: ([A-Za-z]+)(?::\S*)?\s+\[([^\]]*)\]')
# valentin-mode pastes responsive mode's body in at load: these three mark it whole.
RESPONSIVE_PASTE_HEADING = '## Responsive mode (pasted in when this skill loads)'
RESPONSIVE_PASTE_FIRST = 'The main chat talks. Background agents work.'
RESPONSIVE_PASTE_LAST = 'the push lands on the remote with no nudge.'


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
        if event.get('type') != 'system' or event.get('subtype') != 'init':
            continue
        session_id = event.get('session_id')
        if isinstance(session_id, str) and session_id.strip():
            return session_id.strip()
    return None


def skill_invoked(tool_use):
    if tool_use.get('name') != 'Skill':
        return False
    tool_input = tool_use.get('input')
    skill = tool_input.get('skill') if isinstance(tool_input, dict) else None
    if not isinstance(skill, str):
        return False
    return skill in SKILL_NAMES or skill.endswith(':valentin-mode')


def responsive_invoked(tool_use):
    """True when the chat loads responsive mode through the Skill tool."""
    if tool_use.get('name') != 'Skill':
        return False
    tool_input = tool_use.get('input')
    skill = tool_input.get('skill') if isinstance(tool_input, dict) else None
    if not isinstance(skill, str):
        return False
    return skill == RESPONSIVE or skill.endswith(':' + RESPONSIVE)


def responsive_prompt(events):
    """True when a user prompt starts with the /responsive-mode command."""
    for event in events:
        if event.get('type') != 'user':
            continue
        for block in content_blocks(event, 'text'):
            text = block.get('text')
            if isinstance(text, str) and RESPONSIVE_PROMPT.match(text):
                return True
    return False


def command_installed(events):
    """True when an init event lists valentin-mode among the slash commands."""
    for event in events:
        if event.get('type') != 'system' or event.get('subtype') != 'init':
            continue
        commands = event.get('slash_commands')
        if isinstance(commands, list) and COMMAND in commands:
            return True
    return False


def frontmatter_lines(text):
    """Return the lines inside the leading --- block, else an empty list."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return []
    for index in range(1, len(lines)):
        if lines[index].strip() == '---':
            return lines[1:index]
    return []


def hook_files(command):
    """The script names a hook command line runs."""
    return [token.rsplit('/', 1)[-1] for token in HOOK_FILE.findall(command)]


def hook_commands(text):
    """(event, file name) for every hook the skill's frontmatter turns on."""
    block = []
    inside = False
    for line in frontmatter_lines(text):
        if not inside:
            inside = line.rstrip() == 'hooks:'
            continue
        if line.strip() and not line[:1].isspace():
            break
        block.append(line)
    found, event = [], ''
    for line in block:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped.endswith(':') and not stripped.startswith('-') and indent <= 2:
            event = stripped[:-1]
        elif stripped.startswith('command:'):
            for name in hook_files(stripped):
                found.append((event, name))
    return found


def installed_hook_files(command):
    """Hook file names a command runs out of a .claude/skills/ folder."""
    return [token.rsplit('/', 1)[-1] for token in HOOK_FILE.findall(command)
            if '.claude/skills/' in token]


def hook_runs(evidence):
    """(event, file name) for every hook the chat's debug log recorded running."""
    runs = []
    for line in read_text(evidence / 'debug.log').splitlines():
        match = DEBUG_HOOK.search(line)
        if not match:
            continue
        event, command = match.group(1), match.group(2)
        runs.extend((event, name) for name in installed_hook_files(command))
    return runs


def check_checks_loaded(evidence):
    """The skill's own hooks loaded with it (mirrors verify-responsive-mode/grade.py)."""
    text = read_text(evidence / INSTALLED_NAME)
    if not text:
        return PASS, 'no skill text in evidence, so no hooks block to check'
    wanted = hook_commands(text)
    if not wanted:
        return PASS, 'the skill under test turns no hooks on'
    if not (evidence / 'debug.log').is_file():
        return FAIL, ('no debug.log: the skill turns hooks on, but nothing shows they ran')
    ran = hook_runs(evidence)
    missing = [f'{name} ({event})' for event, name in wanted
               if (event, name) not in ran]
    if missing:
        return FAIL, ('debug.log shows no run of ' + ', '.join(missing)
                      + ' from the scratch project\'s .claude/skills/ folder')
    return PASS, 'debug.log shows every declared hook ran: ' + ', '.join(
        f'{name} ({event})' for event, name in wanted)


def check_loaded(evidence):
    """PASS when the chat was started with /valentin-mode and cannot start it alone."""
    events = read_jsonl(evidence / 'stream.jsonl')
    if any(skill_invoked(tool_use) for tool_use in tool_uses(events)):
        return FAIL, 'the chat started valentin mode by itself'
    prompt = read_text(evidence / 'prompt.txt').strip()
    if not prompt.startswith(PROMPT_START):
        return FAIL, 'the chat was not told /valentin-mode'
    if not command_installed(events):
        return FAIL, 'valentin-mode is not installed as a command'
    installed = read_text(evidence / INSTALLED_NAME)
    if SKILL_BODY_MARKER not in installed:
        return FAIL, 'installed valentin-mode lacks the Three tools section'
    frontmatter = [line.strip() for line in frontmatter_lines(installed)]
    if DISABLE_LINE not in frontmatter:
        return FAIL, 'installed valentin-mode can still start by itself'
    return PASS, ('the chat was started with /valentin-mode '
                  '(three tools version, no self-start)')


def pasted_responsive(text):
    """True when this text holds responsive mode's body, start to last sentence.

    The skill runs a shell line at load, so the body shows up only once that line
    ran: the unexpanded line is text too, and it carries the heading without the
    rules. A paste cut off part way loses the end-of-turn rule, so the last
    sentence of the body is what proves the whole thing arrived.
    """
    return (RESPONSIVE_PASTE_HEADING in text
            and RESPONSIVE_PASTE_FIRST in text
            and RESPONSIVE_PASTE_LAST in text)


def responsive_pasted(events):
    """True when the loaded skill pasted responsive mode's body into the chat."""
    for event in events:
        if event.get('type') != 'user':
            continue
        for block in content_blocks(event, 'text'):
            text = block.get('text')
            if isinstance(text, str) and pasted_responsive(text):
                return True
    return False


def check_responsive(events):
    """PASS when the chat loads responsive mode, alone or as valentin mode's first step."""
    if any(responsive_invoked(tool_use) for tool_use in tool_uses(events)):
        return PASS, 'responsive mode loaded by the Skill tool'
    if responsive_prompt(events):
        return PASS, 'responsive mode started by /responsive-mode'
    if responsive_pasted(events):
        return PASS, 'responsive mode pasted in by /valentin-mode'
    return FAIL, 'responsive mode not loaded'


def board_writes(evidence, started_at):
    """Return (createdAt, author) for each board write at or after started_at."""
    writes = []
    activities = read_json(evidence / 'agent-log.json', {}).get('activities')
    if isinstance(activities, list):
        for activity in activities:
            if not isinstance(activity, dict):
                continue
            created = activity.get('createdAt')
            if not recent_enough(created, started_at):
                continue
            author = activity.get('agentName')
            writes.append((created, author if isinstance(author, str) else None))
    comments = read_json(evidence / 'comments.json', {}).get('comments')
    if isinstance(comments, list):
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            created = comment.get('createdAt')
            if not recent_enough(created, started_at):
                continue
            writes.append((created, comment_author(comment)))
    return writes


def comment_author(comment):
    agent = comment.get('agent')
    if isinstance(agent, dict):
        name = agent.get('displayName')
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None
    creator = comment.get('creator')
    if isinstance(creator, dict):
        name = creator.get('displayName')
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def recent_enough(created, started_at):
    if started_at is None:
        return True
    created_at = parse_time(created)
    if created_at is None:
        return True
    return created_at >= started_at


def check_login(evidence, started_at, agent):
    writes = board_writes(evidence, started_at)
    if not writes:
        return FAIL, 'no board write by the test chat'
    for _created, author in writes:
        if author != agent:
            return FAIL, 'board write by %s instead of %s' % (author or 'nobody', agent)
    return PASS, 'board write by %s' % agent


def check_pacer(evidence, session_id, events):
    launches = read_jsonl(evidence / 'launches.jsonl')
    mine = [line for line in launches if line.get('session') == session_id]
    for tool_use in tool_uses(events):
        name = tool_use.get('name')
        if name not in ('Agent', 'Task'):
            continue
        tool_input = tool_use.get('input')
        subagent = tool_input.get('subagent_type') if isinstance(tool_input, dict) else None
        if subagent != 'Explore':
            return FAIL, 'code worker ran on Claude via the %s tool' % name
    if not mine:
        return FAIL, 'the chat never started a worker through plan-pick --run'
    if all(line.get('lane') is None for line in mine):
        return PASS, 'plan-pick ran, no lane left'
    return PASS, 'plan-pick started a worker'


SYNC_SEPARATORS = re.compile(r';|&&|\|\||\n')
ASSIGNMENT = re.compile(r'(?<![\w$])([A-Za-z_][A-Za-z0-9_]*)=([^\s;&|"\']+)')


def resolve_path_variables(command):
    """Expand $NAME and ${NAME} where NAME=<path ending in reconcile> in this command."""
    paths = {name: value for name, value in ASSIGNMENT.findall(command)
             if value.rsplit('/', 1)[-1] == 'reconcile'}
    for name, value in paths.items():
        command = re.sub(r'\$\{' + re.escape(name) + r'\}|\$' + re.escape(name) + r'(?!\w)',
                         value, command)
    return command


def sync_invocations(command):
    """Split one Bash command into the calls a shell would run in order."""
    command = resolve_path_variables(command)
    return [part.strip() for part in SYNC_SEPARATORS.split(command) if part.strip()]


def classify_sync(command, board, label):
    if 'reconcile' not in command:
        return None
    if not flag_value(command, 'board', board):
        return None
    if not flag_value(command, 'label', label):
        return None
    if not bare_flag(command, 'apply'):
        return 'dry'
    if flag_value(command, 'limit', 5):
        return 'apply'
    return None


def check_board_sync(events, board, label):
    """Grade the sync calls in stream order, one call per reconcile invocation."""
    syncs = []
    for call, tool_use in enumerate(tool_uses(events)):
        if tool_use.get('name') != 'Bash':
            continue
        command = command_of(tool_use)
        tool_use_id = tool_use.get('id')
        tool_use_id = tool_use_id if isinstance(tool_use_id, str) else ''
        for index, invocation in enumerate(sync_invocations(command)):
            if ('reconcile' in invocation and bare_flag(invocation, 'apply')
                    and not flag_value(invocation, 'label', label)):
                return FAIL, 'board sync apply without --label <label> can move real tickets'
            kind = classify_sync(invocation, board, label)
            if kind is None:
                continue
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
    _position, _kind, tool_use_id = ordered[0]
    result = tool_results(events).get(tool_use_id)
    if result is None:
        return FAIL, 'board sync apply failed: no tool result'
    text = result_text(result)
    error_at_line_start = re.search(r'(?m)^\s*(?:[\w .-]+:\s*)?error:', text) is not None
    if result.get('is_error') is not False or error_at_line_start:
        detail = ' '.join(text.split())[:120] or 'is_error true'
        return FAIL, 'board sync apply failed: %s' % detail
    return PASS, 'dry run then apply, apply clean'


def check_task(evidence):
    path = evidence / 'hello.txt'
    try:
        content = path.read_text(errors='replace')
    except OSError:
        return FAIL, 'hello.txt missing or wrong'
    if content.strip() != TASK_LINE:
        return FAIL, 'hello.txt missing or wrong'
    return PASS, 'hello.txt holds the worker line'


def grade(evidence, agent, ticket, board, label):
    del ticket  # kept as a CLI option so graders match the launcher's ticket
    events = read_jsonl(evidence / 'stream.jsonl')
    started_at = parse_time(read_text(evidence / 'started_at').strip())
    session_id = find_session(events)

    checks = []
    name, result = 'loaded', check_loaded(evidence)
    checks.append((name, result))
    checks.append(('responsive', check_responsive(events)))
    checks.append(('checks loaded', check_checks_loaded(evidence)))

    if session_id is None:
        for name in ('session', 'login', 'pacer', 'task', 'board sync'):
            checks.append((name, (FAIL, NO_SESSION)))
    else:
        checks.append(('session', (PASS, 'session %s' % session_id)))
        checks.append(('login', check_login(evidence, started_at, agent)))
        checks.append(('pacer', check_pacer(evidence, session_id, events)))
        checks.append(('task', check_task(evidence)))
        checks.append(('board sync', check_board_sync(events, board, label)))
    return session_id, checks


def main(argv):
    parser = argparse.ArgumentParser(description='Grade a verify-valentin-mode run.')
    parser.add_argument('evidence', help='evidence directory written by run')
    parser.add_argument('--agent', default='VVM Test Agent')
    parser.add_argument('--ticket', default='SOFT-2849')
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

    session_id, checks = grade(evidence, args.agent, args.ticket, args.board, args.label)
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
