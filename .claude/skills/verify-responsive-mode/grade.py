#!/usr/bin/env python3
"""Grade one verify-responsive-mode run from its evidence folder.

Reads the arrival times drive.py logged and the side effects the run left on
origin. Never reads the chat's own claims about what it did.

Usage: grade.py EVIDENCE_DIR    (exit 0 on PASS, 1 on FAIL, 2 on bad evidence)
"""
import json
import pathlib
import re
import sys

REPLY_LIMIT = 60.0
DETACHED = ('nohup', 'setsid', 'disown', 'tmux')
# A single & backgrounds the command; && does not.
BACKGROUND_AMP = re.compile(r'(?:^|[^&])&(?:[^&]|$)')
TRACKED_AGENTS = ('Agent', 'Task')
HOOK_FILE = re.compile(r'[^\s"\'`]+\.[a-z]{2}\b')
# A debug log line per hook run: "Hooks: <Event>[:<matcher>] [<command>] finished".
DEBUG_HOOK = re.compile(r'Hooks: ([A-Za-z]+)(?::\S*)?\s+\[([^\]]*)\]')


def read_text(path):
    try:
        return path.read_text(errors='replace')
    except OSError:
        return ''


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def load_chat(evidence):
    """The messages drive.py sent, and the events the chat produced, in order."""
    sent, events = [], []
    for line in read_text(evidence / 'chat.jsonl').splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if 'sent' in record:
            sent.append(record)
        elif 'ev' in record:
            events.append(record)
    return sent, events


def message_blocks(events, kind):
    """Every content block of one kind, as (message id, arrival time, block)."""
    for record in events:
        event = record['ev']
        if event.get('type') != 'assistant':
            continue
        message = event.get('message') or {}
        for block in message.get('content') or []:
            if isinstance(block, dict) and block.get('type') == kind:
                yield message.get('id'), record['t'], block


def whole_message(events, message_id, block):
    """Every text block sharing one message id, so an answer split over two
    blocks of a single message counts as one reply, not as two."""
    if message_id is None:
        return block.get('text', '')
    texts = [text.get('text', '') for other, _, text in message_blocks(events, 'text')
             if other == message_id]
    return '\n'.join(texts) if texts else block.get('text', '')


def reply_to(question, events, answer):
    """First text holding the answer after the question went out, and its time."""
    wanted = answer.lower()
    for message_id, at, block in message_blocks(events, 'text'):
        if at < question['t']:
            continue
        if wanted in (block.get('text') or '').lower():
            return at, whole_message(events, message_id, block)
    return None, None


def skill_text(evidence):
    """The skill under test: the folder the run saved, else the single file an
    older run saved. Empty when the evidence holds neither."""
    for path in (evidence / 'skill-under-test/SKILL.md', evidence / 'skill-under-test.md'):
        text = read_text(path)
        if text:
            return text
    return ''


def hook_files(command):
    """The script names a hook command line runs, hooks on this box being
    python3 "$CLAUDE_PLUGIN_ROOT/reply-check.py" or a plain .sh path."""
    return [token.rsplit('/', 1)[-1] for token in HOOK_FILE.findall(command)]


