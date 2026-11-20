#!/usr/bin/env python3
"""Stop hook: after a turn, sync this chat's own board, as its own login.

MULTIPROMPT_TAB set means a Valentin-facing Multibot chat. The project's notes carry one
`Hypertask board: <id>` line. The label is the chat's own Multibot name, or the line's
optional `, label: <label>` override. The hook starts `reconcile --apply --limit 5` for
that board and label, detached, at most every 10 minutes, and writes one status record
per board and label. It blocks the chat once an hour, and only for setup this chat is
missing: the board line, the chat's name, or the token for its own login. A sync that fails is one line in
`~/.local/state/reconcile-auto/failures.jsonl` for the reconcile owner, never a block.
No MULTIPROMPT_TAB means a headless run and the hook passes.

reconcile-auto.py --self-test"""
import importlib.machinery
import importlib.util
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
BOARD_LINE = re.compile(r'^Hypertask board:\s*(\d+)(?:,\s*label:\s*(.+?))?\s*$')
CHECKUP = '/hypertask checkup'


def load_session():
    """The one login resolver, from the skill this hook belongs to."""
    here = Path(__file__).resolve()
    for folder in (here.parents[1] / 'skills/hypertask-work',
                   Path.home() / '.local/share/vstack/skills/hypertask-work'):
        path = folder / 'session_login.py'
        if path.is_file():
            loader = importlib.machinery.SourceFileLoader('fleet_session', str(path))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            sys.modules[loader.name] = module
            loader.exec_module(module)
            return module
    raise ImportError('session_login.py not found')


try:
    session = load_session()
except ImportError:
    session = None

slug = session.slug if session else None
state_dir = session.state_dir if session else None
record_path = session.record_path if session else None
log_path = session.log_path if session else None
roster_path = session.roster_path if session else None
chat_names_path = session.chat_names_path if session else None
token_path = session.token_path if session else None
chat_name = session.session_name if session else None
parse_output = session.parse_output if session else None
failures_path = session.failure_path if session else None


def pid_path(home, board, label):
    return state_dir(home) / f'{board}-{slug(label)}.pid'


def git_root(cwd):
    try:
        done = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                              capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    root = done.stdout.strip()
    return Path(root) if done.returncode == 0 and root else None


def find_board(cwd):
    """(board, label or None, notes file) from the first board line at cwd or its git root."""
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
                    return int(found[1]), (found[2] or '').strip() or None, notes
    return None


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


def failure_line(status):
    """What the reconcile owner needs to know about one failed sync."""
    return {'at': status.get('at'), 'board': status.get('board'), 'label': status.get('label'),
            'ticket': status.get('ticket'), 'session_name': status.get('session_name'),
            'summary': status.get('summary_line') or '', 'log': status.get('log') or ''}


def log_failure(home, status):
    """One line per failed run, and never a block. The store is best effort."""
    record = failure_line(status)
    same = ('at', 'board', 'label', 'session_name')
    if any(isinstance(row, dict) and all(row.get(k) == record[k] for k in same)
           for row in session.read_failures(home)):
        return session.failure_path(home)
    session.append_failure(home, record)
    return session.failure_path(home)


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
    session.write_record(record_path(home, board, label), {
        'at': time.time(), 'session_name': name, 'board': board, 'label': label, 'ticket': None,
        'exit': exit_code, 'moved': moved, 'unknown': unknown,
        'summary_line': summary, 'log': str(log)})


def run(argv, env):
    """The detached worker: run reconcile once, then write the status record."""
    board, label, name, token, cwd = argv
    board = int(board)
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


def failed(status):
    return status.get('exit') != 0 or (status.get('unknown') or 0) > 0


def hook(payload, env, now=None):
    """The JSON a Stop hook prints for this payload and environment.

    It blocks only on setup this chat is missing. Every tool failure becomes one
    line in the failures store for the reconcile owner, never a block.
    """
    if not env.get('MULTIPROMPT_TAB'):
        return {}
    now = time.time() if now is None else now
    home = Path(env.get('HOME') or str(Path.home()))
    cwd = Path(payload.get('cwd') or env.get('PWD') or os.getcwd())
    found = find_board(cwd)
    problem = ''
    board = label = None
    login = session.login_for_session(env)
    if found is None:
        problem = (f'no `Hypertask board: <id>` line in AGENTS.md '
                   f'or CLAUDE.md at {cwd}')
    elif login is None:
        problem = (f'no Multibot name for tmux {env["MULTIPROMPT_TAB"]!r} in '
                   f'{roster_path(home)} or {chat_names_path(home)}')
    else:
        board, label, _notes = found
        name, token = login
        # The label is per chat: the line's own label wins, else the Multibot name.
        label = label or name
        if not token.is_file():
            problem = f'board login token missing at {token}'
        else:
            status = read_status(home, board, label)
            if status and failed(status):
                log_failure(home, status)
            fresh = bool(status) and now - float(status.get('at') or 0) < THROTTLE
            if not fresh and not is_running(home, board, label):
                try:
                    spawn(board, label, name, token, cwd, home, started_env(env))
                except OSError as error:
                    log_failure(home, {'at': now, 'board': board, 'label': label,
                                       'session_name': name,
                                       'summary_line': f'could not start reconcile: {error}'})
    if problem:
        where = payload.get('session_id') or env['MULTIPROMPT_TAB']
        if not blocked_recently(home, where, now):
            stamp_block(home, where, now)
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
        notes(project, 'Hypertask board: 2060\n')
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
        assert 'Hypertask board: <id>' in answer['reason'], 'the line is named'

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
            assert calls[0][1] == 'Test Chat', 'a line without a label uses the chat name'

            one, label = find_board(project)[:2]
            assert label is None, 'a line without a label resolves to the chat name'
            label = 'Test Chat'
            write_status(home, one, label, 'Test Chat', 0, 'PREVIEW board=2060 tickets=2 unknown=0\n')
            before = len(calls)
            assert hook(dict(payload, session_id='sid-fresh'), env, now=time.time()) == {}
            assert len(calls) == before, 'a fresh status starts no run'

            write_status(home, one, label, 'Test Chat', 1, 'MOVE X-1 Todo -> Doing\n')
            answer = hook(dict(payload, session_id='sid-fail'), env, now=time.time())
            assert answer == {}, 'a failed sync never blocks the chat'
            assert not calls[before:], 'a fresh failed status starts no run'
            stored = failures_path(home).read_text().splitlines()
            assert len(stored) == 1, 'a failed run is one line for the reconcile owner'
            line = json.loads(stored[0])
            for field in ('at', 'board', 'label', 'ticket', 'session_name', 'summary', 'log'):
                assert field in line, f'the failure line names {field}'
            assert str(log_path(home, one, label)) == line['log'], 'the failure line links its log'
            hook(dict(payload, session_id='sid-fail'), env, now=time.time())
            assert len(failures_path(home).read_text().splitlines()) == 1, 'the same run logs once'

            write_status(home, one, label, 'Test Chat', 0, 'UNKNOWN X-2 | no facts\nPREVIEW board=2060 tickets=2 unknown=1\n')
            assert hook(dict(payload, session_id='sid-unknown'), env, now=time.time()) == {}, \
                'unknowns never block either'
            assert len(failures_path(home).read_text().splitlines()) == 2, 'unknowns are logged too'
        finally:
            globals()['spawn'] = real_spawn
        trial.cleanup()
    print('reconcile-auto self-test ok')


def main():
    argv = sys.argv[1:]
    if argv == ['--self-test']:
        self_test()
        return 0
    if session is None:
        print('{}')
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
