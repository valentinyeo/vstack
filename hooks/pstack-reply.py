#!/usr/bin/env python3
"""Stop guard for the advisor: a reply that gives advice or a plan names the pstack source it follows.

Valentin, 2026-11-16: "when i chat with you you give me bad non pstack advice."
A reply that proposes, recommends, plans or fixes must carry a line `pstack: <name>` where <name> is a real
pstack playbook (Autonomous run, Bug fix ...), principle (Attack the Premise ...) or skill (figure-it-out ...).
Short replies and plain status answers pass.

pstack-reply.py --self-test
"""
import json
import re
import sys
from pathlib import Path

PSTACK = Path.home() / ".claude/plugins/cache/cursor-plugins/pstack"
ADVICE = re.compile(r"\b(fix|fixing|i'll|i will|my pick|recommend|propose|plan|end state|should|build|building|design|lauren)\b", re.I)
SOURCE = re.compile(r"^\W*pstack:\s*(.+)$", re.I | re.M)
MIN_LEN = 300
MESSAGE = ("This reply gives advice or a plan without naming its pstack source. Check the advice against the pstack "
           "playbook or principle first (" + str(PSTACK) + "), change it if it disagrees, then end the reply with one line "
           "`pstack: <playbook or principle name>`, for example `pstack: Autonomous run playbook, Attack the Premise`. "
           "No pstack source covers it? Say \"my design, not pstack\" and do not build it. "
           "Your reply is already shown to the user: send ONLY the missing `pstack:` line now. Never repeat the reply.")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def known():
    names = set()
    versions = list(PSTACK.glob("*"))
    if not versions:
        return names
    newest = max(versions, key=lambda v: tuple(int(x) for x in v.name.split(".") if x.isdigit()))
    for skill in newest.glob("skills/*"):
        names.add(skill.name)
        names.add(skill.name.removeprefix("principle-"))
    for book in newest.glob("skills/poteto-mode/playbooks/*.md"):
        names.add(book.stem)
    return names


def named(line, names):
    parts = re.split(r"[,;/+]| and ", line)
    for part in parts:
        s = slug(re.sub(r"\b(playbook|principle|skill|pstack)\b", "", part, flags=re.I))
        if s and (s in names or any(n in s for n in names if len(n) > 5)):
            return True
    return False


def verdict(text, names=None):
    names = known() if names is None else names
    if len(text) < MIN_LEN or not ADVICE.search(text):
        return None
    return None if any(named(m, names) for m in SOURCE.findall(text)) else MESSAGE


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
            if parts:
                text = "\n".join(parts) + "\n" + text
    return text


def self_test():
    names = known()
    assert verdict("pstack: Autonomous run playbook", names) is None, "a lone pstack line after a block must pass"
    bad = ("Partly. Lauren's goal: a finished worker wakes its chat. The fix, building now: a real spawn-worker "
           "launcher that starts the worker, records it, and wakes the chat that started it when it ends. "
           "I'll also add a hook that blocks detached workers, and I recommend we roll it out to every chat.") * 2
    assert verdict(bad, names), "the spawn-worker advice without a source is blocked"
    assert verdict(bad + "\npstack: Autonomous run playbook, Attack the Premise", names) is None, "a real source passes"
    assert verdict(bad + "\npstack: Made Up Method", names), "a made-up source is blocked"
    assert verdict("Yes, it's in place. Tested live just now.", names) is None, "a short status passes"
    assert verdict("x" * 400, names) is None, "long text without advice passes"
    print("pstack-reply self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    if data.get("stop_hook_active"):
        print("{}")
        return 0
    why = verdict(last_reply(data.get("transcript_path") or ""))
    print(json.dumps({"decision": "block", "reason": why}) if why else "{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
