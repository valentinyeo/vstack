#!/usr/bin/env python3
"""Stop guard: GitHub billing is Valentin's; a chat never raises it with him.

House rules line: "github billing is valentin's. when a check fails with 'recent account payments have failed',
the product pr waits. never verify it on this server or merge around the check. say it once on the ticket, then
build the next unit." Valentin, 2026-11-17: "we fixed this sooooo many times". Poteto still asked him in chat.

billing-quiet.py --self-test
"""
import json
import re
import sys
from pathlib import Path

BILLING = re.compile(r"payments have failed|spending limit|github billing|billing (problem|failure|issue)|fix the (github )?billing", re.I)
MESSAGE = ("GitHub billing is Valentin's (house rules). Do not raise it in chat. Log it once on the ticket's agent log, "
           "let that PR wait, and build the next unit. Send one line restating the reply without the billing part.")


def last_reply(transcript):
    text = ""
    try:
        lines = Path(transcript).read_text(errors="ignore").splitlines()[-400:]
    except OSError:
        return text
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        msg = entry.get("message")
        if entry.get("type") == "user" and isinstance(msg, dict) and isinstance(msg.get("content"), str):
            break
        if entry.get("type") == "assistant" and isinstance(msg, dict):
            parts = [c.get("text", "") for c in msg.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"]
            text = "\n".join(parts) + "\n" + text
    return text


def verdict(text):
    return MESSAGE if BILLING.search(text) else None


def self_test():
    # Real past mistake, 2026-11-17.
    assert verdict('Question: GitHub won\'t run checks, saying "recent account payments have failed or your spending '
                   'limit needs to be increased". Fix the GitHub billing? My pick: yes.'), "today's billing question is blocked"
    assert verdict("Runners: 9 now. The gate PR waits on CI.") is None, "plain status passes"
    print("billing-quiet self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("stop_hook_active"):
        return 0
    why = verdict(last_reply(data.get("transcript_path") or ""))
    if why:
        print(json.dumps({"decision": "block", "reason": why}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