def frontmatter(text):
    """The lines between a SKILL.md's first two --- fences, or none."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return []
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == '---':
            return lines[1:index]
    return []


def hook_commands(text):
    """(event, file name) for every hook the skill's frontmatter turns on.
    Only the hooks: block counts, and only its own event lines."""
    block = []
    inside = False
    for line in frontmatter(text):
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
    """The hook file names a command line runs out of a .claude/skills/ folder.
    An unexpanded "$CLAUDE_PLUGIN_ROOT" leaves the path as /reply-check.py, which
    would match on name alone, so a path outside that folder never counts."""
    return [token.rsplit('/', 1)[-1] for token in HOOK_FILE.findall(command)
            if '.claude/skills/' in token]


def hook_runs(evidence):
    """(event, file name) for every hook the chat's debug log recorded running.
    The shape: "Hooks: <Event>[:<matcher>] [<command>] finished with status N".
    The transcript is no use here: a hook that prints nothing leaves no entry."""
    runs = []
    for line in read_text(evidence / 'debug.log').splitlines():
        match = DEBUG_HOOK.search(line)
        if not match:
            continue
        event, command = match.group(1), match.group(2)
        runs.extend((event, name) for name in installed_hook_files(command))
    return runs


def check_checks_loaded(evidence):
    """The skill's own hooks loaded with it. A skill that turns no hooks on has
    nothing to prove; one that does must show those hook files running in the
    chat's debug log, never in the chat's words."""
    text = skill_text(evidence)
    if not text:
        return True, 'no skill text in evidence, so no hooks block to check'
    wanted = hook_commands(text)
    if not wanted:
        return True, 'the skill under test turns no hooks on'
    if not (evidence / 'debug.log').is_file():
        return False, ('no debug.log: the skill turns hooks on, but nothing shows '
                       'they ran')
    ran = hook_runs(evidence)
    missing = [f'{name} ({event})' for event, name in wanted
               if (event, name) not in ran]
    if missing:
        return False, ('debug.log shows no run of ' + ', '.join(missing)
                       + ' from the scratch project\'s .claude/skills/ folder')
    return True, 'debug.log shows every declared hook ran: ' + ', '.join(
        f'{name} ({event})' for event, name in wanted)


def check_loaded(evidence, marker):
    """The skill body reached the chat, read from the chat's own transcript:
    the output stream does not echo an expanded slash command."""
    text = read_text(evidence / 'transcript.jsonl')
    if marker and json.dumps(marker)[1:-1] in text:
        return True, 'skill text is in the chat transcript'
    return False, 'skill text never reached the chat transcript'


def slow_commands(events, slow):
    """Every Bash command that runs the slow step, or the paced helper, with its input."""
    for _, _, block in message_blocks(events, 'tool_use'):
        name = block.get('name', '')
        args = block.get('input') if isinstance(block.get('input'), dict) else {}
        command = args.get('command') or ''
        if name == 'Bash' and (slow in command or 'plan-pick' in command):
            yield command, args
        elif name in TRACKED_AGENTS and args.get('run_in_background') is True:
            yield name, args


def check_background(events, slow):
    """The slow step was handed to the harness as a background job, which is what
    lets the chat answer questions and still wake up when the job ends."""
    tracked, detached = [], []
    for command, args in slow_commands(events, slow):
        if args.get('run_in_background') is True:
            tracked.append(command)
        elif (any(word in command for word in DETACHED)
              or BACKGROUND_AMP.search(command)):
            detached.append(command)
    if detached:
        return False, f'slow step detached from the harness: {detached[0][:80]}'
    if tracked:
        return True, f'slow step ran as a tracked background job: {tracked[0][:60]}'
    return False, 'slow step never ran as a tracked background job'


def expected_lines(spec):
    if spec.get('expected_lines'):
        return spec['expected_lines']
    if spec.get('expected_line'):
        return [spec['expected_line']]
    return []


def reply_rows(sent, events, answers):
    """One row per side question, plus the check that two questions got two replies."""
    rows, replies = [], []
    for index, answer in enumerate(answers, 1):
        question = sent[index] if index < len(sent) else None
        if question is None:
            rows.append((f'reply {index}', False, 'not run: side question never sent'))
            replies.append(None)
            continue
        at, text = reply_to(question, events, answer)
        replies.append(text)
        if at is None:
            rows.append((f'reply {index}', False, f'no reply containing {answer!r}'))
            continue
        delay = at - question['t']
        rows.append((f'reply {index}', delay <= REPLY_LIMIT,
                     f'{answer!r} after {delay:.0f}s, limit {REPLY_LIMIT:.0f}s'))
    if not all(replies) or len(replies) != len(answers):
        rows.append(('separate', False, 'not run: a reply is missing'))
        return rows
    merged = len(set(replies)) < len(replies) or any(
        other.lower() in reply.lower()
        for index, reply in enumerate(replies)
        for other_index, other in enumerate(answers) if index != other_index)
    rows.append(('separate', not merged,
                 'both answers in one reply' if merged else 'one reply per question'))
    return rows


class BadEvidence(Exception):
    """The run left too little behind to grade, so no verdict is possible."""


def grade(evidence):
    """Every check, then the verdict. Returns True on PASS."""
    spec = read_json(evidence / 'spec.json')
    if not spec:
        raise BadEvidence('no readable spec.json in ' + str(evidence))
    sent, events = load_chat(evidence)
    if not sent:
        raise BadEvidence('no message was sent in ' + str(evidence / 'chat.jsonl'))

    rows = [('loaded', *check_loaded(evidence, spec.get('skill_marker'))),
            ('checks loaded', *check_checks_loaded(evidence))]
    rows += reply_rows(sent, events, spec.get('answers') or [])
    rows.append(('background', *check_background(events, spec.get('slow_step', 'slow-report'))))

    for index, marker in enumerate(('ran.txt', 'ran2.txt')[:len(expected_lines(spec))], 1):
        ran = (evidence / marker).exists()
        rows.append((f'slow step {index} ran', ran,
                     f'slow step {index} finished' if ran
                     else f'slow step {index} never finished'))

    lines = expected_lines(spec)
    pushed = read_text(evidence / 'pushed-report.md')
    missing = [line for line in lines if line not in pushed]
    rows.append(('pushed', bool(lines) and not missing,
                 'origin main has REPORT.md with every report line' if lines and not missing
                 else 'origin main is missing ' + ', '.join(repr(line) for line in missing or ['every report line'])))

    verdict = 'PASS' if all(ok for _, ok, _ in rows) else 'FAIL'
    text = ''.join(f"{'PASS' if ok else 'FAIL'} {name}: {why}\n" for name, ok, why in rows)
    text += f'VERDICT {verdict}\n'
    (evidence / 'verdict.txt').write_text(text)
    (evidence / 'verdict.json').write_text(json.dumps({
        'verdict': verdict,
        'checks': [{'check': name, 'pass': ok, 'why': why} for name, ok, why in rows],
    }, indent=2) + '\n')
    sys.stdout.write(text)
    return verdict == 'PASS'


def main(argv):
    if len(argv) != 2:
        sys.stderr.write('usage: grade.py EVIDENCE_DIR\n')
        return 2
    try:
        passed = grade(pathlib.Path(argv[1]))
    except BadEvidence as error:
        sys.stderr.write('grade: ' + str(error) + '\n')
        return 2
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
