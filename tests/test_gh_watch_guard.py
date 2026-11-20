#!/usr/bin/env python3
"""hooks/gh-watch-guard.py blocks gh poll loops before they spend the shared GitHub token.

Two chats polled CI in tight loops on 2026-11-20, one every 30 s and one with `watch -n 30`.
Every poll is a fresh GraphQL call against one token shared by every chat. The guard refuses
`gh --watch`, `watch -n <60> gh ...` and shell loops calling gh with a sleep under 60 s, and names
~/.local/share/vstack/tools/gh-wrapper/wait-checks as the quiet replacement.
"""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "hooks/gh-watch-guard.py"
RULES = "~/.local/share/vstack/tools/gh-wrapper/USING-GITHUB.md"

BLOCKED = (
    "gh pr checks 223 --watch",
    "gh pr checks 2455 --repo hypertask-ai/hypertask --watch --interval 300",
    "gh pr checks 16 -R hypertask-ai/docs-rs --watch --interval 30",
    "while true; do gh pr checks 223 --repo valentinyeo/vstack; sleep 30; done",
    "while :; do gh pr view 223 --json state,mergeable; sleep 45; done",
    "for i in $(seq 1 40); do gh pr checks 12; sleep 15; done",
    "while ! gh pr checks 12; do sleep 10; done",
    "until gh pr checks 12 >/dev/null; do sleep 20; done",
    "watch -n 30 gh pr checks 12",
    "watch gh pr checks 12",
    "nohup bash -c 'while true; do gh pr checks 12; sleep 20; done' &",
    'bash -lc "while true; do gh pr checks 7; sleep 30; done"',
    "gh run watch 4931",
    "while true; do gh pr checks 12; done",
)

ALLOWED = (
    "gh pr checks 223",
    "gh pr view 223 --json body,state",
    "gh api -X PUT repos/valentinyeo/vstack/pulls/223/merge -f merge_method=squash",
    "gh api repos/valentinyeo/vstack/pulls/223",
    "gh budget",
    "tools/gh-wrapper/wait-checks valentinyeo/vstack 223 &",
    "nohup tools/gh-wrapper/wait-checks valentinyeo/vstack 223 >/tmp/wc.log 2>&1 &",
    "while true; do gh pr checks 223; sleep 120; done",
    "while true; do git fetch origin main; sleep 30; done",
    "watch -n 90 gh pr view 223",
    'grep -n "gh pr checks --watch" tools/gh-wrapper/README.md',
    'echo "while true; do gh pr checks 1; sleep 30; done"',
    "for f in a b c; do sleep 5; done",
    "git status",
    "",
)


def load_guard():
    spec = importlib.util.spec_from_file_location("gh_watch_guard", str(GUARD))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerdictTests(unittest.TestCase):
    def setUp(self):
        self.guard = load_guard()

    def test_every_loud_command_is_blocked(self):
        for command in BLOCKED:
            self.assertEqual(self.guard.verdict(command), self.guard.MESSAGE, command)

    def test_every_quiet_command_passes(self):
        for command in ALLOWED:
            self.assertIsNone(self.guard.verdict(command), command)

    def test_the_message_names_the_quiet_command_and_the_rules(self):
        self.assertIn("~/.local/share/vstack/tools/gh-wrapper/wait-checks <repo> <pr>", self.guard.MESSAGE)
        self.assertIn(RULES, self.guard.MESSAGE)
        self.assertTrue(self.guard.MESSAGE.startswith("BLOCKED by gh-watch-guard:"))

    def test_guard_message_uses_shared_install_path_not_repo_relative(self):
        self.assertIn("~/.local/share/vstack/tools/gh-wrapper/wait-checks <repo> <pr>", self.guard.MESSAGE)
        self.assertNotIn("instead: tools/gh-wrapper/wait-checks", self.guard.MESSAGE)
        self.assertIn("run_in_background", self.guard.MESSAGE)

    def test_self_test_mode_passes(self):
        result = subprocess.run([sys.executable, str(GUARD), "--self-test"], capture_output=True,
                                text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("self-test ok", result.stdout)


class HookContractTests(unittest.TestCase):
    def payload(self, command, tool="Bash"):
        return json.dumps({"tool_name": tool, "tool_input": {"command": command}})

    def run_hook(self, payload):
        return subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True,
                              text=True, timeout=60)

    def test_a_loud_bash_command_exits_two_with_the_message(self):
        result = self.run_hook(self.payload("while true; do gh pr checks 223; sleep 30; done"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLOCKED by gh-watch-guard", result.stderr)
        self.assertIn(RULES, result.stderr)

    def test_a_quiet_command_passes_silently(self):
        result = self.run_hook(self.payload("gh pr checks 223"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_another_tool_is_not_this_guards_business(self):
        result = self.run_hook(self.payload("while true; do gh pr checks 1; sleep 5; done", tool="Read"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_broken_json_passes(self):
        result = self.run_hook("{not json")
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
