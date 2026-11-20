#!/usr/bin/env python3
"""UserPromptSubmit, Stop, and PreCompact (auto): valentin-mode chats hand off before autocompact.

Context size is the last assistant message.usage total in the transcript JSONL, read from the
file end. Soft threshold injects additionalContext once per 10% band; hard threshold blocks Stop
and auto PreCompact until the long-chat skill runs mp-fresh, unless warn-only (no Multibot host).

FAIL-OPEN: any exception exits 0 with no output.

long-chat.py --self-test
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

DEFAULT_WINDOW = 200_000
WINDOW_1M = 1_000_000
DEFAULT_SOFT = 0.55
DEFAULT_HARD = 0.70
MAX_BLOCKS = 3
SKILL = '~/.claude/skills/long-chat/SKILL.md'
READ_CHUNK = 1 << 20
MAX_TAIL_LINES = 4000

_spec = importlib.util.spec_from_file_location(
    'valentin_mode_loaded',
    Path(__file__).resolve().with_name('valentin_mode_loaded.py'))
valentin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(valentin)


def state_dir(home):
    return Path(home) / '.local/state/long-chat'


def home_dir(env):
    return Path(env.get('LONG_CHAT_HOME') or env.get('HOME') or Path.home())


def float_env(env, key, default):
    try:
        return float(env.get(key, default))
    except (TypeError, ValueError):
        return default


def window_tokens(model, env):
    override = env.get('LONG_CHAT_WINDOW')
    if override:
        try:
            return int(override)
        except ValueError:
            return WINDOW_1M
    if model and '[1m]' in model:
        return WINDOW_1M
    return DEFAULT_WINDOW


def usage_total(usage):
    if not isinstance(usage, dict):
        return None
    total = 0
    for key in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'):
        try:
            total += int(usage.get(key) or 0)
        except (TypeError, ValueError):
            return None
    return total


def iter_lines_from_end(path):
    """Newest JSONL lines first, without loading the whole transcript."""
    try:
        with open(path, 'rb') as handle:
            handle.seek(0, os.SEEK_END)
            pos = handle.tell()
            buf = b''
            while pos > 0:
                read_amt = min(READ_CHUNK, pos)
                pos -= read_amt
                handle.seek(pos)
                buf = handle.read(read_amt) + buf
                while True:
                    nl = buf.rfind(b'\n')
                    if nl == -1:
                        break
                    line = buf[nl + 1:]
                    buf = buf[:nl]
                    if line.strip():
                        yield line
            if buf.strip():
                yield buf
    except OSError:
        return


def last_context(transcript_path):
    """(token_count, model) from the last assistant line that carries message.usage."""
    if not transcript_path:
        return None, None
    for count, raw in enumerate(iter_lines_from_end(transcript_path)):
        if count >= MAX_TAIL_LINES:
            break
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if row.get('type') != 'assistant':
            continue
        message = row.get('message')
        if not isinstance(message, dict):
            continue
        usage = message.get('usage')
        total = usage_total(usage)
        if total is None:
            continue
        model = message.get('model') or ''
        return total, model if isinstance(model, str) else ''
    return None, None


def multibot_host(env):
    if not str(env.get('MULTIPROMPT_TAB') or '').strip():
        return False
    path = env.get('PATH') or os.environ.get('PATH', '')
    return bool(shutil.which('mp-fresh', path=path))


def soft_notified(home, session_id, band):
    path = state_dir(home) / f'{session_id}.soft-bands'
    try:
        bands = json.loads(path.read_text())
    except (OSError, ValueError):
        bands = []
    if not isinstance(bands, list):
        bands = []
    return band in bands


def mark_soft(home, session_id, band):
    path = state_dir(home) / f'{session_id}.soft-bands'
    try:
        bands = json.loads(path.read_text())
    except (OSError, ValueError):
        bands = []
    if not isinstance(bands, list):
        bands = []
    if band in bands:
        return
    bands.append(band)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(bands))
    except OSError:
        pass


def block_count(home, session_id):
    path = state_dir(home) / f'{session_id}.blocks'
    try:
        return int(path.read_text().strip())
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


def queued(home, session_id):
    return (state_dir(home) / f'{session_id}.queued').is_file()


def soft_context(size, window, soft):
    pct = int(round(100 * size / window))
    return {
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': (
                f'Chat context is about {pct}% of the window ({size:,} / {window:,} tokens). '
                f'Before autocompact, follow the long-chat skill at your next clean point '
                f'({SKILL}): hand over and run mp-fresh in this same Multibot chat.'
            ),
        },
    }


def hard_reason():
    return (
        f'Context is past the long-chat hard limit. Follow {SKILL} now: write the handover, '
        'run mp-fresh --handover <file>, then end the turn. Do not use /clear.'
    )


def hard_block():
    return {'decision': 'block', 'reason': hard_reason()}


def warn_no_host():
    return {
        'systemMessage': (
            'This chat is past the long-chat hard limit but has no Multibot host (no '
            'MULTIPROMPT_TAB or mp-fresh). Hand off manually when you can; autocompact may still run.'
        ),
    }


def user_prompt(payload, env):
    if not valentin.loaded(payload.get('transcript_path')):
        return {}
    session_id = payload.get('session_id')
    if not session_id:
        return {}
    size, model = last_context(payload.get('transcript_path'))
    if size is None:
        return {}
    window = window_tokens(model, env)
    soft = float_env(env, 'LONG_CHAT_SOFT', DEFAULT_SOFT)
    if size < soft * window:
        return {}
    band = min(9, int(size * 10 / window))
    home = home_dir(env)
    if soft_notified(home, session_id, band):
        return {}
    mark_soft(home, session_id, band)
    return soft_context(size, window, soft)


def stop_or_precompact(payload, env, event_name):
    if event_name == 'PreCompact' and payload.get('trigger') != 'auto':
        return {}
    if payload.get('stop_hook_active'):
        return {}
    if not valentin.loaded(payload.get('transcript_path')):
        return {}
    session_id = payload.get('session_id')
    if not session_id:
        return {}
    home = home_dir(env)
    if queued(home, session_id):
        return {}
    size, model = last_context(payload.get('transcript_path'))
    if size is None:
        return {}
    window = window_tokens(model, env)
    hard = float_env(env, 'LONG_CHAT_HARD', DEFAULT_HARD)
    if size < hard * window:
        return {}
    if not multibot_host(env):
        return warn_no_host()
    if block_count(home, session_id) >= MAX_BLOCKS:
        return {}
    bump_blocks(home, session_id)
    return hard_block()


def hook(payload, env):
    event = payload.get('hook_event_name') or ''
    if event == 'UserPromptSubmit':
        return user_prompt(payload, env)
    if event in ('Stop', 'PreCompact'):
        return stop_or_precompact(payload, env, event)
    return {}


def self_test():
    loaded_mark = (
        '{"type":"user","message":{"content":[{"type":"tool_result",'
        '"content":"Base directory for this skill: /x/valentin-mode\\n"}]}}\n'
    )

    def write_transcript(where, name, assistant_usage, model='claude-sonnet', extra_user=''):
        path = where / name
        usage_json = json.dumps(assistant_usage)
        body = (
            extra_user
            + '{"type":"assistant","message":{"role":"assistant","model":'
            + json.dumps(model)
            + ',"usage":'
            + usage_json
            + '}}\n'
        )
        path.write_text(loaded_mark + body)
        return str(path)

    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp) / 'home'
        place = Path(temp) / 'transcripts'
        place.mkdir()
        plain = place / 'plain.jsonl'
        plain.write_text('{"type":"user","message":{"content":"hello"}}\n')

        small = write_transcript(place, 'small.jsonl',
                                 {'input_tokens': 50000, 'cache_read_input_tokens': 0,
                                  'cache_creation_input_tokens': 0})
        soft_line = write_transcript(place, 'soft.jsonl',
                                     {'input_tokens': 120000, 'cache_read_input_tokens': 0,
                                      'cache_creation_input_tokens': 0})
        hard_line = write_transcript(place, 'hard.jsonl',
                                     {'input_tokens': 150000, 'cache_read_input_tokens': 0,
                                      'cache_creation_input_tokens': 0})

        env = {'HOME': str(home), 'LONG_CHAT_WINDOW': str(DEFAULT_WINDOW)}
        sid = 'sess-a'

        assert hook({'hook_event_name': 'UserPromptSubmit', 'session_id': sid,
                     'transcript_path': str(plain)}, env) == {}, 'not loaded -> nothing'
        assert hook({'hook_event_name': 'UserPromptSubmit', 'session_id': sid,
                     'transcript_path': small}, env) == {}, 'under soft -> nothing'

        payload_soft = {'hook_event_name': 'UserPromptSubmit', 'session_id': sid,
                        'transcript_path': soft_line}
        first = hook(payload_soft, env)
        assert first.get('hookSpecificOutput', {}).get('additionalContext'), 'soft -> context once'
        assert hook(payload_soft, env) == {}, 'same band -> once'

        stop_hard = {'hook_event_name': 'Stop', 'session_id': sid,
                     'transcript_path': hard_line, 'stop_hook_active': False}
        assert hook(stop_hard, env) == warn_no_host(), 'hard + no host -> no block'

        env_host = {**env, 'MULTIPROMPT_TAB': 'live-test'}
        bin_dir = home / 'bin'
        bin_dir.mkdir(parents=True)
        (bin_dir / 'mp-fresh').write_text('#!/bin/sh\nexit 0\n')
        (bin_dir / 'mp-fresh').chmod(0o755)
        env_host['PATH'] = f'{bin_dir}:{env.get("PATH", "")}'

        blocked = hook(stop_hard, env_host)
        assert blocked.get('decision') == 'block', 'hard + host -> block'

        queued_file = state_dir(home) / f'{sid}.queued'
        queued_file.parent.mkdir(parents=True, exist_ok=True)
        queued_file.write_text('')
        assert hook(stop_hard, env_host) == {}, 'queued marker -> no block'
        queued_file.unlink()

        active = {**stop_hard, 'stop_hook_active': True}
        assert hook(active, env_host) == {}, 'stop_hook_active -> no block'

        for _ in range(MAX_BLOCKS):
            hook(stop_hard, env_host)
        assert hook(stop_hard, env_host) == {}, '4th block -> no block'

        pre_manual = {'hook_event_name': 'PreCompact', 'trigger': 'manual',
                      'session_id': sid, 'transcript_path': hard_line}
        assert hook(pre_manual, env_host) == {}, 'manual PreCompact -> pass'
        pre_auto = {**pre_manual, 'trigger': 'auto'}
        env_host.pop('MULTIPROMPT_TAB')
        assert hook(pre_auto, env) == warn_no_host(), 'PreCompact auto warn-only without host'

    print('long-chat self-test ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        answer = hook(payload, os.environ)
    except Exception:
        return 0
    if answer:
        print(json.dumps(answer))
    return 0


if __name__ == '__main__':
    sys.exit(main())