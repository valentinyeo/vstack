#!/usr/bin/env python3
"""Stop guard: a chat with an open ticket must not end its turn with nothing to wake it.

Valentin, 2026-11-20: a Cursor cloud agent finished at 12:51 and the chat sat still until 21:40. The turn
ended with no tracked background job alive, so no task notification was ever going to arrive. This guard
blocks that turn once, until the chat starts a tracked job or says what blocks it.

The decision, in order:
1. `stop_hook_active` is true: this guard already blocked this turn, so allow.
2. A live background job in the transcript's last lines: allow. A job starts on a Bash background result
   ("Command running in background with ID: <id>") or an async agent result ("agentId: <id>"), and ends on
   a `<task-notification>` naming it, or a TaskStop/KillShell call naming it.
3. The harness wakes this chat when a tracked job exits, not when it prints. The long-lived board-drain
   watcher instead sends its own Multibot tab a prompt, at most once per 60s, coalescing changes;
   unavailable or failed delivery falls back to printing and exiting 0. A live job is allowed here.
   No job, but the reply's last line is a question to Valentin: allow, he owes the answer.
4. Otherwise ask this chat's own board for its open tickets (Doing, In Progress, Checks, AI Review,
   assigned to its agent). One open ticket blocks.
5. No board line, no login, or any error, timeout or unreadable transcript: allow. A quiet check must never
   hold a chat hostage.

Stubbing for tests and self-test: `IDLE_STOP_CLI` points at a fake hypertask command, and
`IDLE_STOP_TIMEOUT` sets the seconds allowed for its call (default 8). `HYPERTASK_AGENT_TOKEN_FILE` names
this chat's agent token file.

idle-stop.py --self-test
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from bin_path import find

NOTES = ('CLAUDE.md', 'AGENTS.md')
BOARD_LINE = re.compile(r'^Hypertask board:\s*(\d+)(?:,\s*label:\s*(.+?))?\s*$')
OPEN_SECTIONS = frozenset({'Doing', 'In Progress', 'Checks', 'AI Review'})
ENDING = frozenset({'completed', 'killed', 'stopped', 'failed'})
STOP_TOOLS = frozenset({'TaskStop', 'KillShell'})
HARNESS = ('<task-notification>', '<system-reminder>', '<command-message>', '<local-command-')
BACKGROUND = re.compile(r'Command running in background with ID:\s*([A-Za-z0-9_-]+)')
ASYNC = re.compile(r'Async agent launched[\s\S]{0,600}?agentId:\s*([A-Za-z0-9_-]+)')
NOTIFICATION = re.compile(r'<task-notification>([\s\S]*?)</task-notification>')
TASK_ID = re.compile(r'<task-id>\s*([^<\s]+)\s*</task-id>')
STATUS = re.compile(r'<status>\s*([^<\s]+)\s*</status>')
LINES = 4000
TAIL_BYTES = 4 * 1024 * 1024
MESSAGE = ('Ticket {key} is still open and no background job is running, so nothing will wake this chat. '
           'Start the next step as a tracked background job (worker, CI watch or board watcher), or say '
           'what blocks it, then end the turn.')


def tail(transcript):
    """The transcript's last LINES lines, file order. A cut first line is dropped."""
    try:
        if not Path(transcript).is_file():
            return None
        with Path(transcript).open('rb') as handle:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - TAIL_BYTES))
            data = handle.read()
    except OSError:
        return None
    lines = data.decode('utf-8', 'ignore').splitlines()
    if size > TAIL_BYTES:
        lines = lines[1:]
    return lines[-LINES:]


def block_texts(content):
    """The strings a user entry carries: its whole message, and each tool result's text."""
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get('type') != 'tool_result':
                continue
            value = block.get('content')
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for part in value:
                    if isinstance(part, dict) and isinstance(part.get('text'), str):
                        yield part['text']


def tool_uses(content):
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                yield block


def said(content):
    """The assistant text in one entry."""
    if isinstance(content, str):
        return [content]
    return [block['text'] for block in (content if isinstance(content, list) else [])
            if isinstance(block, dict) and block.get('type') == 'text'
            and isinstance(block.get('text'), str)]


def him(entry, content):
    """Did Valentin type this entry? Harness notes, tool results and skill bodies are not him."""
    if entry.get('isMeta') or entry.get('isSidechain'):
        return False
    texts = said(content)
    return any(value.strip() and not value.lstrip().startswith(HARNESS) for value in texts)


def started(entry, content):
    """Background job ids this entry started."""
    ids = set()
    for text in block_texts(content):
        ids.update(BACKGROUND.findall(text))
        ids.update(ASYNC.findall(text))
    result = entry.get('toolUseResult')
    if isinstance(result, dict):
        if isinstance(result.get('backgroundTaskId'), str):
            ids.add(result['backgroundTaskId'])
        if result.get('isAsync') and isinstance(result.get('agentId'), str):
            ids.add(result['agentId'])
    return ids


