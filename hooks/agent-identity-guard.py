#!/usr/bin/env python3
"""PreToolUse Bash guard: a chat never writes to a Hypertask board with plain `hypertask` (Valentin's login).

The chat's name is its Multibot name (chat-names.json via MULTIPROMPT_TAB), else its Claude session name.
Its board login is the agent token file named after that name. Has one: use it. Has none: get one named
exactly like the chat with /board-identity first. One name everywhere: Multibot, Claude, Hypertask.

agent-identity-guard.py --self-test"""
import json
import re
import sys
from pathlib import Path

SESSIONS = Path.home() / ".config/hypertask-agents/credentials/sessions"
WRITE = re.compile(
    r"(^|[;&|(\s/])hypertask\s+(--json\s+)?(task|tasks|comment|comments|page|pages|section|sections|label|labels|decision|blockers)\s+"
    r"(create|add|update|edit|move|move-board|assign|unassign|delete|archive|done|resolve|clear|set|react)\b")


def slug(name):
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))


def session_name():
    pid = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[1]
    pid = int(pid)
    while pid > 1:
        f = Path.home() / ".claude/sessions" / f"{pid}.json"
        if f.is_file():
            try:
                return (json.loads(f.read_text()).get("name") or "").split(" | ")[0]
            except ValueError:
                return ""
        try:
            pid = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            return ""
    return ""


def multibot_name(env=None):
    tab = (env if env is not None else __import__("os").environ).get("MULTIPROMPT_TAB")
    if not tab:
        return ""
    try:
        entry = json.loads((Path.home() / ".local/state/multiprompt/chat-names.json").read_text()).get(tab) or {}
    except (OSError, ValueError):
        return ""
    return entry.get("name") or ""


def verdict(cmd, name, has_login):
    if not WRITE.search(cmd) or "HT_TOKEN=" in cmd or re.search(r"\s(--help|-h)\b", cmd) or not name:
        return None
    if has_login:
        return (f"BLOCKED by agent-identity-guard: \"{name}\" has its own board login. Plain `hypertask` writes as "
                "Valentin. Run the same command with its token (--token from your login file) instead.")
    return (f"BLOCKED by agent-identity-guard: \"{name}\" has no board login, so this write would post as Valentin. "
            f"Run /board-identity first and name the login exactly \"{name}\", then link it with "
            f"`mp-agent-sync link --tmux $MULTIPROMPT_TAB --id <agent id>`. Then write with its token.")


def self_test():
    w = "hypertask task create --project 2060 --title x"
    assert verdict(w, "Poteto", False) and "board-identity" in verdict(w, "Poteto", False), "no login must block"
    assert "own board login" in verdict(w, "HT Finance", True), "own login must use its token"
    assert verdict("hypertask task list --project 2060", "Poteto", False) is None, "reads pass"
    assert verdict("~/.local/bin/hypertask " + w[10:], "Poteto", False), "the full CLI path must be caught"
    assert verdict('hypertask --token "$T" ' + w[10:], "Poteto", False) is None, "a write with its own token passes"
    assert verdict(w, "", False) is None, "a script with no chat name passes"
    assert verdict("HT_TOKEN=x " + w, "Poteto", False) is None
    print("agent-identity-guard self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    try:
        cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except ValueError:
        return 0
    name = multibot_name() or session_name()
    why = verdict(cmd, name, bool(name) and (SESSIONS / f"{slug(name)}-agent-token").is_file()) if name else None
    if not why:
        return 0
    print(why, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
