#!/usr/bin/env python3
"""Harness start and prompt: a chat that switched harness still gets valentin-mode and its loop.

Valentin, 2026-11-25 (VSTA-305): Multibot's "Switch AI" moved three chats from Claude to Codex. Each
got AGENTS.md, the skill list and a handover quoting "valentin-mode v111", but never read
skills/valentin-mode/SKILL.md, and `loop-state status` said "not armed" for all three. Claude loads
valentin-mode from the skill's own frontmatter hook; Codex, Antigravity and Pi run no such hook, so
the harness start itself has to hand the chat the mode: the version line, the order to read the
skill in full, and, when this chat drains a board, the one command that arms board-drain the
no-background-jobs way.

Codex reads `hookSpecificOutput.additionalContext` from SessionStart and UserPromptSubmit; Antigravity
reads `injectSteps` from PreInvocation, so that path emits its start line once per conversation; Pi's
extension reads the plain text this hook prints. Fails open: any problem prints nothing (or `{}`) and
exits 0, so a slow or broken check never stalls a chat.

harness-start.py [--harness codex|agy|pi] [--event start|prompt] [--cwd DIR] [--session ID]
harness-start.py --self-test
"""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOOP_STATE = ROOT / 'skills' / 'board-drain' / 'loop-state'
GUARD = HERE / 'board-drain-guard.py'
NOTES = ('CLAUDE.md', 'AGENTS.md')
BOARD_LINE = re.compile(r'^Hypertask board:\s*(\d+)(?:,\s*label:\s*(.+?))?\s*$')
PROMPT_EVERY = 600
VERSION_TIMEOUT = 2.0
CODEX = 'codex'
AGY = 'agy'
PI = 'pi'
HARNESSES = (CODEX, AGY, PI)
EVENTS = ('start', 'prompt')


def load_module(name, path):
    """A hyphen-named script beside this hook, loaded the way the tests load it."""
    if name in sys.modules:
        return sys.modules[name]
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def guard():
    """Board-drain's guard owns how a chat is named from its own tab; reuse it, never re-derive it."""
    return load_module('board_drain_guard', GUARD)


def loop_state():
    """The one owner of loop state."""
    return load_module('board_drain_loop_state', LOOP_STATE)


def home_dir(env):
    return Path(env.get('HOME') or Path.home())


def display(path, home):
    text = str(path)
    prefix = str(home)
    return '~' + text[len(prefix):] if text.startswith(prefix) else text


def version_script(home):
    for candidate in (home / '.local/state/vstack/skills/valentin-mode/version.sh',
                      home / '.local/share/vstack/skills/valentin-mode/version.sh',
                      ROOT / 'skills/valentin-mode/version.sh'):
        if candidate.is_file():
            return candidate
    return None


