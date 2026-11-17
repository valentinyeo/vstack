#!/usr/bin/env python3
"""PreToolUse guard for configured project boundaries.

VSTACK_BLOCKED_PROJECT is out of bounds.
VSTACK_READ_ONLY_PROJECT permits reads and advice only.
Configure private project names in the local environment.

out-of-bounds.py --self-test
"""
import json
import os
import re
import sys

CLIENT = os.environ.get("VSTACK_READ_ONLY_PROJECT", "read-only-project")
BLOCKED_PROJECT = os.environ.get("VSTACK_BLOCKED_PROJECT", "restricted-project")
BLOCKED = re.compile(r"(?i)(?<![a-z])" + re.escape(BLOCKED_PROJECT) + r"(?![a-z])")
NAMED = re.compile(r"(?i)(?<![a-z])" + re.escape(CLIENT) + r"(?![a-z])")
READ_TOOLS = {"Read", "Grep", "Glob", "Agent", "ToolSearch", "advisor"}
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
MCP_WRITES = re.compile(r"(?i)(write|request_report_change|propose_correction|growth_bot$|create|delete|update)")
SHELL_WRITES = re.compile(
    r"(?i)(\bgit\s+(push|commit|merge|rebase|reset|tag|cherry-pick|revert|am|apply|stash)\b"
    r"|\bgh\s+(pr|issue|repo|release|secret|variable|workflow|run|label)\s+(create|merge|edit|close|reopen|delete|comment|review|rename|archive|set|run|rerun|cancel)"
    r"|\bgh\s+api\b.*\s-(X|f|F)\s|\b(rm|mv|cp|rsync|chmod|chown|truncate|ln|mkdir|touch|kill|pkill|systemctl|crontab|wrangler|terraform)\b"
    r"|\bsed\s+-i|\btee\b|\b(npm|pnpm|yarn|bun)\s+(publish|install|add|remove|run|exec)|\bcurl\b.*\s-(X|d|F|T)\b|>{1,2}\s*[^&\s]*" + re.escape(CLIENT) + r")")
MESSAGING = re.compile(r"mp_send\.py|mp-send|session-mail|" + re.escape(CLIENT) + r"-comms")
REASON_BLOCKED = "This project is out of bounds. Do not read, scan, list, change or plan work on it."
REASON_RO = ("This project is read-only for this advisor. Read it and advise its sessions. "
             "Never change it. Send advice to its session.")


def verdict(tool, tool_input):
    text = json.dumps(tool_input or {})
    if BLOCKED.search(text):
        return REASON_BLOCKED
    if not NAMED.search(text) and not tool.startswith("mcp__claude_ai_" + CLIENT):
        return None
    if tool in READ_TOOLS:
        return None
    if tool in EDIT_TOOLS:
        return REASON_RO
    if tool.startswith("mcp__"):
        return REASON_RO if MCP_WRITES.search(tool.split("__")[-1]) else None
    if tool == "Bash":
        cmd = (tool_input or {}).get("command", "")
        if MESSAGING.search(cmd):
            return None
        return REASON_RO if SHELL_WRITES.search(cmd) else None
    return REASON_RO


def self_test():
    c, b = CLIENT, BLOCKED_PROJECT
    cases = [
        ("Bash", {"command": f"ls ~/projects/{c}-dash2 && git -C ~/projects/{c}-dash2 log --oneline -5"}, None),
        ("Bash", {"command": f"cat ~/projects/{c}-rules/AGENTS.md"}, None),
        ("Bash", {"command": f"cd ~/projects/{c}-dash2 && git commit -am x"}, REASON_RO),
        ("Bash", {"command": f"gh pr merge 3 -R example/{c}-dash2"}, REASON_RO),
        ("Bash", {"command": f"echo hi > ~/projects/{c}-x/a"}, REASON_RO),
        ("Bash", {"command": f"rm -rf ~/projects/{c}-x"}, REASON_RO),
        ("Bash", {"command": f"python3 mp_send.py --to 'project advisor' 'advice about {c}'"}, None),
        ("Read", {"file_path": f"/workspace/projects/{c}-x/README.md"}, None),
        ("Edit", {"file_path": f"/workspace/projects/{c}-x/README.md"}, REASON_RO),
        ("mcp__claude_ai_" + c + "_Growth_Bot__get_ticket", {"id": 1}, None),
        ("mcp__claude_ai_" + c + "_Growth_Bot__dash_write", {"x": 1}, REASON_RO),
        ("Bash", {"command": f"ls ~/projects/{b}-worker"}, REASON_BLOCKED),
        ("Bash", {"command": "echo unrelated-project"}, None),
    ]
    bad = [(t, i) for t, i, want in cases if verdict(t, i) != want]
    print("out-of-bounds self-test ok" if not bad else f"out-of-bounds self-test FAILED {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    why = verdict(data.get("tool_name") or "", data.get("tool_input"))
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
              "permissionDecisionReason": why}}))
