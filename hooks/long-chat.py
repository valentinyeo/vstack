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
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_WINDOW = 200_000
WINDOW_1M = 1_000_000
DEFAULT_SOFT = 0.55
DEFAULT_HARD = 0.70
SOFT_CAP = 300_000
HARD_CAP = 400_000
MAX_BLOCKS = 3
NOHOST_TTL = 30 * 60
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


def int_env(env, key, default):
    try:
        return int(env.get(key, default))
    except (TypeError, ValueError):
        return default


def token_threshold(window, fraction, cap, env, cap_key, default_cap):
    cap_tokens = int_env(env, cap_key, default_cap)
    return min(int(fraction * window), cap_tokens)


_CLAUDE_5_1M = re.compile(r'claude-(opus|sonnet|fable)-5', re.IGNORECASE)
_BARE_1M = frozenset({'opus', 'sonnet', 'fable'})


def window_tokens(model, env, size=None):
    override = env.get('LONG_CHAT_WINDOW')
    if override:
        try:
            return int(override)
        except ValueError:
            return WINDOW_1M
    if model:
        low = model.lower()
        if 'haiku' in low:
            return DEFAULT_WINDOW
        if '[1m]' in model or _CLAUDE_5_1M.search(model):
            return WINDOW_1M
        if low.strip() in _BARE_1M:
            return WINDOW_1M
    if size is not None and size > DEFAULT_WINDOW:
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


def agent_host_dir(home):
    return Path(home) / '.local/state/multiprompt/agent-host'


def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _tmux_needles(tab):
    quoted = json.dumps(tab)
    return (f'"tmux": {quoted}'.encode(), f'"tmux":{quoted}'.encode())


