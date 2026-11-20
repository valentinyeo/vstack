"""A chat's own board login and the status store its card syncs write.

One rule, one place: a Multibot chat's tmux session names it in the house-rules
fleet roster, and its login is that name's agent token. The after-turn hook and
the lease both read it from here; neither keeps its own copy.
"""
import json
import os
from pathlib import Path
import re
import time

TOKENS = '.config/hypertask-agents/credentials/sessions'
STATE = '.local/state/reconcile-auto'


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')


def home(env=None):
    return Path((env if env is not None else os.environ).get('HOME') or str(Path.home()))


def roster_path(home):
    return Path(home) / '.local/share/house-rules/fleet/roster.json'


def chat_names_path(home):
    return Path(home) / '.local/state/multiprompt/chat-names.json'


def token_path(home, name):
    return Path(home) / TOKENS / f'{slug(name)}-agent-token'


def session_name(home, tab):
    """The roster Multibot name for this tmux session, else the chat-name file."""
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


def login_for_session(env=None):
    """(name, token path) for the chat in MULTIPROMPT_TAB, or None when unnamed.

    A returned path may not exist yet: the caller decides whether a missing token
    is its own setup gap (the hook) or a reason to stay quiet (the lease).
    """
    env = os.environ if env is None else env
    tab = str(env.get('MULTIPROMPT_TAB') or '').strip()
    if not tab:
        return None
    where = home(env)
    name = session_name(where, tab)
    return (name, token_path(where, name)) if name else None


def state_dir(home):
    return Path(home) / STATE


def record_path(home, board, label):
    return state_dir(home) / f'{board}-{slug(label)}.json'


def log_path(home, board, label):
    return state_dir(home) / f'{board}-{slug(label)}.log'


def card_record_path(home, board, ticket, phase):
    return state_dir(home) / f'{board}-{slug(ticket)}-{slug(phase)}.json'


def card_log_path(home, board, ticket, phase):
    return state_dir(home) / f'{board}-{slug(ticket)}-{slug(phase)}.log'


def failure_path(home):
    return state_dir(home) / 'failures.jsonl'


def read_failures(home, limit=500):
    """The newest failure lines, for the reconcile owner and for dedupe."""
    try:
        lines = failure_path(home).read_text().splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError):
        return []


def append_failure(home, record):
    """One JSON line for the reconcile owner. A store that cannot be written
    never fails its caller: the sync itself matters more than its report."""
    path = failure_path(home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as handle:
            handle.write(json.dumps(record) + '\n')
        return True
    except OSError:
        return False


def write_record(path, record):
    """One status record, whole or not at all."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(record, indent=1))
    temporary.replace(path)


def parse_output(text):
    """(moved, unknown, summary) from a reconcile run's combined output.

    The summary is the run's own verdict line, never a progress or timing line.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = ''
    for line in lines:
        if line.startswith(('PREVIEW ', 'DRY RUN ')):
            summary = line
    if not summary:
        for line in lines:
            if line.startswith(('MOVE ', 'PLAN ', 'KEEP ', 'SKIP ', 'UNKNOWN ', 'DEFERRED ')):
                summary = line
                break
    if not summary:
        summary = lines[-1] if lines else ''
    found = re.search(r'unknown=(\d+)', summary)
    moved = sum(1 for line in lines if line.startswith('MOVE '))
    return moved, int(found[1]) if found else 0, summary
