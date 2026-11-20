#!/usr/bin/env python3
"""Stop hook: after a turn, sync this chat's own board, as its own login.

MULTIPROMPT_TAB set means a Valentin-facing Multibot chat. The project's notes carry one
`Hypertask board: <id>, label: <label>` line. The hook starts `reconcile --apply --limit 5`
for that board and label, detached, at most every 10 minutes, and writes one status record
per board and label. When it cannot run, or the last run failed, it blocks the chat once an
hour with the one thing to fix. No MULTIPROMPT_TAB means a headless run and the hook passes.

reconcile-auto.py --self-test"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

THROTTLE = 600
BLOCK_WINDOW = 3600
NOTES = ('AGENTS.md', 'CLAUDE.md')
BOARD_LINE = re.compile(r'^Hypertask board:\s*(\d+),\s*label:\s*(.+?)\s*$')
CHECKUP = '/hypertask-checkup check 5'


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')


def state_dir(home):
    return Path(home) / '.local/state/reconcile-auto'


def record_path(home, board, label):
    return state_dir(home) / f'{board}-{slug(label)}.json'


def log_path(home, board, label):
    return state_dir(home) / f'{board}-{slug(label)}.log'


def pid_path(home, board, label):
    return state_dir(home) / f'{board}-{slug(label)}.pid'


def roster_path(home):
    return Path(home) / '.local/share/house-rules/fleet/roster.json'


def chat_names_path(home):
    return Path(home) / '.local/state/multiprompt/chat-names.json'


def token_path(home, name):
    return (Path(home) / '.config/hypertask-agents/credentials/sessions'
            / f'{slug(name)}-agent-token')


def git_root(cwd):
    try:
        done = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                              capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    root = done.stdout.strip()
    return Path(root) if done.returncode == 0 and root else None


def find_board(cwd):
    """(board, label, notes file) from the first board line at cwd or its git root."""
    places = [Path(cwd)]
    root = git_root(cwd)
    if root is not None and root != Path(cwd):
        places.append(root)
    for place in places:
        for name in NOTES:
            notes = place / name
            try:
                text = notes.read_text(errors='replace')
            except OSError:
                continue
            for line in text.splitlines():
                found = BOARD_LINE.match(line.strip())
                if found:
                    return int(found[1]), found[2], notes
    return None


def chat_name(home, tab):
    """The roster Multibot name for this tab, else the Multibot chat-name file."""
    try:
        rows = json.loads(roster_path(home).read_text()).get('rows') or []
    except (OSError, ValueError, AttributeError):
        rows = []
    for row in rows:
        if isinstance(row, dict) and row.get('tmux') == tab:
            name = str(row.get('multibot') or '').strip()
            if name:
                return name
    try:
        names = json.loads(chat_names_path(home).read_text())
    except (OSError, ValueError):
        return ''
    entry = names.get(tab) if isinstance(names, dict) else None
    return str(entry.get('name') or '').strip() if isinstance(entry, dict) else ''


def read_status(home, board, label):
    try:
        status = json.loads(record_path(home, board, label).read_text())
    except (OSError, ValueError):
        return None
    return status if isinstance(status, dict) else None


def is_running(home, board, label):
    try:
        pid = int(pid_path(home, board, label).read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        command = Path(f'/proc/{pid}/cmdline').read_bytes()
    except OSError:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    return b'reconcile-auto.py' in command


def parse_output(text):
    """(moved, unknown, summary) from a reconcile run's combined output."""
    summary = ''
    for line in text.splitlines():
        if line.startswith(('PREVIEW ', 'DRY RUN ')):
            summary = line.strip()
    if not summary:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        summary = lines[-1] if lines else ''
    found = re.search(r'unknown=(\d+)', summary)
    moved = sum(1 for line in text.splitlines() if line.startswith('MOVE '))
    return moved, int(found[1]) if found else 0, summary


def reconcile_script(home):
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / 'skills/hypertask-work/reconcile',
                      Path(home) / '.local/share/vstack/skills/hypertask-work/reconcile'):
        if candidate.is_file():
            return candidate
    found = shutil.which('reconcile')
    return Path(found) if found else None


