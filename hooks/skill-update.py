#!/usr/bin/env python3
"""UserPromptSubmit hook: keep the shared skills current, and tell a chat to re-read.

Every chat reads its skills through symlinks into the shared checkout
`~/.local/share/vstack`. Job 1 moves that checkout to `origin/main` and runs its
`./install`, at most once per 10 minutes for the whole server, under an exclusive
non-blocking lock so one prompt does the work and the rest pass. A dirty checkout is
never touched. Every failure is one line in
`~/.local/state/skill-update/updates.log` and never blocks the prompt.

Job 2 keeps the sha256 of `~/.claude/skills/valentin-mode/SKILL.md` per session, keyed
by the hook input's `session_id`. The first prompt whose transcript shows
valentin-mode was loaded records the hash. A later prompt with a different hash prints
one reload notice carrying the new SKILL.md text, once, and records the new hash. A
skill over MAX_INLINE chars gets the one-line notice instead. No transcript or no
load: nothing.

This hook is registered once, globally, by `./install`, so a chat in any project hears
about a change; the repo-only registration fired only in chats whose cwd was vstack
(VSTA-207).

SKILL_UPDATE_HOME overrides the home dir. SKILL_UPDATE_NO_GIT=1 skips job 1.

skill-update.py --self-test"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

THROTTLE = 600
FETCH_TIMEOUT = 20
INSTALL_TIMEOUT = 60
SKILL = 'valentin-mode'
SKILL_REL = '.claude/skills/valentin-mode/SKILL.md'
LOADED_MARK = 'Base directory for this skill:'
# The whole skill goes into the turn, under the harness cap on hook context.
MAX_INLINE = 9000
NOTICE = ('valentin-mode changed since this chat loaded it ({old}..{new}). '
          'Re-read ~/.claude/skills/valentin-mode/SKILL.md in full now and follow '
          'the new version.')
NOTICE_WITH_TEXT = ('valentin-mode changed since this chat loaded it ({old}..{new}). '
                    'The new version is below; follow it from now on instead of the '
                    'copy you loaded.\n\n{text}')


def home_dir(env):
    return Path(env.get('SKILL_UPDATE_HOME') or env.get('HOME') or Path.home())


def state_dir(home):
    return home / '.local/state/skill-update'


def share_dir(home, env):
    return Path(env.get('VSTACK_DIR') or home / '.local/share/vstack')


def skill_file(home):
    return home / SKILL_REL


def digest(path):
    """The skill's content hash, through its symlink. None when it is unreadable."""
    try:
        return hashlib.sha256(path.resolve().read_bytes()).hexdigest()
    except OSError:
        return None


def session_record(home, session_id):
    name = hashlib.sha256(str(session_id).encode()).hexdigest()[:16] + '.json'
    return state_dir(home) / 'sessions' / name


def run(command, cwd, timeout, env=None):
    """(exit code, stdout, stderr). A missing binary or a timeout is exit code 1."""
    try:
        done = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout, check=False, env=env)
    except (OSError, subprocess.SubprocessError) as error:
        return 1, '', str(error)
    return done.returncode, done.stdout or '', done.stderr or ''


def git(args, share, timeout):
    return run(['git', *args], share, timeout)


def stamp_text(now):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now))


def log_line(home, now, text):
    log = state_dir(home) / 'updates.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log.open('a') as handle:
            handle.write(f'{stamp_text(now)} {text}\n')
    except OSError:
        pass


def failure(step, code, stderr, stdout):
    detail = (stderr or stdout or '').strip().splitlines()
    return f'{step} failed ({code})' + (f': {detail[-1]}' if detail else '')


def update_checkout(home, env, share, now):
    """Fetch, then move a clean checkout to origin/main and run its install."""
    code, _out, err = git(['fetch', '-q', 'origin', 'main'], share, FETCH_TIMEOUT)
    if code != 0:
        log_line(home, now, failure('fetch', code, err, ''))
        return
    head_code, head, _err = git(['rev-parse', 'HEAD'], share, FETCH_TIMEOUT)
    target_code, target, _err = git(['rev-parse', 'origin/main'], share, FETCH_TIMEOUT)
    head, target = head.strip(), target.strip()
    if head_code != 0 or target_code != 0 or not head or not target:
        log_line(home, now, 'rev-parse failed: cannot read HEAD or origin/main')
        return
    if head == target:
        return
    code, out, err = git(['status', '--porcelain'], share, FETCH_TIMEOUT)
    if code != 0:
        log_line(home, now, failure('status', code, err, out))
        return
    if out.strip():
        log_line(home, now, f'skip {head[:8]}..{target[:8]}: dirty tree at {share}')
        return
    code, out, err = git(['checkout', '-q', '--detach', 'origin/main'], share, FETCH_TIMEOUT)
    if code != 0:
        log_line(home, now, failure('checkout', code, err, out))
        return
    install_env = dict(env)
    install_env['HOME'] = str(home)
    code, out, err = run([str(share / 'install')], share, INSTALL_TIMEOUT, env=install_env)
    if code != 0:
        log_line(home, now, f'{head[:8]}..{target[:8]} ' +
                 failure('install', code, err, out))
        return
    log_line(home, now, f'{head[:8]}..{target[:8]} updated from {share}')


