#!/usr/bin/env python3
"""Does this hook input come from a Claude Code subagent?

PreToolUse and PostToolUse from a subagent carry agent_id and often agent_type; the subagent's own
transcript lives under a subagents/ directory. The parent session's transcript_path is unchanged, so
valentin-mode lanes that key off transcript_path alone still need this check.

subagent_call.py --self-test
"""
import sys


def from_hook(payload):
    if not isinstance(payload, dict):
        return False
    agent_id = payload.get("agent_id")
    if isinstance(agent_id, str) and agent_id.strip():
        return True
    path = payload.get("transcript_path")
    if isinstance(path, str):
        return "/subagents/" in path.replace("\\", "/")
    return False


def self_test():
    heavy = {
        "tool_name": "Bash",
        "tool_input": {"command": "python3 -m unittest discover -s tests"},
    }
    assert not from_hook(heavy), "main chat has no agent fields"
    assert not from_hook({}), "empty payload is main chat"
    assert not from_hook(None), "non-dict is main chat"
    agent_id = {**heavy, "agent_id": "a4d2c8f1e0b3a297", "agent_type": "general-purpose"}
    assert from_hook(agent_id), "agent_id marks a subagent"
    nested = {**heavy, "transcript_path": "/home/u/.claude/projects/p/s/subagents/agent-def456.jsonl"}
    assert from_hook(nested), "subagents/ transcript marks a subagent"
    parent = {**heavy, "transcript_path": "/home/u/.claude/projects/p/s/transcript.jsonl"}
    assert not from_hook(parent), "parent transcript alone is main chat"
    blank = {**heavy, "agent_id": "  "}
    assert not from_hook(blank), "blank agent_id is main chat"
    print("subagent-call self-test ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        sys.exit(0)
    sys.exit(0 if from_hook(__import__("json").load(sys.stdin)) else 1)