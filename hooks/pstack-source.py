#!/usr/bin/env python3
"""PreToolUse guard for the advisor: every worker brief and PR names the pstack source it follows.

A worker launch (codex exec, pi -p, cursor-agent -p) or `gh pr create` from this project must carry a line
`pstack: <path>` in the brief file or command, and the path must be a real file under the installed pstack plugin
(a playbook, a principle skill, or another pstack skill). Verifiers and reviewers prefixed with
NO_TICKET_REASON= are exempt: they check work, they do not design it.

pstack-source.py --self-test
"""
import json
import re
import sys
from pathlib import Path

PSTACK = Path.home() / ".claude/plugins/cache/cursor-plugins/pstack"
LAUNCH = re.compile(r"(?:^|[\s;&|(])(?:\S*/)?(?:codex\s+exec\b|pi\s+(?:.*\s)?-p\b|cursor-agent\s+(?:.*\s)?-p\b|gh\s+pr\s+create\b)")
SOURCE = re.compile(r"pstack:\s*(\S+\.md)")
WORKER = re.compile(r"Read \S*poteto-mode/worker\.md before anything else")
WORKER_MESSAGE = ("pstack 0.15.43: the first line of every kickoff is `Read <abs path>/worker.md before anything else.` "
                  "Add: Read " + str(PSTACK) + "/<newest version>/skills/poteto-mode/worker.md before anything else.")
BRIEF = re.compile(r"\$\(cat\s+([^)\s]+)\)|--body-file\s+(\S+)")
MESSAGE = ("Name the pstack source first. Add a line `pstack: <path>` to the brief or PR body, pointing at the "
           "playbook or principle this design follows, under " + str(PSTACK) + " (for example "
           "skills/poteto-mode/playbooks/autonomous-run.md). No pstack skill covers it? Then do not build it "
           "(SKILL.md, Design first).")


def text_of(cmd):
    parts = [cmd]
    for a, b in BRIEF.findall(cmd):
        path = Path((a or b).replace("~", str(Path.home()), 1))
        try:
            parts.append(path.read_text(errors="ignore"))
        except OSError:
            pass
    return "\n".join(parts)


def resolves(ref):
    ref = ref.strip("`'\"")
    path = Path(ref.replace("~", str(Path.home()), 1))
    root = newest().resolve()
    path = (root / path).resolve()
    return path.is_file() and root in path.parents


def newest():
    """Only the newest installed pstack counts: a playbook removed upstream (orchestrate.md, gone in 0.15.43) must not pass."""
    return max(PSTACK.glob("*"), key=lambda v: tuple(int(x) for x in v.name.split(".") if x.isdigit()))


def verdict(cmd):
    if not LAUNCH.search(cmd) or "NO_TICKET_REASON=" in cmd:
        return None
    text = text_of(cmd)
    if not any(resolves(r) for r in SOURCE.findall(text)):
        return MESSAGE
    if not WORKER.search(text) and not re.search(r"gh\s+pr\s+create\b", cmd):
        return WORKER_MESSAGE
    return None


def self_test():
    import tempfile
    past = Path.home() / "handover/briefs/spawn-worker.md"
    if past.is_file() and "pstack:" not in past.read_text():
        assert verdict(f'codex exec -C /tmp/x "$(cat {past})"'), "the spawn-worker brief (a non-pstack design) is blocked"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write("Goal: x\npstack: skills/poteto-mode/playbooks/autonomous-run.md\n")
    assert verdict(f'codex exec -C /tmp/x "$(cat {f.name})"') == WORKER_MESSAGE, "a brief without the worker.md line is blocked"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as w:
        w.write("Read /x/skills/poteto-mode/worker.md before anything else.\npstack: skills/poteto-mode/playbooks/autonomous-run.md\n")
    assert verdict(f'codex exec -C /tmp/x "$(cat {w.name})"') is None, "a brief with worker.md line and real playbook passes"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as g:
        g.write("pstack: skills/poteto-mode/playbooks/made-up.md\n")
    assert verdict(f'codex exec "$(cat {g.name})"'), "a made-up playbook path is blocked"
    assert verdict('NO_TICKET_REASON="verifier" codex exec "$(cat /tmp/v.md)"') is None, "verifiers are exempt"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as h:
        h.write("pstack: skills/poteto-mode/playbooks/orchestrate.md\n")
    assert verdict(f'codex exec "$(cat {h.name})"'), "orchestrate.md, removed in pstack 0.15.43, is blocked"
    assert verdict("git status") is None, "other commands pass"
    assert verdict('gh pr create --title t --body "x"'), "a PR without a source is blocked"
    assert verdict(f'gh pr create --body-file {f.name}') is None, "a PR needs a pstack source but not the worker.md kickoff line"
    print("pstack-source self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    why = verdict((data.get("tool_input") or {}).get("command") or "")
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