def _pid_from_state(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get('pid') is not None:
        return data.get('pid')
    return data.get('agent_pid')


def host_pid_for_tab(home, tab):
    root = agent_host_dir(home)
    if not tab or not root.is_dir():
        return None
    needles = _tmux_needles(tab)
    for path in root.glob('*.config.json'):
        try:
            head = path.read_bytes()[:4096]
        except OSError:
            continue
        if not any(n in head for n in needles):
            continue
        try:
            cfg = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(cfg, dict) or cfg.get('tmux') != tab:
            continue
        base = path.name[: -len('.config.json')]
        if not base:
            return None
        state_path = path.parent / f'{base}.state.json'
        if not state_path.is_file():
            return None
        return _pid_from_state(state_path)
    for path in root.glob('*.state.json'):
        try:
            head = path.read_bytes()[:8192]
        except OSError:
            continue
        if not any(n in head for n in needles):
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get('tmux') != tab:
            continue
        if data.get('pid') is not None:
            return data.get('pid')
        if data.get('agent_pid') is not None:
            return data.get('agent_pid')
        return None
    return None


def agent_host_live(home, env):
    tab = str(env.get('MULTIPROMPT_TAB') or '').strip()
    if not tab:
        return False
    pid = host_pid_for_tab(home, tab)
    if pid is None:
        return False
    return pid_alive(pid)


def nohost_warn(home, session_id, now=None):
    path = state_dir(home) / f'{session_id}.nohost'
    try:
        age = (now if now is not None else time.time()) - path.stat().st_mtime
    except OSError:
        return False
    return age < NOHOST_TTL


def handoff_enforced(home, session_id, env, now=None):
    """True when hard-limit blocking may run (Multibot can accept mp-fresh)."""
    if not multibot_host(env):
        return False
    if nohost_warn(home, session_id, now=now):
        return False
    if not agent_host_live(home, env):
        return False
    return True


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


def soft_context(size, window, soft_tokens, hard_tokens):
    pct = int(round(100 * size / window))
    return {
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': (
                f'Chat context is about {pct}% of the window ({size:,} / {window:,} tokens). '
                f'Long-chat limits for this window: warn at {soft_tokens:,} tokens, hand off at '
                f'{hard_tokens:,}. Before autocompact, follow the long-chat skill at your next '
                f'clean point ({SKILL}): hand over and run mp-fresh in this same Multibot chat.'
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
            'This chat is past the long-chat hard limit but Multibot cannot run a fresh start '
            '(no tab or mp-fresh, host not running, or a recent no-host marker). Hand off manually '
            'when you can; autocompact may still run.'
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
    window = window_tokens(model, env, size)
    soft_frac = float_env(env, 'LONG_CHAT_SOFT', DEFAULT_SOFT)
    hard_frac = float_env(env, 'LONG_CHAT_HARD', DEFAULT_HARD)
    soft_tokens = token_threshold(
        window, soft_frac, SOFT_CAP, env, 'LONG_CHAT_SOFT_TOKENS', SOFT_CAP)
    hard_tokens = token_threshold(
        window, hard_frac, HARD_CAP, env, 'LONG_CHAT_HARD_TOKENS', HARD_CAP)
    if size < soft_tokens:
        return {}
    band = min(9, int(size * 10 / window))
    home = home_dir(env)
    if soft_notified(home, session_id, band):
        return {}
    mark_soft(home, session_id, band)
    return soft_context(size, window, soft_tokens, hard_tokens)


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
    window = window_tokens(model, env, size)
    hard_frac = float_env(env, 'LONG_CHAT_HARD', DEFAULT_HARD)
    hard_tokens = token_threshold(
        window, hard_frac, HARD_CAP, env, 'LONG_CHAT_HARD_TOKENS', HARD_CAP)
    if size < hard_tokens:
        return {}
    if not handoff_enforced(home, session_id, env):
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

        host_dir = agent_host_dir(home)
        host_dir.mkdir(parents=True)
        (host_dir / 'live-test.state.json').write_text(json.dumps({
            'tmux': 'live-test', 'pid': os.getpid()}))

        cfg_host = agent_host_dir(home)
        (cfg_host / 'pinned.config.json').write_text(json.dumps({
            'tmux': 'live-cfg', 'sid': 'sid-cfg', 'provider': 'claude'}))
        (cfg_host / 'pinned.state.json').write_text(json.dumps({
            'sid': 'sid-cfg', 'provider': 'claude', 'pid': os.getpid()}))
        env_cfg = {**env_host, 'MULTIPROMPT_TAB': 'live-cfg'}
        stop_cfg = {**stop_hard, 'session_id': 'sess-cfg'}
        assert hook(stop_cfg, env_cfg).get('decision') == 'block', (
            'config.json tmux + state pid -> block')

        blocked = hook(stop_hard, env_host)
        assert blocked.get('decision') == 'block', 'hard + live host -> block'

        (host_dir / 'live-test.state.json').unlink()
        assert hook(stop_hard, env_host) == warn_no_host(), 'hard + missing host state -> warn'

        (host_dir / 'live-test.state.json').write_text(json.dumps({
            'tmux': 'live-test', 'pid': 2_000_000_000}))
        assert hook(stop_hard, env_host) == warn_no_host(), 'hard + dead host pid -> warn'

        nohost = state_dir(home) / f'{sid}.nohost'
        nohost.parent.mkdir(parents=True, exist_ok=True)
        nohost.write_text('')
        assert hook(stop_hard, env_host) == warn_no_host(), 'fresh nohost marker -> warn'
        stale = time.time() - NOHOST_TTL - 60
        os.utime(nohost, (stale, stale))
        (host_dir / 'live-test.state.json').write_text(json.dumps({
            'tmux': 'live-test', 'pid': os.getpid()}))
        assert hook(stop_hard, env_host).get('decision') == 'block', (
            'stale nohost + live host -> block')
        nohost.unlink()

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

        model_1m = 'claude-sonnet[1m]'
        soft_1m = write_transcript(
            place, 'soft_1m.jsonl',
            {'input_tokens': 350000, 'cache_read_input_tokens': 0,
             'cache_creation_input_tokens': 0},
            model=model_1m)
        hard_1m = write_transcript(
            place, 'hard_1m.jsonl',
            {'input_tokens': 410000, 'cache_read_input_tokens': 0,
             'cache_creation_input_tokens': 0},
            model=model_1m)
        sid_soft_1m = 'sess-1m-soft'
        sid_hard_1m = 'sess-1m-hard'
        env_1m = {'HOME': str(home)}
        payload_soft_1m = {
            'hook_event_name': 'UserPromptSubmit', 'session_id': sid_soft_1m,
            'transcript_path': soft_1m}
        assert hook(payload_soft_1m, env_1m).get('hookSpecificOutput', {}).get(
            'additionalContext'), '1m 350k -> soft context'
        host_1m = agent_host_dir(home)
        host_1m.mkdir(parents=True, exist_ok=True)
        (host_1m / 'live-1m-test.state.json').write_text(json.dumps({
            'tmux': 'live-1m-test', 'pid': os.getpid()}))
        env_1m_host = {
            **env_1m, 'MULTIPROMPT_TAB': 'live-1m-test',
            'PATH': f'{bin_dir}:{env.get("PATH", "")}'}
        stop_soft_1m = {
            'hook_event_name': 'Stop', 'session_id': sid_soft_1m,
            'transcript_path': soft_1m, 'stop_hook_active': False}
        assert hook(stop_soft_1m, env_1m_host) == {}, '1m 350k under hard -> no Stop block'
        stop_hard_1m = {
            'hook_event_name': 'Stop', 'session_id': sid_hard_1m,
            'transcript_path': hard_1m, 'stop_hook_active': False}
        assert hook(stop_hard_1m, env_1m_host).get('decision') == 'block', '1m 410k -> block'

        opus_150k = write_transcript(
            place, 'opus_150k.jsonl',
            {'input_tokens': 150000, 'cache_read_input_tokens': 0,
             'cache_creation_input_tokens': 0},
            model='claude-opus-5-5')
        opus_410k = write_transcript(
            place, 'opus_410k.jsonl',
            {'input_tokens': 410000, 'cache_read_input_tokens': 0,
             'cache_creation_input_tokens': 0},
            model='claude-opus-5-5')
        unknown_230k = write_transcript(
            place, 'unknown_230k.jsonl',
            {'input_tokens': 230000, 'cache_read_input_tokens': 0,
             'cache_creation_input_tokens': 0},
            model='vendor-unknown')
        haiku_150k = write_transcript(
            place, 'haiku_150k.jsonl',
            {'input_tokens': 150000, 'cache_read_input_tokens': 0,
             'cache_creation_input_tokens': 0},
            model='claude-haiku-5-5')
        env_plain = {'HOME': str(home), 'MULTIPROMPT_TAB': 'live-window-test',
                     'PATH': f'{bin_dir}:{env.get("PATH", "")}'}
        (host_dir / 'live-window-test.state.json').write_text(json.dumps({
            'tmux': 'live-window-test', 'pid': os.getpid()}))
        stop_opus_low = {
            'hook_event_name': 'Stop', 'session_id': 'sess-opus-low',
            'transcript_path': opus_150k, 'stop_hook_active': False}
        assert hook(stop_opus_low, env_plain) == {}, 'opus 5.5 at 150k -> no block'
        stop_opus_high = {
            'hook_event_name': 'Stop', 'session_id': 'sess-opus-high',
            'transcript_path': opus_410k, 'stop_hook_active': False}
        assert hook(stop_opus_high, env_plain).get('decision') == 'block', (
            'opus 5.5 at 410k -> block')
        stop_unknown = {
            'hook_event_name': 'Stop', 'session_id': 'sess-unknown',
            'transcript_path': unknown_230k, 'stop_hook_active': False}
        assert hook(stop_unknown, env_plain) == {}, 'unknown at 230k -> 1M, no block'
        stop_haiku = {
            'hook_event_name': 'Stop', 'session_id': 'sess-haiku',
            'transcript_path': haiku_150k, 'stop_hook_active': False}
        assert hook(stop_haiku, env_plain).get('decision') == 'block', (
            'haiku 5.5 at 150k -> block')

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