def version_line(home):
    script = version_script(home)
    if script is None:
        return ''
    try:
        done = subprocess.run(['sh', str(script)], capture_output=True, text=True,
                              timeout=VERSION_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return ''
    lines = (done.stdout or '').strip().splitlines()
    return lines[0] if lines else ''


def skill_path(home, harness):
    """The SKILL.md this harness has installed, or the Claude path every harness can open."""
    preferred = {CODEX: home / '.codex/skills', AGY: home / '.gemini/config/skills',
                 PI: home / '.pi/agent/skills'}.get(harness)
    for base in (preferred, home / '.claude/skills'):
        if base is None:
            continue
        path = base / 'valentin-mode' / 'SKILL.md'
        if path.is_file():
            return path
    return home / '.claude/skills/valentin-mode/SKILL.md'


def notes(cwd):
    if not cwd:
        return None
    try:
        folders = [Path(cwd), *Path(cwd).parents]
    except (OSError, ValueError):
        return None
    for folder in folders:
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


def own_chat(env, home, cwd=None):
    """(name, board, label) for the Multibot chat running this hook; ('', None, '') when unknown."""
    name = ''
    board = label = None
    try:
        name = guard().own_name(env, home)
    except Exception:  # noqa: BLE001 - a broken lookup must never stall a start
        name = ''
    try:
        record = loop_state().own_record(env)
    except Exception:  # noqa: BLE001
        record = {}
    if not name and isinstance(record, dict) and isinstance(record.get('name'), str):
        name = record['name'].strip()
    if isinstance(record, dict):
        if isinstance(record.get('board'), int):
            board = record['board']
        if isinstance(record.get('label'), str) and record['label'].strip():
            label = record['label'].strip()
    if board is None:
        found = notes(cwd or env.get('PWD') or os.getcwd())
        if found:
            board, label = found
    return name, board, label


def armed(name):
    if not name:
        return False
    try:
        return loop_state().is_armed(name)
    except Exception:  # noqa: BLE001
        return False


def rearm_text(name, board, label, harness):
    share = '~/.local/share/vstack/skills/board-drain'
    board_text = f'board {board}' if board else 'its Hypertask view'
    label_text = f' (label "{label}")' if label else ''
    named = f'--name "{name}"' if name else '--name "<this chat\'s Multibot name>"'
    every = ''
    try:
        seconds = loop_state().loop_interval()
        every = f'--every {seconds}s'
    except Exception:  # noqa: BLE001
        every = ''
    fields = ' '.join(part for part in (
        named,
        f'--board {board}' if board else '',
        f'--label "{label}"' if label else '',
        every,
        '--job <the recurring job id>',
    ) if part)
    prompt = (f'/pstack:poteto-mode full autopilot on this queue: every workable ticket in my view. '
              f'each item is independent. done when {share}/drain-check --board {board} '
              f'--label "{label}" passes.') if board and label else (
              f'/pstack:poteto-mode full autopilot on this queue: every workable ticket in my view. '
              f'each item is independent. done when {share}/drain-check passes.')
    silent = ('You have no background jobs on this harness, so the watcher step does not apply: '
              'arm the loop the no-background-jobs way, with one recurring job.\n'
              if harness != PI else '')
    return (f'Board drain: this chat drains {board_text}{label_text} and its loop is not armed, so '
            f'nothing will wake it. {silent}Arm it now, following {share}/SKILL.md '
            f'("Codex or chats without background jobs"): one recurring job on '
            f'`~/.local/bin/plan-pick --loop-interval` (at least 2h) that runs the loop prompt, then '
            f'record it:\n{share}/loop-state arm {fields}\nLoop prompt: {prompt}')


def start_text(env, home, harness, cwd=None):
    text = ''
    version = version_line(home)
    if version:
        text += version + '\n\n'
    text += (f'Valentin mode is loaded for this chat. Read {display(skill_path(home, harness), home)} '
             f'in full now, before your first reply; the hook hands you the mode a switched chat '
             f'used to drop, and your first reply names that version line.')
    name, board, label = own_chat(env, home, cwd)
    if name and (board or label) and not armed(name):
        text += '\n\n' + rearm_text(name, board, label, harness)
    return text


def prompt_text(env, home, harness, cwd=None):
    name, board, label = own_chat(env, home, cwd)
    if not name or not (board or label) or armed(name):
        return ''
    return rearm_text(name, board, label, harness)


def state_dir(home):
    return home / '.local' / 'state' / 'vstack' / 'harness-start'


def session_key(payload, conversation=None):
    for value in (conversation, payload.get('session_id'), payload.get('conversationId')):
        if isinstance(value, str) and value.strip():
            return hashlib.sha256(value.strip().encode()).hexdigest()[:32]
    return 'unknown'


def marked(home, key, suffix):
    return (state_dir(home) / f'{key}.{suffix}').is_file()


def mark(home, key, suffix, now=None):
    path = state_dir(home) / f'{key}.{suffix}'
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(time.time() if now is None else now)))
    except OSError:
        pass


def prompt_due(home, key, now=None, every=PROMPT_EVERY):
    try:
        last = float((state_dir(home) / f'{key}.prompt').read_text().strip())
    except (OSError, ValueError):
        return True
    return (time.time() if now is None else now) - last >= every


def answer(payload, env, home=None, harness=CODEX, event='start', now=None):
    home = home or home_dir(env)
    key = session_key(payload, env.get('HARNESS_START_SESSION'))
    here = payload.get('cwd') if isinstance(payload.get('cwd'), str) else None
    text = ''
    if event == 'start':
        if not marked(home, key, 'start'):
            text = start_text(env, home, harness, here)
            if text:
                mark(home, key, 'start', now)
                mark(home, key, 'prompt', now)   # the start line already carries the re-arm order
        if harness != AGY:
            return text
    # Antigravity fires PreInvocation before every model call and has no prompt event, so its
    # start dedupe and its re-arm check share this path.
    if not text and prompt_due(home, key, now):
        text = prompt_text(env, home, harness, here)
        if text:
            mark(home, key, 'prompt', now)
    return text


def shaped(text, harness, event):
    if not text:
        return {}
    if harness == AGY:
        return {'injectSteps': [{'systemMessage': {'systemMessage': text}}],
                'terminationBehavior': ''}
    return {'hookSpecificOutput': {
        'hookEventName': 'SessionStart' if event == 'start' else 'UserPromptSubmit',
        'additionalContext': text}}


