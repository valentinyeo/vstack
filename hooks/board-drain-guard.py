#!/usr/bin/env python3
"""UserPromptSubmit and Stop: a chat whose board watcher died is told to re-arm, in its own turn.

Valentin, 2026-11-23: in Multi Bot Bugs and Multi Bot Features the background board watcher had
died and nothing woke them; board 13734 drifted to 89 tickets in AI Review until he noticed. A
background job dies with the chat process, its task notification dies with it, and the safety
cron was a session cron that died too, so the chat has to check itself.

This hook reads this chat's own loop record and its watcher's pulse (VSTA-151). The chat is named
by its own Multibot tab in its own environment and the host's own announce record for that tab, so
it reads and nudges one chat: the one running this hook. It never reads or messages another chat,
and it fails open: any problem prints nothing and the turn runs.

The decision, in order:
1. No own name, or no loop record for it: nothing to say.
2. `loop-state status` says armed (or expires soon): the watcher is pulsing, so nothing to say.
3. It says `watcher dead since <time>`, or the loop is not armed: the chat has nothing to wake it.
   A prompt gets that fact as context; a Stop blocks, up to MAX_BLOCKS times, until the chat starts
   a fresh watcher or says what blocks it.

board-drain-guard.py --self-test
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOOP_STATE = ROOT / 'skills' / 'board-drain' / 'loop-state'
TAB_KEYS = ('MULTIPROMPT_TAB', 'ZSB_SESSION', 'MULTIBOT_SESSION')
SKILL = '~/.claude/skills/board-drain'
MAX_BLOCKS = 3
DEAD = re.compile(r'^watcher dead since (.+)$')
WHAT = ('Your board drain watcher is dead since {since}. Nothing is polling your view, so nothing '
        'will wake this chat.')
OFF = ('Your board drain loop is not armed: this chat restarted or the loop expired. Nothing will '
       'wake this chat.')


def home_dir(env):
    return Path(env.get('HOME') or Path.home())


def announce_dir(home):
    return home / '.local' / 'state' / 'roster' / 'announce'


def tab(env):
    """This chat process's own Multibot tab, the name the host records it under."""
    for key in TAB_KEYS:
        value = str(env.get(key) or '').strip()
        if value:
            return value
    return ''


def own_name(env, home):
    """This chat's Multibot name, from the host's announce record for its own tab."""
    explicit = str(env.get('BOARD_DRAIN_NAME') or '').strip()
    if explicit:
        return explicit
    here = tab(env)
    if not here:
        return ''
    try:
        record = json.loads((announce_dir(home) / f'{here}.json').read_text())
    except (OSError, ValueError):
        return ''
    if not isinstance(record, dict) or record.get('tmux') != here:
        return ''
    name = record.get('multibot')
    return name.strip() if isinstance(name, str) else ''


def loop_state():
    """The one owner of loop state, loaded from beside this hook, the way the tests load it."""
    name = 'board_drain_loop_state'
    if name in sys.modules:
        return sys.modules[name]
    loader = importlib.machinery.SourceFileLoader(name, str(LOOP_STATE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def rearm(name, state):
    """The one command that re-arms this chat's watcher on the view it drains."""
    board, label = state.get('board'), state.get('label')
    if isinstance(board, int) and isinstance(label, str) and label:
        return (f'{SKILL}/watch --board {board} --label "{label}" --name "{name}" as a tracked '
                f'background Bash job (7200000 ms timeout)')
    return f'{SKILL}/SKILL.md Arm step 2'


def nudge(name, state, code, line):
    """What this chat is told: the fact, its time, and the command that fixes it. '' when fine."""
    dead = DEAD.match(line or '')
    if code != 2 or not (dead or line == 'not armed'):
        return ''
    what = WHAT.format(since=dead.group(1)) if dead else OFF
    return (f'{what} Re-arm now: {rearm(name, state)}, then end this turn with the watcher '
            f'running.')


def state_dir(home):
    return home / '.local' / 'state' / 'board-drain-guard'


def block_count(home, session_id):
    try:
        return int((state_dir(home) / f'{session_id}.blocks').read_text().strip())
    except (OSError, ValueError):
        return 0


def bump_blocks(home, session_id):
    path = state_dir(home) / f'{session_id}.blocks'
    count = block_count(home, session_id) + 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(count))
    except OSError:
        pass
    return count


def own_loop(env, home, now=None):
    """(name, state, code, line) for this chat's own loop, or None when there is no record."""
    name = own_name(env, home)
    if not name:
        return None
    loop = loop_state()
    try:
        state = loop.stored(name)
        if not state:
            return None
        code, line = loop.status(name, now=time.time() if now is None else now)
    except Exception:  # noqa: BLE001 - a broken check must never hold a chat's turn
        return None
    return name, state, code, line


def answer(payload, env, home=None, now=None):
    """This hook's one answer for one event: context on a prompt, a block on a Stop."""
    home = home or home_dir(env)
    found = own_loop(env, home, now=now)
    if found is None:
        return {}
    name, state, code, line = found
    text = nudge(name, state, code, line)
    if not text:
        return {}
    event = payload.get('hook_event_name') or ''
    if event == 'UserPromptSubmit':
        return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                       'additionalContext': text}}
    if event != 'Stop':
        return {}
    session_id = str(payload.get('session_id') or '').strip()
    if not session_id or block_count(home, session_id) >= MAX_BLOCKS:
        return {}
    bump_blocks(home, session_id)
    return {'decision': 'block', 'reason': text}


