#!/usr/bin/env python3
"""Stop guard: a reply that says work is starting now must have started it in the same turn.

Valentin, 2026-11-17: "why did this happen?" The gate rewrite was announced as "next" for hours and never
launched. A reply promising work now ("starting now", "I'm fixing ... now", "building it now", "next: I ...")
passes only if this turn ran real work: a worker launch (codex exec, pi -p, cursor-agent), a commit or push,
a file Edit/Write, or a cron/loop arm. Otherwise the turn is blocked once with a message to start it.

said-started.py --self-test
"""
import json
import re
import sys
from pathlib import Path

PROMISE = re.compile(
    r"\b(starting (it |this |that )?now|(i'm|i am) (building|fixing|starting|doing|running|launching)\b[^.\n]{0,80}\bnow"
    r"|(building|fixing|doing|running|launching) (it|this|that|them|number \d+) now"
    r"|next,? i('ll| will)\b|i('ll| will) (start|build|fix|do|run|launch)\b[^.\n]{0,60}\b(now|next))", re.I)
WORK = re.compile(r"codex\s+exec|(?:^|[\s/])pi\s+(?:.*\s)?-p\b|cursor-agent|git\s+commit|git\s+push|gh\s+pr\s+(create|merge)")
WORK_TOOLS = {"Edit", "Write", "CronCreate", "NotebookEdit"}
MESSAGE = ("This reply says work is starting now, but this turn started nothing: no worker launch, commit, push, "
           "file edit or loop. Start it now (launch the worker or make the change), then send one short line saying "
           "what started. If it cannot start now, send one line correcting the reply: say it is NOT started and why.")


def turn(transcript):
    text, tools = [], []
    try:
        lines = Path(transcript).read_text(errors="ignore").splitlines()[-600:]
    except OSError:
        return "", []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        msg = entry.get("message")
        if entry.get("type") == "user" and isinstance(msg, dict) and isinstance(msg.get("content"), str):
            break
        if entry.get("type") == "assistant" and isinstance(msg, dict):
            for c in msg.get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text":
                    text.insert(0, c.get("text", ""))
                elif c.get("type") == "tool_use":
                    tools.append((c.get("name"), (c.get("input") or {}).get("command", "")))
    return "\n".join(text), tools


def verdict(text, tools):
    if not PROMISE.search(text):
        return None
    for name, cmd in tools:
        if name in WORK_TOOLS or (name == "Bash" and WORK.search(cmd or "")):
            return None
    return MESSAGE


def self_test():
    # Real past mistake, 2026-11-17: "Next: a worker rewrites the gate" with no launch, for hours.
    assert verdict("Next, I'll have a worker rewrite the gate.", []), "promise with no work is blocked"
    assert verdict("I'm fixing number 1 now, it is under 10 minutes.", [("Bash", "ls")]), "a read-only turn is blocked"
    assert verdict("Starting now.", [("Bash", "nohup codex exec -C /tmp/x \"$(cat b)\" &")]) is None, "a worker launch passes"
    assert verdict("I'm building it now.", [("Write", "")]) is None, "a file write passes"
    assert verdict("Building it now.", [("Bash", "git commit -m x && git push")]) is None, "a commit passes"
    assert verdict("The gate is a draft. Live on no repo.", []) is None, "plain status passes"
    print("said-started self-test ok")


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
    why = verdict(*turn(data.get("transcript_path") or ""))
    if why:
        print(json.dumps({"decision": "block", "reason": why}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
