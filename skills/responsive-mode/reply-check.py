#!/usr/bin/env python3
"""PreToolUse guard: no tool step until Valentin's newest message has a reply.

Valentin, 2026-11-20: "the chat ignores his new messages while it keeps working". A chat that loaded
responsive-mode answers him first, then carries on. This hook holds the next tool call of a message that got
no assistant text after it.

Read from a real transcript (2.1.329), two shapes:
  - He types while the chat is idle: a user entry whose message.content holds the typed text.
  - He types mid-turn: an attachment entry with attachment.type "queued_command" and the text in
    attachment.prompt. Claude Code writes it where the next tool result lands, so file order is the order.
An assistant text block and a tool_use are separate entries, text first, so a reply written just before a tool
call counts. Tool results, isMeta entries, task notifications and skill body expansions are not him talking.

Fails open: a missing or unreadable transcript, or any shape this file does not know, allows the call.

reply-check.py --self-test
"""
import json
import os
import re
import sys
import time
from pathlib import Path

MESSAGE = ("Valentin's newest message has no reply yet. Answer it directly, then continue the work. "
           "No separate acknowledgment.")
SKIP = ("<task-notification", "<system-reminder", "<teammate-message", "<cross-session",
        "[SYSTEM NOTIFICATION", "[Message from", "[Cross-session", "[from ",
        "Cross-session message", "Message from session", "Message from chat", "Base directory for this skill")
SILENCE_REMINDER = re.compile(r"^The user (?:hasn['’]t|has not) heard from you\b", re.I)
SLASH = re.compile(r"<command-name>/\S+</command-name>")
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
QUEUED = "queued_command"


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
        if kind == "attachment":
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

    cases = [
        ([human("ship it"), call()], True, "an unanswered message holds the tool call"),
        ([human("ship it"), say("On it."), call()], False, "a reply before the tool call passes"),
        ([human("ship it"), call(), result(), queued("is it reliable?"), call()], True,
         "a message sent mid-turn is held"),
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
        if unanswered(timeline(write(entries))) != want:
            bad.append(why)
    for entries, want, why in replies:
        if last_reply(write(entries)) != want:
            bad.append(why)
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
    try:
        if unanswered_after_retries(data.get("transcript_path") or ""):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                    "additionalContext": MESSAGE}}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