def ended(entry, content):
    """Background job ids this entry ended: a task notification for it, or a stop call naming it."""
    ids = set()
    for text in block_texts(content):
        for body in NOTIFICATION.findall(text):
            status = STATUS.search(body)
            if status and status.group(1).lower() not in ENDING:
                continue
            ids.update(TASK_ID.findall(body))
    for block in tool_uses(content):
        if block.get('name') in STOP_TOOLS:
            ids.update(value for value in (block.get('input') or {}).values() if isinstance(value, str))
    return ids


def scan(transcript):
    """(live job ids, this turn's assistant text), None when the transcript is unreadable."""
    lines = tail(transcript)
    if lines is None:
        return None
    live, text = set(), []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get('type') not in ('user', 'assistant'):
            continue
        message = entry.get('message')
        content = message.get('content') if isinstance(message, dict) else None
        if entry['type'] == 'assistant':
            if not entry.get('isSidechain'):
                text.extend(said(content))   # a subagent's words are not this chat's reply
            live -= ended(entry, content)
            continue
        live |= started(entry, content)
        live -= ended(entry, content)
        if him(entry, content):
            text = []
    return live, '\n'.join(text)


def asking(text):
    """Does the reply end by asking Valentin something? Its last non-empty line ends with '?'."""
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip().endswith('?')
    return False


def notes(cwd):
    """(board, label) from the nearest CLAUDE.md or AGENTS.md line, or None."""
    for folder in [Path(cwd), *Path(cwd).parents]:
        for name in NOTES:
            try:
                lines = (folder / name).read_text(errors='ignore').splitlines()
            except OSError:
                continue
            for line in lines:
                match = BOARD_LINE.match(line.strip())
                if match:
                    return int(match.group(1)), (match.group(2) or '').strip()
    return None


def state_dir():
    return Path(os.environ.get('BOARD_DRAIN_STATE_DIR') or Path.home() / '.local/state/board-drain')


def loop_state(board, label):
    """This chat's board-drain state record, {} when there is none: it carries the chat's name."""
    best = {}
    for path in sorted(state_dir().glob('*.json')):
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(state, dict):
            continue
        if label and str(state.get('label') or '').strip().lower() == label.strip().lower():
            return state
        if not label and str(state.get('board') or '') == str(board):
            best = best or state
    return best


