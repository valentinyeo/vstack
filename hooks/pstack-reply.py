#!/usr/bin/env python3
"""Stop guard for the advisor: a reply that gives advice or a plan names the pstack source it follows.

Valentin, 2026-11-16: "when i chat with you you give me bad non pstack advice."
A reply that proposes, recommends, plans or fixes must carry a line `pstack: <name>` where <name> is a real
pstack playbook (Shipping, Autonomous run, Bug fix ...), principle (Attack the Premise ...) or skill.
Short replies and plain status answers pass.

pstack-reply.py --self-test
"""
import json
import re
import runpy
import sys
from pathlib import Path

PSTACK = Path.home() / ".claude/plugins/cache/cursor-plugins/pstack"
ADVICE = re.compile(r"\b(fix|fixing|i'll|i will|my pick|recommend|propose|plan|end state|should|build|building|design|lauren)\b", re.I)
SOURCE = re.compile(r"^\W*pstack:\s*(.+)$", re.I | re.M)
MIN_LEN = 300
MESSAGE = ("This reply gives advice or a plan without naming its pstack source. Check the advice against the pstack "
           "playbook or principle first (" + str(PSTACK) + "), change it if it disagrees, then end the reply with one line "
           "`pstack: <playbook or principle name>`, for example `pstack: Shipping playbook, Attack the Premise`. "
           "No pstack source covers it? Say \"my design, not pstack\" and do not build it. "
           "Your reply is already shown to the user: send ONLY the missing `pstack:` line now. Never repeat the reply.")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def inventory():
    generator = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/pstack-index"))
    root = generator["newest"]()
    return generator["render"](root) if root else generator["OUTPUT"].read_text()


def known(index=None):
    index = inventory() if index is None else index
    names = set()
    versions = list(PSTACK.glob("*"))
    root = max(versions, key=lambda v: tuple(int(x) for x in v.name.split(".") if x.isdigit())) if versions else None
    for line in index.splitlines():
        if not line.startswith(("| skill |", "| principle |", "| playbook |", "| script |")):
            continue
        parts = line.split(" | ")
        name, path = parts[1:3]
        if root and not (root / path).resolve().is_relative_to(root.resolve()):
            continue
        names.update({slug(name), slug(name.removeprefix("principle-")), slug(path)})
        if root:
            names.add(slug(str(root / path)))

    return names


# A tool plan needs its own inventory disclosure, even in a short reply.
TOOL = re.compile(r"\b(script|tool|launcher|utility|helper|watcher|automation|command|program)s?\b", re.I)
INTENT = re.compile(r"\b(build|building|write|writing|create|creating|implement|implementing|add|make|develop|design|propose|recommend|generate|craft|introduce|assemble|plan|fix order|smallest fix|need|replace|replacing|rewrite|rewriting|refactor|refactoring)\b", re.I)
HAS = re.compile(r"^\W*pstack has:\s*(.+)$", re.I | re.M)
NONE = re.compile(r"none\s*\(searched:\s*([^()]+)\)\s*$", re.I)


def tool_plan(text):
    return bool(TOOL.search(text) and INTENT.search(text))


def matches(text, index):
    words = set(re.findall(r"[a-z]{3,}", text.lower())) - {
        "pstack", "script", "scripts", "skill", "skills", "plan", "that", "this", "with", "from", "will", "have",
        "playbook", "playbooks", "principle", "principles", "the", "and", "for", "its", "one", "now", "our", "when"}
    if re.search(r"\b(merge|merges|merging)\b", text, re.I):
        words.update({"shipping", "watch"})
    rows = [line for line in index.splitlines() if line.startswith(("| skill |", "| principle |", "| playbook |", "| script |"))]
    scored = [(len(words.intersection(re.findall(r"[a-z]{3,}", line.lower()))), line) for line in rows]
    return [line for score, line in sorted(scored, key=lambda item: (-item[0], item[1])) if score]


def named(line, names):
    parts = re.split(r"[,;+]| and ", line)
    for part in parts:
        part = part.strip("` ")
        if "/" in part or part.endswith(".md"):
            name = slug(part)
        else:
            name = slug(re.sub(r"\b(playbook|principle|skill|pstack)\b", "", part, flags=re.I))
        if not name or name not in names:
            return False
    return bool(parts)


def verdict(text, names=None):
    index = inventory()
    names = known(index) if names is None else names
    if tool_plan(text):
        declarations = HAS.findall(text)
        valid = any(NONE.fullmatch(d) or (slug(d.strip("` ")) in names) for d in declarations)
        if not valid:
            lines = matches(text, index)
            return ("Before planning a new script or tool, check pstack-index.md. Add "
                    "`pstack has: <part>` or `pstack has: none (searched: <terms>)`. "
                    "Use the existing part when it covers this work. Matching index lines:\n" + "\n".join(lines))
    if len(text) < MIN_LEN or not ADVICE.search(text):
        return None
    sources = SOURCE.findall(text)
    return None if sources and all(named(m, names) for m in sources) else MESSAGE


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
    assert verdict("pstack: Orchestrate playbook", names) is None, "a lone pstack line after a block must pass"
    bad = ("Partly. Lauren's goal: a finished worker wakes its chat. The fix, building now: a real spawn-worker "
           "launcher that starts the worker, records it, and wakes the chat that started it when it ends. "
           "I'll also add a hook that blocks detached workers, and I recommend we roll it out to every chat.") * 2
    assert verdict(bad, names), "the spawn-worker advice without a source is blocked"
    assert verdict(bad + "\npstack: Attack the Premise\npstack has: Shipping", names) is None, "a real source passes"
    assert verdict(bad + "\npstack: Made Up Method", names), "a made-up source is blocked"
    assert verdict("Yes, it's in place. Tested live just now.", names) is None, "a short status passes"
    assert verdict("The command finished; I'll check the output.", names) is None
    assert verdict("x" * 400, names) is None, "long text without advice passes"
    real = (Path(__file__).resolve().parents[1] / "tests/fixtures/soft-2608/merge-plan.txt").read_text()
    why = verdict(real, names)
    assert why and "shipping.md" in why and "scripts/watch-pr" in why
    assert verdict(SOURCE.sub("pstack: Shipping", real) + "\npstack has: Shipping", names) is None
    for plan in ["I'll write a merge helper.", "We need a custom PR watcher.", "Plan: create an automation command."]:
        assert verdict(plan, names), plan
        assert verdict(plan + "\npstack has: Shipping", names) is None
        assert verdict(plan + "\npstack has: none", names)
        assert verdict(plan + "\npstack has: Made Up Shipping", names)
        assert verdict(plan + "\npstack has: none (searched: merge watcher)", names) is None
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
