#!/usr/bin/env python3
"""PreToolUse and Stop reminder: answer Valentin's newest message, and never hand him a merge.

Valentin, 2026-11-20: "the chat ignores his new messages while it keeps working". A chat that loaded
responsive-mode answers him first, then carries on. This hook reminds the chat at each tool call when his
newest message has no assistant text after it.

Valentin, 2026-11-23 (VSTA-158): a chat held a finished, green multiprompt-android PR #524 waiting for his
"ship" yes. At Stop the same hook reads the final reply with the same transcript reader, and when the reply
asks him to merge, ship, approve or review a PR it adds the fix as context. It never denies a tool call and
never blocks the turn (VSTA-155). The matcher and the fix line live in one owner, hypertask-work/merge-ask.

Read from a real transcript (2.1.329), two shapes:
  - He types while the chat is idle: a user entry whose message.content holds the typed text.
  - He types mid-turn: an attachment entry with attachment.type "queued_command" and the text in
    attachment.prompt. Claude Code writes it where the next tool result lands, so file order is the order.
An assistant text block and a tool_use are separate entries, text first, so a reply written just before a tool
call counts. Tool results, isMeta entries, task notifications and skill body expansions are not him talking.

Harness-agnostic: Antigravity writes transcript.jsonl instead, one decided step per line, and the same events
come out of it. His message is a USER_INPUT whose source is USER_EXPLICIT, wrapped in <USER_REQUEST> with
<ADDITIONAL_METADATA> after it; only the request body is his words, and a <SYSTEM_MESSAGE> entry is the
harness. The model's reply is a PLANNER_RESPONSE with content, and its tool_calls ride on that same entry.
Any other type is harness bookkeeping. Both shapes are read per entry, so a mixed or unknown file fails open.

Fails open: a missing or unreadable transcript, or any shape this file does not know, allows the call.

reply-check.py --self-test
"""
import json
import importlib.machinery
import importlib.util
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MERGE_ASK = ROOT / 'skills' / 'hypertask-work' / 'merge-ask'


def merge_ask_module():
    """The one owner of the merge-ask matcher, shared with the board drain."""
    name = 'merge_ask'
    module = sys.modules.get(name)
    if module is not None and getattr(module, '__file__', None) == str(MERGE_ASK):
        return module
    loader = importlib.machinery.SourceFileLoader(name, str(MERGE_ASK))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


merge_ask = merge_ask_module()

MESSAGE = ("Valentin's newest message has no reply yet. Answer it directly, then continue the work. "
           "No separate acknowledgment.")
MERGE_MESSAGE = ("This reply asks Valentin to merge, ship, approve or review a pull request. The fix: "
                 + merge_ask.FIX + ". Carry it through babysit until it is green and mergeable, merge it, "
                 "prove it live on the real case, then report that. Ask him only a product question.")
SKIP = ("<task-notification", "<system-reminder", "<teammate-message", "<cross-session",
        "<SYSTEM_MESSAGE", "<ADDITIONAL_METADATA",
        "[SYSTEM NOTIFICATION", "[Message from", "[Cross-session", "[from ",
        "Cross-session message", "Message from session", "Message from chat", "Base directory for this skill")
SILENCE_REMINDER = re.compile(r"^The user (?:hasn['’]t|has not) heard from you\b", re.I)
SLASH = re.compile(r"<command-name>/\S+</command-name>")
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
QUEUED = "queued_command"
AGY_USER = "USER_INPUT"
AGY_MODEL = "PLANNER_RESPONSE"
AGY_SOURCES = (None, "USER_EXPLICIT")
AGY_MODEL_SOURCES = (None, "MODEL")
USER_REQUEST = re.compile(r"<USER_REQUEST>(.*?)</USER_REQUEST>", re.S)


