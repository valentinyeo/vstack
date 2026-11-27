#!/usr/bin/env python3
"""Stop guard: a reply that says work is starting now must have started it in the same turn.

Valentin, 2026-11-17: "why did this happen?" The gate rewrite was announced as "next" for hours and never
launched. A reply promising work now ("starting now", "I'm fixing ... now", "building it now", "next: I ...")
passes only if this turn ran real work: a worker launch (codex exec, pi -p, cursor-agent, plan-pick --run), a
commit or push, a file write, or a cron/loop arm. Otherwise the turn is blocked once with a message to start it.

Harness-agnostic, one reader per shape. Claude Code writes `user` and `assistant` entries whose tool calls are
`Bash`, `Edit` or `Write` blocks. Antigravity writes transcript.jsonl instead: his turn is a `USER_INPUT` with
source USER_EXPLICIT, and the model's turn is a `PLANNER_RESPONSE` whose `content` is the reply and whose
`tool_calls` name `run_command`, `write_file`, `edit_file`, `invoke_subagent` or `run_workflow`. Antigravity's
`args` values may arrive JSON-encoded, so each one is decoded when it parses. Any other entry is harness noise
and is skipped; an unreadable transcript allows the turn.

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
WORK = re.compile(r"codex\s+exec|(?:^|[\s/])pi\s+(?:.*\s)?-p\b|cursor-agent|plan-pick\s+--run\b"
                  r"|git\s+commit|git\s+push|gh\s+pr\s+(create|merge)")
WORK_TOOLS = {"Edit", "Write", "CronCreate", "NotebookEdit",
              "write_file", "create_file", "edit_file", "replace_file_content",
              "multi_replace_file_content", "apply_patch", "insert_content",
              "invoke_subagent", "run_workflow"}
SHELL_TOOLS = {"Bash", "run_command"}
AGY_KINDS = {"USER_INPUT", "PLANNER_RESPONSE", "SYSTEM_MESSAGE", "GENERIC"}
COMMAND_KEYS = ("CommandLine", "command", "cmd", "command_line")
MESSAGE = ("This reply says work is starting now, but this turn started nothing: no worker launch, commit, push, "
           "file edit or loop. Start it now (launch the worker or make the change), then send one short line saying "
           "what started. If it cannot start now, send one line correcting the reply: say it is NOT started and why.")


def decoded(value):
    """Antigravity stores some args as JSON-encoded strings; decode when it parses, else keep."""
    if isinstance(value, str) and value[:1] in '{["':
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def agy_args(call):
    """One Antigravity tool call's args with its JSON-encoded values decoded, or {}."""
    args = call.get("args") if isinstance(call, dict) else None
    if not isinstance(args, dict):
        return {}
    return {key: decoded(value) for key, value in args.items()}


def shell_command(args):
    """The shell command a tool call carries, or ""."""
    for key in COMMAND_KEYS:
        value = args.get(key)
        if isinstance(value, str):
            return value
    return ""


def agy_his_turn(entry):
    return (entry.get("type") == "USER_INPUT" and entry.get("source") in (None, "USER_EXPLICIT")
            and isinstance(entry.get("content"), str) and entry["content"].strip() != ""
            and not entry["content"].lstrip().startswith(("<SYSTEM_MESSAGE", "<system-reminder",
                                                          "<ADDITIONAL_METADATA")))


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
        if not isinstance(entry, dict):
            continue
        if entry.get("type") in AGY_KINDS:
            if entry["type"] == "USER_INPUT":
                if agy_his_turn(entry):
                    break
                continue
            if entry["type"] != "PLANNER_RESPONSE":
                continue
            content = entry.get("content")
            if isinstance(content, str) and content.strip():
                text.insert(0, content)
            for call in entry.get("tool_calls") or []:
                if isinstance(call, dict):
                    tools.append((call.get("name"), shell_command(agy_args(call))))
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
        if name in WORK_TOOLS or (name in SHELL_TOOLS and WORK.search(cmd or "")):
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
    # Antigravity names its tools its own way, and stores args JSON-encoded.
    assert verdict("I'm fixing it now.", [("run_command", "git push")]) is None, "an antigravity push passes"
    assert verdict("I'm fixing it now.", [("run_command", "ls -la")]), "an antigravity read is blocked"
    assert verdict("I'm fixing it now.", [("write_file", "")]) is None, "an antigravity file write passes"
    assert verdict("I'm launching it now.", [("invoke_subagent", "")]) is None, "an antigravity subagent passes"
    assert verdict("I'm launching it now.", [("run_workflow", "")]) is None, "an antigravity workflow passes"
    assert verdict("Starting now.", [("run_command", "~/.local/bin/plan-pick --run < brief.txt")]) is None, \
        "a plan-pick launch passes"
    print("said-started self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("stop_hook_active"):
        return 0
    why = verdict(*turn(data.get("transcript_path") or ""))
    if why:
        print(json.dumps({"decision": "block", "reason": why}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
