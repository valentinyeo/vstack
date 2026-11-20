#!/usr/bin/env python3
"""PreToolUse guard: workers start only through plan-pick, so every chat shares one live usage pick.

A Bash command that launches a worker itself is blocked: codex exec, pi/hax/claude/cursor-agent with -p or
--print, and spawn-worker. In the 48 hours to 2026-11-20, Claude chats started 976 workers directly and 792
through plan-pick, and the direct launches drained Codex. plan-pick starts its runners as its own
subprocesses, so no hook sees them and no marker env is needed. Help and version probes pass, and so does a
command that only mentions the words, such as grep for "codex exec".

Launches are parsed with hooks/book-check.py's own launch_argv and worker_launch, so this guard and the book
check agree on what a worker launch is.

plan-pick-only.py --self-test
"""
import importlib.util
import json
from pathlib import Path
import shlex
import sys

MESSAGE = ("BLOCKED by plan-pick-only: workers start only through plan-pick, so every chat shares one live "
           "usage pick. Put the brief in brief.txt and run ~/.local/bin/plan-pick --run (reviews add "
           "--not-vendor <author vendor>). If no lane is free, plan-pick says when one frees: wait for it, "
           "never ask Valentin to pay.")
_spec = importlib.util.spec_from_file_location("book_check", Path(__file__).resolve().with_name("book-check.py"))
book = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(book)
NESTED = frozenset({"lease"})
PROBE = frozenset({"-h", "--help", "-V", "--version"})


def argv_list(cmd, depth=0):
    found = []
    for args in book.launch_argv(cmd):
        found.append(args)
        if depth < 4 and Path(args[0]).name in NESTED and "--" in args:
            tail = args[args.index("--") + 1:]
            if tail:
                found += argv_list(shlex.join(tail), depth + 1)
    return found


def verdict(cmd):
    for args in argv_list(cmd):
        if Path(args[0]).name == "plan-pick" or PROBE.intersection(args[1:]):
            continue
        if book.worker_launch(shlex.join(args)):
            return MESSAGE
    return None


def self_test():
    blocked = [
        'cd ~/projects/software-factory/advisor && nohup ~/.npm-global/bin/codex exec --skip-git-repo-check '
        '-s danger-full-access -C /home/valentin "Ticket SOFT-2446 ..."',
        'cd /tmp/cs-checks && NO_TICKET_REASON="research audit for SOFT-2747, read only" pi -p '
        '--provider opencode-go --model deepseek-v4.1-flash --thinking medium "$(cat brief.txt)"',
        'nohup codex exec -C /tmp/x "$(cat b)" &',
        'lease SOFT-12 run -- codex exec -C /tmp/x "b"',
        'claude -p "fix it"',
        'hax --print "fix it"',
        'cursor-agent -p "fix it"',
        '~/.local/bin/plan-pick --run && codex exec -C /tmp/x "$(cat b)"',
        'spawn-worker --level normal /tmp/brief.md',
        'command codex exec -C /tmp/x "b"',
    ]
    allowed = [
        '~/.local/bin/plan-pick --run',
        'plan-pick --run --not-vendor openai',
        'lease SOFT-12 run -- timeout 3600 ~/.local/bin/plan-pick --run',
        'grep -n "codex exec" file',
        'codex exec --help',
        'codex --version',
        'pi --version',
        'echo "pi -p --model x"',
        'cat notes.md',
        'git status',
    ]
    for cmd in blocked:
        assert verdict(cmd) == MESSAGE, f"blocked: {cmd}"
    for cmd in allowed:
        assert verdict(cmd) is None, f"allowed: {cmd}"
    print("plan-pick-only self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0
    why = verdict((data.get("tool_input") or {}).get("command") or "")
    if not why:
        return 0
    print(why, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
