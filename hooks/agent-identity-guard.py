#!/usr/bin/env python3
"""PreToolUse guard: a chat never writes to a Hypertask board as Valentin, with plain `hypertask`, the `ht`
REST helper, or the claude.ai Hypertask connector.

The chat's name is its Multibot name (chat-names.json via MULTIPROMPT_TAB), else its Claude session name.
Its board login is the agent token file named after that name. Has one: use it. Has none: get one named
exactly like the chat with /board-identity first. One name everywhere: Multibot, Claude, Hypertask.

An `ht` write that only names /mcp/agents is agent setup (its name, its board access), not a board write,
so it passes: an agent cannot change its own board access, the owner's saved login must. Each `ht` call is
judged on its own, so a chain that adds a ticket write still blocks.

agent-identity-guard.py --self-test"""
import json
import re
import sys
from pathlib import Path

SESSIONS = Path.home() / ".config/hypertask-agents/credentials/sessions"
WRITE = re.compile(
    r"(^|[;&|(\s/])hypertask\s+(--json\s+)?(task|tasks|comment|comments|page|pages|section|sections|label|labels|decision|blockers)\s+"
    r"(create|add|update|edit|move|move-board|assign|unassign|delete|archive|done|resolve|clear|set|react)\b")
HT_WRITE = re.compile(r"(^|[;&|(\s/])ht\s+(post|patch|put|delete)\b([^\n;&|)]*)", re.IGNORECASE)
PATH_LIKE = re.compile(r"^(?:https?://|/)")
AGENT_SETUP = re.compile(r"^(?:https?://[^/]+)?/mcp/agents(?:[/?#]|$)", re.IGNORECASE)
MCP_PREFIX = "mcp__claude_ai_Hypertask__"
MCP_READ_ONLY = frozenset("list get search read history whoami context count export status".split())
MCP_BLOCKED = ("BLOCKED by agent-identity-guard: the claude.ai Hypertask connector writes as Valentin. "
               "Pass input.as_agent with your own agent id, or write with the hypertask CLI and your token.")


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


def is_board_write(one_call):
    """One `ht` write (its own arguments) is a board write unless every path it names is agent setup.

    Naming no path counts as a board write: only a clearly agent-scoped call earns the exemption."""
    paths = [t.strip("'\"") for t in one_call.split()]
    paths = [t for t in paths if PATH_LIKE.match(t)]
    return not (paths and all(AGENT_SETUP.match(p) for p in paths))


def ht_board_writes(cmd):
    """Every `ht` write in the command that is a board write, so a chain cannot smuggle one through."""
    return [m.group(0) for m in HT_WRITE.finditer(cmd) if is_board_write(m.group(3))]


def mcp_verdict(tool_name, tool_input):
    if not (tool_name or "").startswith(MCP_PREFIX):
        return None
    args = tool_input if isinstance(tool_input, dict) else {}
    if str(args.get("action") or "").strip().lower() in MCP_READ_ONLY:
        return None
    inner = args.get("input")
    if isinstance(inner, dict) and inner.get("as_agent"):
        return None
    return MCP_BLOCKED


def verdict(cmd, name, has_login):
    if not (WRITE.search(cmd) or ht_board_writes(cmd)) or "HT_TOKEN=" in cmd or re.search(r"\s(--help|-h)\b", cmd):
        return None
    if not name:
        return ("BLOCKED by agent-identity-guard: this chat has no name, so this write would post as Valentin. "
                "Name the chat, run /board-identity for a login with that name, then write with its token.")
    if has_login:
        return (f"BLOCKED by agent-identity-guard: \"{name}\" has its own board login. Plain `hypertask` or `ht` "
                "writes as Valentin. Run the same command with its token (--token from your login file) instead.")
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
    assert "no name" in verdict(w, "", False), "a chat with no name never writes as Valentin"
    assert verdict('HT_TOKEN="$T" ' + w, "", False) is None, "a nameless chat with an agent token writes"
    assert verdict("HT_TOKEN=x " + w, "Poteto", False) is None
    assert verdict("ht POST /mcp/comments '{}'", "Poteto", False), "an `ht` POST must block"
    assert verdict("ht GET /mcp/tasks", "Poteto", False) is None, "an `ht` read passes"
    assert verdict("HT_TOKEN=\"$T\" ht PATCH /mcp/tasks/1 '{}'", "", False) is None, "an `ht` write with a token passes"
    assert verdict("/usr/local/bin/ht delete /mcp/x", "Poteto", False), "the full `ht` path must be caught"
    setup = 'ht PATCH /mcp/agents/abc \'{"add_project_ids":[13556]}\''
    assert verdict(setup, "Poteto", False) is None, "agent setup is not a board write"
    assert verdict(setup, "", False) is None, "agent setup passes for a nameless chat too"
    assert verdict('ht PATCH /mcp/agents/abc \'{"display_name":"X"}\'', "Poteto", False) is None, "a rename passes"
    chain = "ht PATCH /mcp/agents/1 '{}'; ht POST /mcp/comments '{}'"
    assert verdict(chain, "Poteto", False), "a chain keeps the ticket write blocked"
    assert verdict("ht PATCH /mcp/agents/1 '{}' && ht POST /mcp/comments '{}'", "Poteto", False), "&& chains too"
    assert verdict("ht PATCH /mcp/agents/x /mcp/comments", "Poteto", False), "a second board path is not exempt"
    assert verdict("ht PATCH /mcp/agentsx '{}'", "Poteto", False), "a lookalike path is not exempt"
    assert verdict("ht PATCH", "Poteto", False), "a pathless write is not exempt"
    assert verdict("h PATCH /mcp/agents/x '{}'", "Poteto", False) is None, "`h` is a skill wrapper, not `ht`"
    assert mcp_verdict(MCP_PREFIX + "hypertask_comments", {"action": "add", "input": {"body": "x"}}) == MCP_BLOCKED
    assert mcp_verdict(MCP_PREFIX + "hypertask_comments", {"action": "add", "input": {"as_agent": "u-1"}}) is None
    assert mcp_verdict(MCP_PREFIX + "hypertask_tasks", {"action": "list", "input": {}}) is None
    assert mcp_verdict("Bash", {"command": w}) is None, "a non-Hypertask tool never takes the MCP path"
    print("agent-identity-guard self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(hook, dict):
        return 0
    tool_name = hook.get("tool_name") or ""
    tool_input = hook.get("tool_input") or {}
    if tool_name.startswith(MCP_PREFIX):
        why = mcp_verdict(tool_name, tool_input)
    else:
        cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        name = multibot_name() or session_name()
        why = verdict(cmd, name, bool(name) and (SESSIONS / f"{slug(name)}-agent-token").is_file())
    if not why:
        return 0
    print(why, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