def read_token(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ''


def session_login():
    """The repo's one login resolver: (name, token path), or None."""
    for folder in (ROOT / 'skills/hypertask-work', Path.home() / '.local/share/vstack/skills/hypertask-work'):
        path = folder / 'session_login.py'
        if path.is_file():
            break
    else:
        return None
    try:
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader('idle_stop_login', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[loader.name] = module
        loader.exec_module(module)
        return module.login_for_session()
    except Exception:
        return None


def login(board, label):
    """(agent name, token) for this chat's own board login, ('', '') when it has none."""
    path = os.environ.get('HYPERTASK_AGENT_TOKEN_FILE')
    if path:
        return os.environ.get('HYPERTASK_AGENT_NAME', ''), read_token(path)
    state = loop_state(board, label)
    name = str(state.get('name') or '')
    for key in ('agent_token_file', 'token_file'):
        if state.get(key):
            return name, read_token(state[key])
    if state.get('token') and isinstance(state['token'], str):
        return name, state['token'].strip()
    found = session_login()
    if found:
        return str(found[0] or ''), read_token(found[1])
    return '', ''


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')


def mine(task, name):
    """Is this ticket assigned to this chat's agent? Unknown assignees count as mine."""
    assignees = [row for row in task.get('assignees') or [] if isinstance(row, dict)]
    if not assignees or not name:
        return True
    return any(slug(row.get('displayName') or '') == slug(name) for row in assignees)


def cli():
    return os.environ.get('IDLE_STOP_CLI') or find('hypertask') or 'hypertask'


def open_tickets(board, label, name, token):
    """This chat's open ticket keys. Any error or timeout gives [], so the guard fails open."""
    try:
        timeout = float(os.environ.get('IDLE_STOP_TIMEOUT') or 8)
    except ValueError:
        timeout = 8.0
    command = [cli(), '--json', '--token', token, 'task', 'list', '--project', str(board),
               '--label', label, '--assigned-to', 'me', '--limit', '100']
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode:
        return []
    try:
        page = json.loads(done.stdout or '')
    except ValueError:
        return []
    if not isinstance(page, dict) or page.get('success') is False:
        return []
    keys = []
    for task in page.get('tasks') or []:
        if not isinstance(task, dict) or (task.get('section') or '') not in OPEN_SECTIONS:
            continue
        key = task.get('ticketNumber')
        if key and mine(task, name):
            keys.append(str(key))
    return keys


def verdict(data):
    """The block message, or '' to allow the turn to end."""
    if not isinstance(data, dict) or data.get('stop_hook_active'):
        return ''
    found = scan(data.get('transcript_path') or '')
    if not found:
        return ''
    live, text = found
    if live or asking(text):
        return ''
    found = notes(data.get('cwd') or os.getcwd())
    if not found:
        return ''
    board, label = found
    if not label:
        label = str(loop_state(board, '').get('label') or '').strip()
    if not label:
        return ''
    name, token = login(board, label)
    if not token:
        return ''
    keys = open_tickets(board, label, name, token)
    return MESSAGE.format(key=keys[0]) if keys else ''


def background(transcript, job, agent=None):
    """A transcript line for a tool result: a finished tool call that started `job`."""
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': job}]},
        'toolUseResult': {'backgroundTaskId': job} if agent is None else
        {'isAsync': True, 'agentId': job}}


def notification(job, status='completed'):
    return {'type': 'user', 'message': {'role': 'user',
                                       'content': f'<task-notification>\n<task-id>{job}</task-id>\n'
                                                  f'<status>{status}</status>\n</task-notification>'}}


def reply(text):
    return {'type': 'assistant', 'isSidechain': False,
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


def human(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}}


def self_test():
    """Every case runs the real decision against a hand-written transcript and a fake CLI."""
    folder = Path(tempfile.mkdtemp())
    try:
        project = folder / 'project'
        project.mkdir()
        (project / 'CLAUDE.md').write_text('# project\n\nHypertask board: 13556, label: Idle Stop\n')
        token = folder / 'token'
        token.write_text('stub-token\n')
        open_ticket = folder / 'hypertask'
        open_ticket.write_text('#!/bin/sh\nprintf \'{"tasks": [{"ticketNumber": "VSTA-1", '
                               '"section": "Doing"}]}\'\n')
        slow = folder / 'slow'
        slow.write_text('#!/bin/sh\nsleep 30\n')
        for script in (open_ticket, slow):
            script.chmod(0o755)
        os.environ['HYPERTASK_AGENT_TOKEN_FILE'] = str(token)
        os.environ['IDLE_STOP_CLI'] = str(open_ticket)
        os.environ['IDLE_STOP_TIMEOUT'] = '0.4'
        os.environ['BOARD_DRAIN_STATE_DIR'] = str(folder / 'state')
        os.environ.pop('HYPERTASK_AGENT_NAME', None)
        start = ('Command running in background with ID: bxo4265ry. Output is being written to: '
                 '/tmp/tasks/bxo4265ry.output.')
        cases = [
            ('a live job allows', [human('do it'), background(start, 'bxo4265ry'),
                                   reply('CI watcher bxo4265ry is running.')], str(project), ''),
            ('a finished job blocks', [human('do it'), background(start, 'bxo4265ry'),
                                       notification('bxo4265ry'), reply('CI is green.')],
             str(project), MESSAGE.format(key='VSTA-1')),
            ('a stopped job blocks', [human('do it'), background(start, 'bxo4265ry'),
                                      {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
                                          {'type': 'tool_use', 'name': 'TaskStop',
                                           'input': {'task_id': 'bxo4265ry'}}]}},
                                      reply('Stopped.')], str(project), MESSAGE.format(key='VSTA-1')),
            ('an async agent counts as live', [human('brief'), background('Async agent launched '
                                                                        'successfully.\nagentId: '
                                                                        'ad4867cb12c16aa1a', 'x', 'async'),
                                               reply('Worker is running.')], str(project), ''),
            ('an agent notification ends it', [human('brief'), background('x', 'ad4867cb12c16aa1a', 'async'),
                                               notification('ad4867cb12c16aa1a'), reply('Done.')],
             str(project), MESSAGE.format(key='VSTA-1')),
            ('a question allows', [human('do it'), reply('Two of four are done. Want the rest?')],
             str(project), ''),
            ('a missing board line allows', [human('do it'), reply('Done.')], str(folder), ''),
            ('a slow board call allows', [human('do it'), reply('Done.')], str(project), 'slow'),
        ]
        for case in cases:
            label, entries, cwd = case[0], case[1], case[2]
            expected = case[3]
            transcript = folder / 'transcript.jsonl'
            transcript.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
            os.environ['IDLE_STOP_CLI'] = str(open_ticket)
            if expected == 'slow':
                os.environ['IDLE_STOP_CLI'] = str(slow)
                expected = ''
            answer = verdict({'transcript_path': str(transcript), 'cwd': cwd})
            assert answer == expected, f'{label}: expected {expected!r}, got {answer!r}'
        assert verdict({'transcript_path': 'x', 'cwd': str(project), 'stop_hook_active': True}) == '', \
            'a second Stop check in the same turn allows'
        os.environ['IDLE_STOP_CLI'] = str(open_ticket)
        transcript.write_text(json.dumps(human('do it')) + '\n' + json.dumps(reply('Done.')) + '\n')
        os.environ['HYPERTASK_AGENT_TOKEN_FILE'] = str(folder / 'missing')
        assert verdict({'transcript_path': str(transcript), 'cwd': str(project)}) == '', \
            'no token file means the guard stays quiet'
        assert verdict('not a dict') == '', 'garbage input allows'
        print('idle-stop self-test ok')
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        why = verdict(data)
    except Exception:
        return 0
    if why:
        print(json.dumps({'decision': 'block', 'reason': why}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