def write_status(home, board, label, name, exit_code, output):
    moved, unknown, summary = parse_output(output)
    log = log_path(home, board, label)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(output)
    record = {'at': time.time(), 'session_name': name, 'board': board, 'label': label,
              'exit': exit_code, 'moved': moved, 'unknown': unknown,
              'summary_line': summary, 'log': str(log)}
    target = record_path(home, board, label)
    temporary = Path(str(target) + '.tmp')
    temporary.write_text(json.dumps(record, indent=1))
    temporary.replace(target)


def run(argv, env):
    """The detached worker: run reconcile once, then write the status record."""
    board, label, name, token, cwd = argv
    home = Path(env.get('HOME') or str(Path.home()))
    pid = pid_path(home, board, label)
    pid.parent.mkdir(parents=True, exist_ok=True)
    pid.write_text(str(os.getpid()))
    script = reconcile_script(home)
    output, code = '', 1
    try:
        if script is None:
            output = 'reconcile-auto: no reconcile script found\n'
        else:
            try:
                token_value = Path(token).read_text().strip()
            except OSError:
                token_value = ''
            if not token_value:
                output = f'reconcile-auto: board login token unreadable at {token}\n'
            else:
                run_env = dict(env)
                run_env['HT_TOKEN'] = token_value
                run_env['SHIP_SESSION_NAME'] = name
                command = [str(script), '--board', str(board), '--label', label,
                           '--apply', '--limit', '5']
                done = subprocess.run(command, capture_output=True, text=True,
                                      env=run_env, cwd=cwd, check=False)
                output = (done.stdout or '') + (done.stderr or '')
                code = done.returncode
    except (OSError, subprocess.SubprocessError) as error:
        output = f'reconcile-auto: {error}\n'
    finally:
        try:
            write_status(home, board, label, name, code, output)
        finally:
            try:
                pid.unlink()
            except OSError:
                pass
    return 0


def spawn(board, label, name, token, cwd, home, env):
    """Start the detached worker and return at once."""
    command = [sys.executable, str(Path(__file__).resolve()), '--run', str(board), label,
               name, str(token), str(cwd)]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
                     env=dict(env), cwd=str(cwd) if Path(cwd).is_dir() else None)


def started_env(env):
    """Reconcile needs a running user bus. Fill in the usual path when it is unset."""
    env = dict(env)
    uid = os.getuid()
    env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{uid}')
    env.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{uid}/bus')
    return env


def blocked_recently(home, session, now):
    stamp = state_dir(home) / 'blocks' / f'{slug(session)}.stamp'
    try:
        return now - float(stamp.read_text().strip()) < BLOCK_WINDOW
    except (OSError, ValueError):
        return False


def stamp_block(home, session, now):
    stamp = state_dir(home) / 'blocks' / f'{slug(session)}.stamp'
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(str(now))


def failure_text(status):
    log = status.get('log') or ''
    detail = status.get('summary_line') or 'no output'
    return (f"last run exit {status.get('exit')} unknown {status.get('unknown')}: {detail}"
            f'{"; log " + log if log else ""}')


def hook(payload, env, now=None):
    """The JSON a Stop hook prints for this payload and environment."""
    if not env.get('MULTIPROMPT_TAB'):
        return {}
    now = time.time() if now is None else now
    home = Path(env.get('HOME') or str(Path.home()))
    cwd = Path(payload.get('cwd') or env.get('PWD') or os.getcwd())
    tab = env['MULTIPROMPT_TAB']
    found = find_board(cwd)
    name = chat_name(home, tab)
    token = token_path(home, name) if name else None
    board = label = None
    problem = ''
    if found is None:
        problem = (f'no `Hypertask board: <id>, label: <label>` line in AGENTS.md '
                   f'or CLAUDE.md at {cwd}')
    else:
        board, label, _notes = found
        if not name:
            problem = (f'no Multibot name for tmux {tab!r} in {roster_path(home)} '
                       f'or {chat_names_path(home)}')
        elif not token.is_file():
            problem = f'board login token missing at {token}'
    if not problem:
        status = read_status(home, board, label)
        fresh = bool(status) and now - float(status.get('at') or 0) < THROTTLE
        if status and (status.get('exit') != 0 or (status.get('unknown') or 0) > 0):
            problem = failure_text(status)
        if not fresh and not is_running(home, board, label):
            try:
                spawn(board, label, name, token, cwd, home, started_env(env))
            except OSError as error:
                problem = f'could not start reconcile: {error}'
    if problem:
        session = payload.get('session_id') or tab
        if not blocked_recently(home, session, now):
            stamp_block(home, session, now)
            return {'decision': 'block',
                    'reason': (f'Board sync is not working for this chat: {problem}. '
                               f'Fix it now (see {CHECKUP}), then continue.')}
    return {}


