#!/usr/bin/env python3
"""Stop guard: a reply to Valentin names the work in plain words, never a bare ticket number.

Valentin, 2026-11-22: "they must not just constantly give me IDs for tickets. SOFT-3072 means nothing to me.
am i supposed to memorize this?" valentin-mode already said "Full https:// URLs, never a server path or a
bare ticket id", in markdown only, and chats broke it all day. A ban in markdown is not a ban, so the rule
comes with a check: the reply must not show a key like ABCD-123 unless it sits inside a full https:// link.

What is ignored, because it is not a ticket named at him:
  - code blocks and inline code, where a key is part of a command
  - his own words, quoted with a leading ">"
  - anything inside a full https:// URL, which tells him where the ticket is
  - encoding and standard names such as UTF-8 and SHA-256

Declared in skills/valentin-mode/SKILL.md's frontmatter Stop hooks, so it runs in every valentin-mode chat
and nowhere else. The reply is read through skills/responsive-mode/reply-check.py's events(), the one
transcript reader, not a second copy. Fails open: any problem allows the stop.

no-bare-ids.py              hook mode, reads hook JSON on stdin
no-bare-ids.py --self-test
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

REPLY_CHECK = Path(__file__).resolve().parents[1] / "skills/responsive-mode/reply-check.py"
KEY = re.compile(r"(?<![A-Za-z0-9_/-])([A-Z]{2,6}-\d{2,6})(?![A-Za-z0-9_])")
FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
INLINE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://\S+")
# Names of encodings and standards that look like a ticket key and are not one.
NOT_A_TICKET = frozenset({"UTF-8", "UTF-16", "SHA-1", "SHA-256", "SHA-512", "ISO-8601", "AES-256",
                          "RSA-2048", "BASE-64", "HTTP-2", "IPV-6"})
MESSAGE = ("BLOCKED by no-bare-ids: your reply names ticket numbers to Valentin: {ids}.\n"
           "Name the work in plain words. If he needs the ticket, give its full https:// link.\n"
           "For example: \"the idle-stop removal: https://app.hypertask.ai/detail/project-2060/3072\"\n"
           "Drop the key from the sentence, or replace it with that full link, then send the reply again.")


def readable(reply):
    """The reply with the parts that are not a ticket named at him taken out."""
    text = FENCE.sub("", reply or "")
    kept = []
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            continue
        kept.append(INLINE.sub("", line))
    return URL.sub("", "\n".join(kept))


def bare_ids(reply):
    """Every ticket key shown outside a full link, in the order it appears, without repeats."""
    found = []
    for key in KEY.findall(readable(reply)):
        if key not in NOT_A_TICKET and key not in found:
            found.append(key)
    return found


def load_reader():
    try:
        spec = importlib.util.spec_from_file_location("reply_check", REPLY_CHECK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def reply_text(payload):
    """The chat's last assistant reply, or "" when the transcript has none to read."""
    path = payload.get("transcript_path") or ""
    reader = load_reader()
    if reader is not None and path:
        try:
            text = reader.last_reply(path)
        except Exception:
            text = ""
        if text:
            return text
    fallback = payload.get("last_assistant_message")
    return fallback if isinstance(fallback, str) else ""


def reason(payload):
    found = bare_ids(reply_text(payload))
    return MESSAGE.format(ids=", ".join(found)) if found else ""


def self_test():
    bad = []
    cases = [
        ("SOFT-3072 is first", ["SOFT-3072"], "a bare key is caught"),
        ("the idle-stop removal: https://app.hypertask.ai/detail/project-2060/3072", [],
         "a full link passes"),
        ("Run this:\n\n```\ngit log --grep SOFT-3072\n```\n\nDone.", [], "a code block is not him being told"),
        ("You wrote:\n\n> what about SOFT-3072?\n\nIt shipped.", [], "his own quoted words are not the reply"),
        ("It is `SOFT-3072` in the branch name.", [], "an inline code key passes"),
        ("VSTA-119 and SOFT-3072 both wait.", ["VSTA-119", "SOFT-3072"], "every key is named"),
        ("Read as UTF-8, then SHA-256.", [], "an encoding name is not a ticket"),
        ("The idle-stop removal is live.", [], "plain words pass"),
        ("The fix is https://app.hypertask.ai/detail/project-13556/119 for VSTA-119.", ["VSTA-119"],
         "a linked key still leaves a bare copy caught"),
    ]
    for text, want, why in cases:
        if bare_ids(text) != want:
            bad.append(f"{why}: {text!r} -> {bare_ids(text)}")
    try:
        reason({"last_assistant_message": "SOFT-3072 is first"})
    except Exception as exc:
        bad.append(f"the fallback reply field broke: {exc}")
    print("no-bare-ids self-test ok" if not bad else f"no-bare-ids self-test FAILED {bad}")
    return 1 if bad else 0


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return 0
    try:
        why = reason(payload)
    except Exception:
        return 0
    if why:
        print(json.dumps({"decision": "block", "reason": why}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