def update_shared(home, env, now):
    """Job 1, throttled and locked. Any failure is one log line, never a block."""
    if env.get('SKILL_UPDATE_NO_GIT') == '1':
        return
    state = state_dir(home)
    stamp = state / 'last-run'
    try:
        if now - float(stamp.read_text().strip()) < THROTTLE:
            return
    except (OSError, ValueError):
        pass
    try:
        state.mkdir(parents=True, exist_ok=True)
        handle = (state / 'lock').open('w')
    except OSError:
        return
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        try:
            if now - float(stamp.read_text().strip()) < THROTTLE:
                return
        except (OSError, ValueError):
            pass
        try:
            stamp.write_text(str(now))
        except OSError:
            return
        share = share_dir(home, env)
        if not (share / '.git').exists():
            log_line(home, now, f'skip: no git checkout at {share}')
            return
        try:
            update_checkout(home, env, share, now)
        except Exception as error:  # a hook never fails the prompt
            log_line(home, now, f'update crashed: {error}')


def loaded_in(transcript_path):
    """True when the transcript shows this chat read the valentin-mode skill."""
    try:
        with open(transcript_path, errors='replace') as handle:
            for line in handle:
                if LOADED_MARK in line and SKILL in line:
                    return True
    except (OSError, TypeError):
        return False
    return False


def fresh_text(home):
    """The new SKILL.md text, or None when it is unreadable or too big to inline."""
    try:
        text = skill_file(home).resolve().read_text(errors='replace')
    except OSError:
        return None
    return text if len(text) <= MAX_INLINE else None


def recorded_hash(record):
    try:
        seen = json.loads(record.read_text()).get('hash')
    except (OSError, ValueError, AttributeError):
        return None
    return seen if isinstance(seen, str) and seen else None


def note_hash(record, value):
    try:
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({'hash': value, 'at': time.time()}))
    except OSError:
        pass


def reload_notice(payload, home):
    """Job 2: the UserPromptSubmit answer that asks the chat to re-read a changed skill."""
    session_id = payload.get('session_id')
    transcript = payload.get('transcript_path')
    if not session_id or not transcript:
        return {}
    current = digest(skill_file(home))
    if current is None:
        return {}
    record = session_record(home, session_id)
    seen = recorded_hash(record)
    if seen is None:
        # One transcript scan per session, and only until its load shows up.
        if not loaded_in(transcript):
            return {}
        note_hash(record, current)
        return {}
    if seen == current:
        return {}
    note_hash(record, current)
    text = fresh_text(home)
    notice = NOTICE if text is None else NOTICE_WITH_TEXT
    return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                   'additionalContext': notice.format(old=seen[:8],
                                                                      new=current[:8],
                                                                      text=text)}}


def hook(payload, env, now=None):
    """The JSON a UserPromptSubmit hook prints for this payload and environment."""
    now = time.time() if now is None else now
    home = home_dir(env)
    update_shared(home, env, now)
    try:
        return reload_notice(payload, home)
    except Exception:  # a hook never fails the prompt
        return {}


def self_test():
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp) / 'home'
        skill = skill_file(home)
        skill.parent.mkdir(parents=True)
        skill.write_text('version one\n')
        transcript = Path(temp) / 'transcript.jsonl'
        transcript.write_text('{"content": "' + LOADED_MARK + ' /x/skills/valentin-mode"}\n')
        payload = {'session_id': 'sid-a', 'transcript_path': str(transcript)}
        assert reload_notice(payload, home) == {}, 'the first load only records the hash'
        skill.write_text('version two\n')
        answer = reload_notice(payload, home)
        text = answer['hookSpecificOutput']['additionalContext']
        assert 'valentin-mode changed since this chat loaded it' in text, \
            'the notice names the change'
        assert 'version two' in text, 'the notice carries the new skill text'
        assert reload_notice(payload, home) == {}, 'the notice fires once'
        skill.write_text('version three\n' + 'x' * MAX_INLINE)
        big = reload_notice(payload, home)['hookSpecificOutput']['additionalContext']
        assert 'Re-read ~/.claude/skills/valentin-mode/SKILL.md in full now' in big, \
            'a skill too big to inline gets the one-line instruction instead'
        skill.unlink()
        assert reload_notice(payload, home) == {}, 'an unreadable skill is silent'
        quiet = Path(temp) / 'quiet.jsonl'
        quiet.write_text('{"content": "no skill load here"}\n')
        assert reload_notice({'session_id': 'sid-b', 'transcript_path': str(quiet)}, home) == {}, \
            'a chat that never loaded valentin-mode gets nothing'
        assert not session_record(home, 'sid-b').exists(), 'nothing is recorded without a load'
        env = {'SKILL_UPDATE_HOME': str(home), 'SKILL_UPDATE_NO_GIT': '1'}
        assert hook(payload, env) == {}, 'the hook passes with git off'
        assert hook({}, env) == {}, 'a payload without a session passes'
    print('skill-update self-test ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    answer = {}
    try:
        answer = hook(payload, os.environ)
    except Exception:  # a hook never fails the prompt
        answer = {}
    if answer:
        print(json.dumps(answer))
    return 0


if __name__ == '__main__':
    sys.exit(main())