def self_test():
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        announce = announce_dir(home)
        announce.mkdir(parents=True)
        state = home / 'state'
        previous = os.environ.get('BOARD_DRAIN_STATE_DIR')
        os.environ['BOARD_DRAIN_STATE_DIR'] = str(state)
        try:
            loop = loop_state()
            now = 1800000000
            (announce / 'live-guard.json').write_text(json.dumps({
                'tmux': 'live-guard', 'multibot': 'Guard Test'}))
            (announce / 'live-other.json').write_text(json.dumps({
                'tmux': 'live-other', 'multibot': 'Other Chat'}))
            env = {'MULTIBOT_SESSION': 'live-guard'}
            prompt = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'sid-1'}
            stop = {'hook_event_name': 'Stop', 'session_id': 'sid-1'}
            assert answer(prompt, env, home, now) == {}, 'a chat that never armed is left alone'

            loop.arm('Guard Test', every='6h', job='cron-1', now=now, board=2060,
                     label='Board Drain Loop')
            assert answer(prompt, env, home, now) == {}, 'an armed loop with no watcher recorded is quiet'

            loop.record_sync('Guard Test', True, '', now=now)
            loop.record_watch('Guard Test', os.getpid(), now=now, every=180)
            assert answer(prompt, env, home, now) == {}, 'a pulsing watcher is quiet'

            # The real failure: the watcher exited, or the chat process died with it.
            dead = loop.record_watch('Guard Test', 2_000_000_000, now=now - 3600, every=180)
            assert dead['watch_beat'] == loop.iso(now - 3600), 'starting a watcher leaves a pulse'
            told = answer(prompt, env, home, now)
            context = told.get('hookSpecificOutput', {}).get('additionalContext', '')
            assert 'watcher is dead since 2027-01-15T07:00:00Z' in context, context
            assert 'watch --board 2060 --label "Board Drain Loop" --name "Guard Test"' in context, (
                'the nudge names the exact command')
            assert answer(stop, env, home, now).get('decision') == 'block', 'Stop holds the turn'
            assert block_count(home, 'sid-1') == 1, 'one block recorded'

            # A watcher that exits on purpose leaves the same silence.
            loop.record_watch('Guard Test', os.getpid(), now=now, every=180)
            loop.clear_watch('Guard Test')
            assert 'watcher is dead since' in answer(prompt, env, home, now)[
                'hookSpecificOutput']['additionalContext'], 'an exited watcher is dead too'

            # A hung watcher: the pid lives but the pulse stopped.
            loop.record_watch('Guard Test', os.getpid(), now=now - 600, every=180)
            assert 'watcher is dead since' in nudge('Guard Test', loop.stored('Guard Test'),
                                                    *loop.status('Guard Test', now=now)), (
                'a live pid past three polls is dead')

            # A restart: the owner process is gone, so the loop is not armed.
            loop.arm('Guard Test', every='6h', job='cron-1', now=now - 60, board=2060,
                     label='Board Drain Loop')
            state_path = loop.state_path('Guard Test')
            record = json.loads(state_path.read_text())
            record['owner_pid'] = 2_000_000_000
            state_path.write_text(json.dumps(record))
            off = answer(prompt, env, home, now)['hookSpecificOutput']['additionalContext']
            assert 'not armed' in off and 'Re-arm now' in off, off

            # The blocks are capped, so a chat cannot be trapped in the turn.
            for _ in range(MAX_BLOCKS - 1):
                answer(stop, env, home, now)
            assert answer(stop, env, home, now) == {}, 'past the cap the turn ends'

            # Own chat only: another chat's dead watcher is not this chat's business.
            loop.arm('Other Chat', every='6h', now=now, board=2060, label='Other')
            loop.record_watch('Other Chat', 2_000_000_000, now=now - 3600, every=180)
            mine = answer(prompt, {'MULTIBOT_SESSION': 'live-guard'}, home, now)[
                'hookSpecificOutput']['additionalContext']
            assert '"Guard Test"' in mine and 'Other Chat' not in mine, (
                'this chat reads its own record, never the other chat\'s')
            theirs = answer(prompt, {'MULTIBOT_SESSION': 'live-other'}, home, now)[
                'hookSpecificOutput']['additionalContext']
            assert 'Other Chat' in theirs and 'Guard Test' not in theirs, (
                'the same hook in the other chat reads only that chat')
            assert answer(prompt, {}, home, now) == {}, 'no tab, no verdict'
            assert answer(prompt, {'MULTIBOT_SESSION': 'live-gone'}, home, now) == {}, (
                'an unknown tab has no record')
        finally:
            if previous is None:
                os.environ.pop('BOARD_DRAIN_STATE_DIR', None)
            else:
                os.environ['BOARD_DRAIN_STATE_DIR'] = previous
    print('board-drain-guard self-test ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        return self_test()
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        reply = answer(payload, os.environ)
    except Exception:  # noqa: BLE001 - fail open, always
        return 0
    if reply:
        print(json.dumps(reply))
    return 0


if __name__ == '__main__':
    sys.exit(main())