def blocks(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def typed(text):
    """Is this text something Valentin typed himself, rather than the harness talking?"""
    text = (text or "").strip()
    if not text or text.startswith(SKIP) or SILENCE_REMINDER.search(text):
        return False
    if SLASH.search(text):
        args = COMMAND_ARGS.search(text)
        return bool(args and args.group(1).strip())
    return True


def text_of(content):
    return "".join(block.get("text") or "" for block in blocks(content) if block.get("type") == "text")


def agy_his_words(entry):
    """Valentin's words from one Antigravity USER_INPUT, or "" when the entry is not him."""
    if entry.get("source") not in AGY_SOURCES:
        return ""
    content = entry.get("content")
    if not isinstance(content, str):
        return ""
    found = USER_REQUEST.search(content)
    return (found.group(1) if found else content).strip()


def agy_reply_text(entry):
    """The model's words from one Antigravity PLANNER_RESPONSE, or ""."""
    if entry.get("source") not in AGY_MODEL_SOURCES:
        return ""
    content = entry.get("content")
    return content if isinstance(content, str) else ""


def events(transcript):
    """One event per entry, in file order: ("human", his text) or ("reply", assistant text).

    The one reader of a transcript in this repo. Every stop or tool guard builds on it.
    """
    try:
        lines = Path(transcript).read_text(errors="ignore").splitlines()[-2000:]
    except (OSError, TypeError):
        return
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        if kind == AGY_USER:
            text = agy_his_words(entry)
            if typed(text):
                yield "human", text
        elif kind == AGY_MODEL:
            text = agy_reply_text(entry)
            if text.strip():
                yield "reply", text
        elif kind == "attachment":
            attachment = entry.get("attachment")
            if not isinstance(attachment, dict) or attachment.get("type") != QUEUED:
                continue
            text = text_of(attachment.get("prompt"))
            if not entry.get("isMeta") and typed(text):
                yield "human", text
        elif kind == "user":
            if entry.get("isMeta"):
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            text = text_of(content)
            if typed(text):
                yield "human", text
        elif kind == "assistant":
            if entry.get("isSidechain"):
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            text = text_of(content)
            if text.strip():
                yield "reply", text


def timeline(transcript):
    """One mark per event, in file order: "human" for his message, "reply" for assistant text."""
    return [kind for kind, _ in events(transcript)]


def last_reply(transcript):
    """The newest assistant text in the transcript, read through events, or ""."""
    text = ""
    for kind, entry_text in events(transcript):
        if kind == "reply":
            text = entry_text
    return text


def unanswered(marks):
    """True when his newest message has no assistant text after it."""
    if "human" not in marks:
        return False
    last = len(marks) - 1 - marks[::-1].index("human")
    return "reply" not in marks[last + 1:]


def _retry_count():
    try:
        return max(1, int(os.environ.get("REPLY_CHECK_RETRIES", "8")))
    except ValueError:
        return 8


def _retry_delay_sec():
    try:
        return max(0, int(os.environ.get("REPLY_CHECK_DELAY_MS", "250"))) / 1000.0
    except ValueError:
        return 0.25


def unanswered_after_retries(transcript_path):
    """True when his newest message still has no reply after re-reading the transcript."""
    path = transcript_path or ""
    delay = _retry_delay_sec()
    for attempt in range(_retry_count()):
        if not unanswered(timeline(path)):
            return False
        if attempt + 1 < _retry_count():
            time.sleep(delay)
    return True


def self_test():
    import subprocess
    import tempfile

    def write(entries):
        path = Path(tempfile.mkdtemp()) / "transcript.jsonl"
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
        return str(path)

    def human(text):
        return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}

    def say(text):
        return {"type": "assistant", "isSidechain": False,
                "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}

    def call():
        return {"type": "assistant", "isSidechain": False,
                "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Bash",
                                                              "input": {"command": "ls"}}]}}

    def result():
        return {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}

    def queued(text):
        return {"type": "attachment", "attachment": {"type": "queued_command",
                                                     "prompt": [{"type": "text", "text": text}]}}

    def meta(text):
        return {"type": "user", "isMeta": True, "turnCompanion": True,
                "message": {"role": "user", "content": [{"type": "text", "text": text}]}}

    def agy_human(text):
        return {"type": "USER_INPUT", "source": "USER_EXPLICIT", "status": "DONE",
                "content": "<USER_REQUEST>\n" + text + "\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\n"
                           "The current local time is: 2026-11-26T15:39:46+01:00.\n</ADDITIONAL_METADATA>"}

    def agy_say(text, calls=None):
        entry = {"type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE", "content": text}
        if calls:
            entry["tool_calls"] = calls
        return entry

    def agy_run():
        return {"name": "run_command", "args": {"CommandLine": json.dumps("ls")}}

    def agy_system():
        return {"type": "SYSTEM_MESSAGE", "source": "SYSTEM", "status": "DONE",
                "content": "<SYSTEM_MESSAGE>\nReminder: work efficiently.\n</SYSTEM_MESSAGE>"}

    cases = [
        ([agy_human("ship it"), agy_say("", [agy_run()])], True,
         "an antigravity request gets a reminder without a deny"),
        ([agy_human("ship it"), agy_say("On it.", [agy_run()])], False,
         "an antigravity reply before the tool call passes"),
        ([agy_human("ship it"), agy_system(), agy_say("", [agy_run()])], True,
         "an antigravity system message does not answer him"),
        ([human("ship it"), call()], True, "an unanswered message gets a reminder without a deny"),
        ([human("ship it"), say("On it."), call()], False, "a reply before the tool call passes"),
        ([human("ship it"), call(), result(), queued("is it reliable?"), call()], True,
         "a message sent mid-turn gets a reminder without a deny"),
        ([human("ship it"), call(), result(), queued("is it reliable?"), say("Yes."), call()], False,
         "a reply to the mid-turn message passes"),
        ([human("a"), say("ok"), meta("<task-notification>\n<task-id>x</task-id>"), call()], False,
         "a task notification is not him"),
        ([human("a"), say("ok"), result(), call()], False, "a tool result is not him"),
        ([human("a"), say("ok"), meta("Base directory for this skill: /x\n\n# Skill"), call()], False,
         "a skill body is not him"),
        ([human("a"), meta("<system-reminder>noted</system-reminder>"), call()], True,
         "a system reminder does not answer him"),
        ([human("<command-name>/responsive-mode</command-name><command-args>be fast</command-args>"), call()],
         True, "a slash command with args is him"),
        ([human("<command-name>/responsive-mode</command-name>"), call()], False,
         "a slash command without args is not a message"),
        ([], False, "an empty transcript allows"),
    ]
    replies = [
        ([human("a"), say("first"), say("second")], "second", "the newest reply wins"),
        ([human("a"), call(), result()], "", "a turn without text has no reply"),
    ]
    bad = []
    for entries, want, why in cases:
        transcript = write(entries)
        if unanswered(timeline(transcript)) != want:
            bad.append(why)
        result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                                input=json.dumps({"transcript_path": transcript}), text=True,
                                capture_output=True, timeout=10,
                                env=dict(os.environ, REPLY_CHECK_RETRIES="1"))
        expected = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": MESSAGE}}
        output = json.loads(result.stdout) if result.stdout.strip() else None
        if result.returncode or result.stderr or output != (expected if want else None):
            bad.append("hook output: " + why)
    for entries, want, why in replies:
        if last_reply(write(entries)) != want:
            bad.append(why)
    stop_cases = [
        ([human("do it"), say("Ready for your review: "
                               "https://github.com/valentinyeo/multiprompt-android/pull/524")], True,
         "a final reply that hands him the PR reminds"),
        ([human("do it"), say("Say ship and I'll merge the green change.")], True,
         "a final reply that asks for his ship reminds"),
        ([human("do it"), say("Should the button be blue or green?")], False,
         "a product question passes"),
        ([human("do it"), say("Merged PR #524 and proved it live.")], False,
         "a finished merge report passes"),
    ]
    for entries, want, why in stop_cases:
        transcript = write(entries)
        result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                                input=json.dumps({"hook_event_name": "Stop",
                                                  "transcript_path": transcript}),
                                text=True, capture_output=True, timeout=10)
        expected = {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": MERGE_MESSAGE}}
        output = json.loads(result.stdout) if result.stdout.strip() else None
        if result.returncode or result.stderr or output != (expected if want else None):
            bad.append("stop output: " + why)
    if unanswered("/nonexistent/transcript.jsonl"):
        bad.append("a missing transcript allows")
    if last_reply("/nonexistent/transcript.jsonl"):
        bad.append("a missing transcript has no reply")
    print("reply-check self-test ok" if not bad else f"reply-check self-test FAILED {bad}")
    return 1 if bad else 0


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    if data.get("stop_hook_active"):
        return 0
    transcript = data.get("transcript_path") or ""
    event = str(data.get("hook_event_name") or data.get("hook_name") or "")
    if event.strip().casefold() == "stop":
        try:
            if merge_ask.asks(last_reply(transcript)):
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop",
                                                         "additionalContext": MERGE_MESSAGE}}))
        except Exception:
            return 0
        return 0
    try:
        if unanswered_after_retries(transcript):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                    "additionalContext": MESSAGE}}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
