#!/usr/bin/env python3
"""PreToolUse on Agent and Task: a Claude helper starts only when plan-pick --claude-helper allows it.

MULTIPROMPT_TAB or TMUX set means this is a chat Valentin talks to, so the gate applies.
Neither set means a headless fleet run, so every call passes.
plan-pick is the only source of truth: exit 0 allows, exit 3 refuses, and any other result
(a missing picker, a timeout, another exit) allows, so a broken picker never stops work.
The refusal sends the work to plan-pick --run, never to a worker started directly.
PLAN_PICK_BIN overrides the picker path, so the self-test runs on stub pickers.

claude-helper-gate.py --self-test
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PICKER = os.path.expanduser("~/.local/bin/plan-pick")
TIMEOUT = 20
MESSAGE = ("BLOCKED by claude-helper-gate: Claude is ahead of its pace, so this helper runs on another plan. "
           "Put the brief in brief.txt and run ~/.local/bin/plan-pick --run.")


def picker():
    return os.environ.get("PLAN_PICK_BIN") or PICKER


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def ask(path):
    try:
        done = subprocess.run([path, "--claude-helper"], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return done if done.returncode in (0, 3) else None


def verdict(in_chat, path=None):
    if not in_chat:
        return None
    done = ask(path or picker())
    if done is None or done.returncode != 3:
        return None
    return f"{MESSAGE} {first_line(done.stdout) or first_line(done.stderr)}".strip()


def stub(where, code, output):
    path = Path(where, f"plan-pick-exit-{code}")
    path.write_text(f"#!/bin/sh\necho '{output}'\nexit {code}\n")
    path.chmod(0o755)
    return str(path)


def self_test():
    with tempfile.TemporaryDirectory() as where:
        allowed = stub(where, 0, "Claude helper: allowed. Why: Claude is under its pace: pace 0.60x, within 1.1x.")
        refused = stub(where, 3, "Claude helper: refused. Why: Claude is pace 1.40x is above 1.1x.")
        broken = stub(where, 1, "plan-pick: cannot read pool state: no such file")
        assert verdict(True, allowed) is None, "exit 0 allows a Claude helper"
        why = verdict(True, refused)
        assert why, "exit 3 refuses a Claude helper"
        assert why.startswith("BLOCKED by claude-helper-gate"), "the refusal names the gate"
        assert "plan-pick --run" in why, "the refusal sends the work to plan-pick --run"
        assert "codex exec" not in why and "pi -p" not in why, "the refusal never starts a worker directly"
        assert "Claude helper: refused" in why, "the refusal quotes plan-pick's own first line"
        assert verdict(True, broken) is None, "another exit allows, so a broken picker never stops work"
        assert verdict(True, str(Path(where, "gone"))) is None, "a missing picker allows"
        assert verdict(True, where) is None, "a picker that cannot run allows"
        assert verdict(False, refused) is None, "a headless run is not a chat"
        assert verdict(False, allowed) is None, "a headless run passes whatever the picker says"
    print("claude-helper-gate self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    why = verdict(bool(os.environ.get("MULTIPROMPT_TAB") or os.environ.get("TMUX")))
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    else:
        print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
