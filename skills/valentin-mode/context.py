#!/usr/bin/env python3
"""PreToolUse hook: put responsive mode's rules in the chat, and hold the tool call until he has a reply.

Valentin, 2026-11-22: a test chat loaded valentin mode and skipped nothing, yet the rules arrived only as the
result of a shell line the chat chose to run, so a chat that skips the line never gets them. Claude Code does
not expand a `!`...`` line in a SKILL.md, so the line is text the model may run or ignore. A PreToolUse hook
can hand text straight to the model instead: on 2.1.330 the context arrives even beside a deny, and the debug
log records it. This hook sends the version line and responsive mode's body once per chat, at its first tool
call, then nothing for later calls. Claude Code registers only one command per hook event from a skill's
frontmatter, so this hook also runs responsive mode's reply guard, reply-check.py, on every call.

State goes in $HOME/.local/state/valentin-mode-context/<session>.injected, or a hash of the transcript path
when the hook input carries no session id. Fails open: any problem prints `{}`.

context.py --self-test
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESPONSIVE = HERE.parent / 'responsive-mode' / 'SKILL.md'
REPLY_CHECK = HERE.parent / 'responsive-mode' / 'reply-check.py'
VERSION = HERE / 'version.sh'


def state_dir(home):
    return Path(home) / '.local' / 'state' / 'valentin-mode-context'


def session_key(payload):
    session = payload.get('session_id')
    if isinstance(session, str) and session.strip():
        return session.strip()
    transcript = payload.get('transcript_path')
    if isinstance(transcript, str) and transcript.strip():
        return hashlib.sha256(transcript.encode()).hexdigest()[:32]
    return 'unknown'


def already_sent(home, key):
    return (state_dir(home) / (key + '.injected')).is_file()


def mark_sent(home, key):
    path = state_dir(home) / (key + '.injected')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('1')
    except OSError:
        pass


def body_after_frontmatter(text):
    """Every line after the second `---`, the same slice the skill used to print with awk."""
    kept, fences = [], 0
    for line in text.splitlines():
        if fences >= 2:
            kept.append(line)
        if line == '---':
            fences += 1
    return '\n'.join(kept).strip()


def version_line():
    try:
        done = subprocess.run(['sh', str(VERSION)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ''
    return done.stdout.strip().splitlines()[0] if done.stdout.strip() else ''


def reply_check():
    """responsive mode's reply guard, loaded from beside this file, or None."""
    try:
        spec = importlib.util.spec_from_file_location('reply_check', REPLY_CHECK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def must_reply(transcript):
    """True when responsive mode would hold this tool call for a missing reply."""
    guard = reply_check()
    if guard is None:
        return False
    try:
        return bool(guard.unanswered_after_retries(transcript or ''))
    except Exception:
        return False


def payload_context():
    try:
        text = RESPONSIVE.read_text(errors='replace')
    except OSError:
        return ''
    body = body_after_frontmatter(text)
    if not body:
        return ''
    version = version_line()
    lead = version + '\n\n' if version else ''
    return (lead + 'Responsive mode is loaded for this chat. These are its rules, injected by a hook so they '
            'arrive whether or not you run a command first.\n\n' + body)


def answer(payload, home=None):
    """One PreToolUse answer: the rules once, and responsive mode's reply deny every call."""
    home = home or os.path.expanduser('~')
    key = session_key(payload)
    output = {}
    if must_reply(payload.get('transcript_path')):
        guard = reply_check()
        output = {'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': guard.MESSAGE}}
    if already_sent(home, key):
        return output
    context = payload_context()
    if not context:
        return output
    mark_sent(home, key)
    output.setdefault('hookSpecificOutput', {'hookEventName': 'PreToolUse'})
    output['hookSpecificOutput']['additionalContext'] = context
    return output


def self_test():
    bad = []
    sample = HERE.parent / 'responsive-mode' / 'SKILL.md'
    whole = sample.read_text(errors='replace') if sample.is_file() else ''
    last = 'the push lands on the remote with no nudge.'
    with tempfile.TemporaryDirectory() as home:
        previous = os.environ.get('HOME')
        os.environ['HOME'] = home
        try:
            first = answer({'session_id': 'abc'})
            context = first.get('hookSpecificOutput', {}).get('additionalContext', '')
            if last not in whole:
                bad.append('the sample skill lost its last sentence')
            if last not in context:
                bad.append('the first tool call carries the whole body')
            if 'valentin-mode v' not in context:
                bad.append('the first tool call carries the version line')
            if answer({'session_id': 'abc'}).get('hookSpecificOutput'):
                bad.append('the second tool call carries nothing')
            if not (state_dir(home) / 'abc.injected').is_file():
                bad.append('a sent chat leaves its marker')
            if 'additionalContext' not in answer({'session_id': 'other'}).get('hookSpecificOutput', {}):
                bad.append('another chat still gets its rules')
        finally:
            if previous is None:
                os.environ.pop('HOME', None)
            else:
                os.environ['HOME'] = previous
        sliced = body_after_frontmatter('---\nname: x\n---\n\n# Title\ntext\n')
        if sliced != '# Title\ntext':
            bad.append('the body starts after the second fence, got %r' % sliced)
        if body_after_frontmatter('no fences') != '':
            bad.append('a text without fences has no body')
    if not (HERE.parent / 'responsive-mode' / 'SKILL.md').is_file():
        bad.append('the sample skill is beside this hook')
    if reply_check() is None:
        bad.append('the reply guard loads from beside this hook')
    print('context self-test ok' if not bad else 'context self-test FAILED %s' % bad)
    return 1 if bad else 0


def main():
    if sys.argv[1:] == ['--self-test']:
        return self_test()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    try:
        print(json.dumps(answer(data)))
    except Exception:
        return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
