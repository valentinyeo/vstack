"""A chat's own board login and the status store its card syncs write.

One rule, one place: the after-turn hook, the lease and vstack-feedback all read
a chat's login from here; none keeps its own copy. `login` holds the order the
three lookups run in.
"""
import base64
import json
import os
from pathlib import Path
import re
import time

TOKENS = '.config/hypertask-agents/credentials/sessions'
STATE = '.local/state/reconcile-auto'
# The environment keys a chat's own process carries its Multibot tab in.
TAB_KEYS = ('MULTIPROMPT_TAB', 'ZSB_SESSION', 'MULTIBOT_SESSION')
TOKEN_FILE = 'HYPERTASK_AGENT_TOKEN_FILE'
# The owner is a person, not an agent. A login named after him writes as him, so
# no session resolves to one: "Valentins Claude Code", "Valentin Yeo" and
# "Valentin's Chat" all refuse.
PERSON = re.compile(r'^valentins?(?:-|$)')


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')


def is_person(name):
    """Is this name the owner's, rather than an agent's?"""
    return bool(PERSON.match(slug(name)))


def home(env=None):
    return Path((env if env is not None else os.environ).get('HOME') or str(Path.home()))


def roster_path(home):
    return Path(home) / '.local/share/house-rules/fleet/roster.json'


def chat_names_path(home):
    return Path(home) / '.local/state/multiprompt/chat-names.json'


def token_path(home, name):
    return Path(home) / TOKENS / f'{slug(name)}-agent-token'


def token_agent_id(token):
    """The agent id a chat token carries, or '' when it carries none.

    The token's own claim names the agent, the same way identity.md step 1 reads
    it. The token is never printed, logged or written anywhere.
    """
    try:
        payload = str(token or '').strip().split('.')[1]
        payload += '=' * (-len(payload) % 4)
        claim = json.loads(base64.urlsafe_b64decode(payload)).get('agentId')
    except (IndexError, TypeError, ValueError):
        return ''
    return str(claim or '').strip()


def own_agent_id(name, env=None):
    """The agent id behind this chat's own login, or '' when it cannot be read.

    The login is the chat's own token file when it has one, else the caller's
    HT_TOKEN, else the session login. One agent can show a name that differs
    from its chat (only the owner renames an agent), so board rules compare this
    id as well as the name.
    """
    env = os.environ if env is None else env
    path = token_path(home(env), name) if name and not is_person(name) else None
    token = ''
    if path is not None and path.is_file():
        try:
            token = path.read_text().strip()
        except OSError:
            token = ''
    if not token:
        token = str(env.get('HT_TOKEN') or '').strip()
    if not token:
        found = login_for_session(env)
        path = found[1] if found else None
        if path is None or not path.is_file():
            return ''
        try:
            token = path.read_text().strip()
        except OSError:
            return ''
    return token_agent_id(token)


def chat_names(home):
    """The chat-name file as {tab: entry}, {} when it cannot be read."""
    try:
        names = json.loads(chat_names_path(home).read_text())
    except (OSError, ValueError):
        return {}
    return names if isinstance(names, dict) else {}


def chat_tabs(home, name):
    """The tabs this Multibot name lives on, newest published first.

    A restart leaves the old tab's entry behind, so only `at` says which tab is current.
    """
    wanted = str(name).strip()
    if not wanted:
        return []
    rows = [(entry, tab) for tab, entry in chat_names(home).items()
            if isinstance(entry, dict) and str(entry.get('name') or '').strip() == wanted]
    rows.sort(key=lambda pair: published(pair[0]), reverse=True)
    return [tab for _entry, tab in rows]


def published(entry):
    """The publish time a chat-name entry carries, 0 when it carries none."""
    at = entry.get('at')
    return at if isinstance(at, (int, float)) else 0


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
    entry = chat_names(home).get(tab)
    return str(entry.get('name') or '').strip() if isinstance(entry, dict) else ''


def agent_name(path):
    stem = Path(path).name
    if stem.endswith('-agent-token'):
        stem = stem[: -len('-agent-token')]
    return ' '.join(stem.replace('-', ' ').split())


def token_file_login(env, where):
    """(name, path, source) for HYPERTASK_AGENT_TOKEN_FILE, or None when it is unset.

    An explicit file wins over every name lookup. A path that does not exist is
    still the answer: the caller names the file in its own error rather than
    quietly filing under another login.
    """
    raw = str(env.get(TOKEN_FILE) or '').strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    name = str(env.get('SHIP_SESSION_NAME') or '').strip()
    if not name or is_person(name):
        name = agent_name(path)
    if not name:
        return None
    return (name, path, TOKEN_FILE)


def ship_name(env):
    """The agent name SHIP_SESSION_NAME names, or '' when it names no agent."""
    name = str(env.get('SHIP_SESSION_NAME') or '').strip()
    return '' if not name or is_person(name) else name


def ship_name_login(env, where):
    """(name, path, source) for SHIP_SESSION_NAME, or None when it names no agent login."""
    name = ship_name(env)
    if not name:
        return None
    path = token_path(where, name)
    return (name, path, 'SHIP_SESSION_NAME') if path.is_file() else None


def tab_login(env, where):
    """(name, path, source) for the chat's tab name, or None when no tab names the chat."""
    tab = str(env.get('MULTIPROMPT_TAB') or '').strip()
    name = session_name(where, tab) if tab else ''
    if not name:
        return None
    return (name, token_path(where, name), 'MULTIPROMPT_TAB')


def name_login(env=None):
    """This chat's name from SHIP_SESSION_NAME or its tab, token file or not, or ''.

    The order matches `login`, and a person's name never resolves.
    """
    env = os.environ if env is None else env
    where = home(env)
    name = ship_name(env)
    if name:
        return name
    tab = str(env.get('MULTIPROMPT_TAB') or '').strip()
    name = session_name(where, tab) if tab else ''
    return '' if is_person(name) else name


def tab_chat_name(env=None):
    """This chat's own Multibot name read from its tab alone, or '' when no tab names it."""
    env = os.environ if env is None else env
    tab = str(env.get('MULTIPROMPT_TAB') or '').strip()
    if not tab:
        return ''
    name = session_name(home(env), tab)
    return '' if not name or is_person(name) else name


def env_login_name(env, where):
    """The login name the environment names, read the way `login` reads it."""
    found = token_file_login(env, where)
    return found[0] if found else ship_name(env)


def borrowed(env=None):
    """(name, tab name) when the environment names a login for a chat other than this tab's.

    The lease asks this before it assigns or syncs anything (VSTA-306: the HT
    Features tab's leases assigned board 15 tickets as HT Product Lead). With no
    tab name known there is nothing to compare against and this is None.
    """
    env = os.environ if env is None else env
    tab = tab_chat_name(env)
    if not tab:
        return None
    name = env_login_name(env, home(env))
    if not name or slug(name) == slug(tab):
        return None
    return (name, tab)


def login(env=None):
    """(name, token path, source) for this chat's own login, or None when it has none.

    The order is HYPERTASK_AGENT_TOKEN_FILE, then SHIP_SESSION_NAME, then the tab
    name; `source` names which one the path came from. A path may not exist yet:
    the caller decides whether a missing token is its own setup gap (the hook) or
    a reason to stay quiet (the lease).
    """
    env = os.environ if env is None else env
    where = home(env)
    return (token_file_login(env, where) or ship_name_login(env, where)
            or tab_login(env, where))


def login_for_session(env=None):
    """(name, token path) for this chat's own login, or None when it has none."""
    found = login(env)
    return found[:2] if found else None


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