def self_test():
    bad = []
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        previous = {key: os.environ.get(key) for key in
                    ('HOME', 'BOARD_DRAIN_STATE_DIR', 'MULTIBOT_SESSION', 'PWD')}
        state = home / 'board-state'
        os.environ['HOME'] = str(home)
        os.environ['BOARD_DRAIN_STATE_DIR'] = str(state)
        os.environ['MULTIBOT_SESSION'] = 'switched-chat'
        os.environ.pop('PWD', None)
        try:
            version = home / '.local/state/vstack/skills/valentin-mode/version.sh'
            version.parent.mkdir(parents=True)
            version.write_text('#!/bin/sh\necho "valentin-mode v999 (latest)"\n')
            announce = home / '.local/state/roster/announce'
            announce.mkdir(parents=True)
            (announce / 'switched-chat.json').write_text(
                json.dumps({'tmux': 'switched-chat', 'multibot': 'Switched Chat'}))
            skill = home / '.codex/skills/valentin-mode'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: valentin-mode\n---\n\n# Valentin mode\n')
            cwd = home / 'repo'
            cwd.mkdir()
            (cwd / 'AGENTS.md').write_text('Hypertask board: 13556, label: Switched\n')

            loop = loop_state()
            loop.arm('Switched Chat', every='2h', job='cron-old', board=13556, label='Switched')
            record = loop.state_path('Switched Chat')
            stale = json.loads(record.read_text())
            stale['owner_pid'] = 2_000_000_000     # a pid no process holds: the abandoned chat
            record.write_text(json.dumps(stale))

            payload = {'session_id': 'sid-1', 'cwd': str(cwd)}
            env = {'HOME': str(home), 'MULTIBOT_SESSION': 'switched-chat'}
            text = answer(payload, env, home, CODEX, 'start')
            if 'valentin-mode v999 (latest)' not in text:
                bad.append('the start line carries the version')
            if 'valentin-mode/SKILL.md' not in text:
                bad.append('the start line names the skill to read')
            if 'loop-state arm' not in text or 'board 13556' not in text:
                bad.append('the start line arms the board drain loop')
            if answer(payload, env, home, CODEX, 'start') != '':
                bad.append('the start line is said once per session')

            shaped_start = shaped(text, CODEX, 'start')
            if shaped_start.get('hookSpecificOutput', {}).get('hookEventName') != 'SessionStart':
                bad.append('codex start output names its event')

            follow = {'session_id': 'sid-2', 'cwd': str(cwd)}
            first = answer(follow, env, home, CODEX, 'prompt')
            if 'loop-state arm' not in first:
                bad.append('a prompt in an unarmed chat gets the re-arm line')
            if answer(follow, env, home, CODEX, 'prompt') != '':
                bad.append('the re-arm line is capped per session')
            if not answer(follow, env, home, CODEX, 'prompt', now=time.time() + PROMPT_EVERY + 1):
                bad.append('past the cap the re-arm line comes back')

            loop.arm('Switched Chat', every='2h', job='cron-new', board=13556, label='Switched')
            quiet = {'session_id': 'sid-3', 'cwd': str(cwd)}
            if answer(quiet, env, home, CODEX, 'prompt') != '':
                bad.append('an armed loop is not nagged')

            agy = answer({'conversationId': 'conv-1'}, env, home, AGY, 'start')
            steps = shaped(agy, AGY, 'start').get('injectSteps') or []
            if not steps or 'valentin-mode/SKILL.md' not in json.dumps(steps):
                bad.append('antigravity gets injectSteps carrying the skill path')
            if answer({'conversationId': 'conv-1'}, env, home, AGY, 'start') != '':
                bad.append('antigravity says its start line once per conversation')

            bare = answer({'session_id': 'sid-4'}, {'HOME': str(home)}, home, CODEX, 'start')
            if 'valentin-mode/SKILL.md' not in bare or 'Board drain:' in bare:
                bad.append('a chat with no board gets the mode only')

            empty = Path(tempfile.mkdtemp())
            try:
                if 'valentin-mode/SKILL.md' not in answer({}, {'HOME': str(empty)}, empty, PI, 'start'):
                    bad.append('a home with nothing installed still names the skill path')
            finally:
                for path in sorted(empty.rglob('*'), reverse=True):
                    path.unlink() if path.is_file() else path.rmdir()
                empty.rmdir()
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    print('harness-start self-test ok' if not bad else
          f'harness-start self-test FAILED {bad}')
    return 1 if bad else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', choices=HARNESSES, default=CODEX)
    parser.add_argument('--event', choices=EVENTS, default='start')
    parser.add_argument('--cwd', default=None)
    parser.add_argument('--session', default=None)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ''
        payload = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    env = dict(os.environ)
    if args.cwd:
        env['PWD'] = args.cwd
        payload.setdefault('cwd', args.cwd)
    if args.session:
        payload.setdefault('session_id', args.session)
    try:
        if args.harness == PI:
            text = answer(payload, env, harness=PI, event=args.event)
            if text:
                print(text)
            return 0
        print(json.dumps(shaped(answer(payload, env, harness=args.harness, event=args.event),
                                args.harness, args.event)))
    except Exception:  # noqa: BLE001 - fail open, always
        print('{}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