def self_test():
    def notes(where, text='# project\n'):
        where.mkdir(parents=True, exist_ok=True)
        (where / 'AGENTS.md').write_text(text)

    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp) / 'home'
        project = Path(temp) / 'project'
        notes(project, 'Hypertask board: 2060, label: Test\n')
        roster = roster_path(home)
        roster.parent.mkdir(parents=True)
        roster.write_text(json.dumps({'rows': [
            {'tmux': 'live-test', 'multibot': 'Test Chat'}]}))
        names = chat_names_path(home)
        names.parent.mkdir(parents=True)
        names.write_text(json.dumps({'live-fallback': {'name': 'Fallback Chat'}}))
        assert chat_name(home, 'live-fallback') == 'Fallback Chat', 'chat-names is the fallback'
        token = token_path(home, 'Test Chat')
        token.parent.mkdir(parents=True)
        token.write_text('secret\n')
        env = {'HOME': str(home), 'MULTIPROMPT_TAB': ''}
        assert hook({'cwd': str(project)}, env) == {}, 'a headless run passes'

        env['MULTIPROMPT_TAB'] = 'live-test'
        payload = {'cwd': str(project), 'session_id': 'sid-a'}
        trial = tempfile.TemporaryDirectory()
        blank = Path(trial.name) / 'vstack-sibling'
        notes(blank)
        answer = hook(dict(payload, cwd=str(blank), session_id='sid-blank'), env, now=1000)
        assert answer.get('decision') == 'block', 'a project note without the line blocks'
        assert 'Hypertask board: <id>, label: <label>' in answer['reason'], 'the line is named'

        real_spawn, calls = globals()['spawn'], []

        def fake(*args):
            calls.append(args)

        globals()['spawn'] = fake
        try:
            token.unlink()
            answer = hook(dict(payload, session_id='sid-token'), env, now=1000)
            assert answer.get('decision') == 'block', 'a missing token blocks'
            assert str(token) in answer['reason'], 'the token path is named'
            assert not calls, 'a missing token never starts a run'

            token.write_text('secret\n')
            assert hook(dict(payload, session_id='sid-stale'), env, now=1000) == {}
            assert len(calls) == 1, 'a stale status starts one run'

            one, label = find_board(project)[:2]
            write_status(home, one, label, 'Test Chat', 0, 'PREVIEW board=2060 tickets=2 unknown=0\n')
            before = len(calls)
            assert hook(dict(payload, session_id='sid-fresh'), env, now=time.time()) == {}
            assert len(calls) == before, 'a fresh status starts no run'

            write_status(home, one, label, 'Test Chat', 1, 'MOVE X-1 Todo -> Doing\n')
            answer = hook(dict(payload, session_id='sid-fail'), env, now=time.time())
            assert answer.get('decision') == 'block', 'a failed run blocks'
            assert str(log_path(home, one, label)) in answer['reason'], 'the log is named'
            assert not calls[before:], 'a fresh failed status starts no run'

            again = hook(dict(payload, session_id='sid-fail'), env, now=time.time())
            assert again == {}, 'one block an hour per session'
        finally:
            globals()['spawn'] = real_spawn
        trial.cleanup()
    print('reconcile-auto self-test ok')


def main():
    argv = sys.argv[1:]
    if argv == ['--self-test']:
        self_test()
        return 0
    if argv[:1] == ['--run']:
        return run(argv[1:], os.environ)
    if not os.environ.get('MULTIPROMPT_TAB'):
        print('{}')
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    print(json.dumps(hook(payload, os.environ)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
