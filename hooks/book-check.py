#!/usr/bin/env python3
"""PreToolUse guard: every worker brief and PR walks the verification book, item by item.

Valentin, 2026-11-17: "every time i ask you you tell me you forgot something". The order to follow Lauren's
playbook closely existed with nothing enforcing it. This check makes a skipped item impossible to miss.

A worker launch (codex exec, pi -p, cursor-agent -p) or `gh pr create` must carry a `Book check:` block in the
brief or PR body. The block names every item below on its own line, followed by `:` and how the work covers it,
or `n/a <reason>`. Any missing item blocks the launch and the message names it. Items and quotes:
book/CHECKLIST.md. Verifiers prefixed with NO_TICKET_REASON= are exempt: they check work, they do not plan it.

book-check.py --self-test
"""
import json
import re
import sys
import tempfile
from pathlib import Path

ITEMS = [
    "Agent drives the real app",
    "Human is not the verifier",
    "Feature map",
    "Reproduce bug first",
    "Failing test first",
    "Fix",
    "Agents try to break it",
    "Tests for the verify skill",
    "Hard rules in checks",
    "Auto-merge only once earned",
    "Spend tokens on verifying",
    "Real-size data",
    "Verifier runs on GitHub",
    "Video or trace before release",
    "Check seen failing",
]
LAUNCH = re.compile(r"(?:^|[\s;&|(])(?:\S*/)?(?:codex\s+exec\b|pi\s+(?:.*\s)?-p\b|cursor-agent\s+(?:.*\s)?-p\b|gh\s+pr\s+create\b)")
BRIEF = re.compile(r"\$\(cat\s+([^)\s]+)\)|--body-file\s+(\S+)")


def text_of(cmd):
    parts = [cmd]
    for a, b in BRIEF.findall(cmd):
        try:
            parts.append(Path((a or b).replace("~", str(Path.home()), 1)).read_text(errors="ignore"))
        except OSError:
            pass
    return "\n".join(parts)


def missing(text):
    if "Book check:" not in text:
        return list(ITEMS)
    block = text.split("Book check:", 1)[1]
    out = []
    for item in ITEMS:
        m = re.search(r"^[\s\-*\d.]*" + re.escape(item) + r"[ \t]*:[ \t]*(\S.*)$", block, re.M | re.I)
        if not m:
            out.append(item)
    return out


def verdict(cmd):
    if not LAUNCH.search(cmd) or "NO_TICKET_REASON=" in cmd:
        return None
    gaps = missing(text_of(cmd))
    if not gaps:
        return None
    return ("Book check incomplete. Add a `Book check:` block to the brief or PR body with one line per item, "
            "`<item>: <how covered>` or `<item>: n/a <reason>`. Missing: " + "; ".join(gaps) +
            ". Items and Lauren's quotes: " + str(Path(__file__).resolve().parents[1] / "book/CHECKLIST.md"))


def self_test():
    def brief(body):
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        f.write(body)
        f.close()
        return f'codex exec -C /tmp/x "$(cat {f.name})"'

    full = "Goal: x\nBook check:\n" + "\n".join(f"- {i}: covered by step {n}" for n, i in enumerate(ITEMS))
    assert verdict(brief(full)), "SOFT-2588: a worker brief without Faults must be blocked"
    full = FAULTS + "\n" + full
    assert verdict(brief(full)) is None, "a complete brief passes"
    for broken in ["Faults:", "Faults: hypertask feedback", "Faults: board 2060 ticket with label Poteto",
                   "Faults: hypertask feedback; board 15 ticket with label Poteto",
                   "Faults: hypertask feedback; board 2060 ticket with label Other",
                   "hypertask feedback; board 2060 ticket with label Poteto",
                   "Faults: hypertask feedback\nboard 2060 ticket with label Poteto"]:
        assert verdict(brief(full.replace(FAULTS, broken))), "both paths belong on one Faults line"
    for launcher in ["pi -p", "hax -p", "claude -p", "cursor-agent -p"]:
        assert verdict(launcher + ' "' + full + '"') is None
        assert verdict(launcher + ' "' + full.replace(FAULTS, '') + '"')
    with tempfile.NamedTemporaryFile("w", suffix=".md") as f:
        f.write(full); f.flush()
        assert verdict(f"/x/spawn-worker --level normal {f.name}") is None
        assert verdict(f"spawn-worker --level normal {f.name}.missing")
    assert verdict('gh pr create --body "' + full.replace(FAULTS, '') + '"') is None, "PRs need book items, not fault routes"
    assert verdict('gh pr create --body "Shared spawn-worker brief rules\n' + full.replace(FAULTS, '') + '"') is None, "launcher names in PR prose are not launches"
    # Real past mistake, 2026-11-17: the verify-gate plan had no 'show the check failing first' step.
    gate_plan = full.replace("- Check seen failing: covered by step 14", "")
    why = verdict(brief(gate_plan))
    assert why and "Check seen failing" in why, "today's gate plan, missing 'seen failing', is blocked"
    assert verdict(brief(full.replace("Fix: covered by step 5", "Fix:"))), "an item with no answer is blocked"
    assert "Fix" not in (verdict(brief(full.replace("Fix: covered by step 5", "Fix: n/a no code change"))) or ""), "n/a with a reason passes"
    assert verdict(brief("pstack: skills/poteto-mode/playbooks/autonomous-run.md\n")), "a brief with no book check is blocked"
    assert verdict('NO_TICKET_REASON="verifier" pi -p "' + FAULTS + '"') is None, "verifiers skip book items"
    assert verdict('NO_TICKET_REASON="verifier" pi -p "check it"'), "verifiers still report faults"
    assert verdict('echo "Shared spawn-worker instructions"') is None
    assert verdict('gh pr create --body "' + full.replace(FAULTS, '') + '" && pi -p "missing routes"')
    assert verdict('NO_TICKET_REASON=verifier timeout 10s pi -p "' + FAULTS + '"') is None
    assert verdict("git status") is None, "other commands pass"
    assert verdict('gh pr create --title t --body "x"'), "a PR without a book check is blocked"
    print("book-check self-test ok")


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
