#!/usr/bin/env python3
"""PreToolUse guard: a gh poll loop spends the one GitHub token every chat shares.

2026-11-20: the shared call log held 69,442 GitHub calls in 24 hours, and two chats polled CI in
tight loops: `while true; do gh pr checks 223; sleep 30; done` and `watch -n 30 gh pr checks 223`.
Each poll is a fresh GraphQL call against one 5000 an hour budget, so one loop starves every other
chat. This guard blocks gh's own `--watch` and any loop that calls gh with a sleep under 60 seconds,
and names the quiet replacement, ~/.local/share/vstack/tools/gh-wrapper/wait-checks, which polls once
a minute through the wrapper cache. Start it as a tracked background command, not with & or nohup.

gh-watch-guard.py --self-test
"""
import json
import re
import shlex
import sys

RULES = "~/.local/share/vstack/tools/gh-wrapper/USING-GITHUB.md"
REPLACEMENT = "~/.local/share/vstack/tools/gh-wrapper/wait-checks <repo> <pr>"
MESSAGE = ("BLOCKED by gh-watch-guard: a gh --watch or a gh loop sleeping under 60 s spends the one "
           "shared GitHub token, so every chat slows down. Start "
           + REPLACEMENT
           + " as a tracked background command (Claude: Bash with run_in_background), never with & "
           "or nohup, so its end wakes the chat (one cached call a minute, exits 0 pass, 1 fail). "
           "Rules: " + RULES)
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
LOOP_WORDS = {"while", "until", "for"}
DURATION = re.compile(r"^([0-9.]+)([smhd]?)$")
UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
SEPARATORS = ";&|()"


def tokens_of(cmd):
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=SEPARATORS + "\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return []


def simple_commands(cmd):
    commands = [[]]
    for token in tokens_of(cmd):
        if token and all(char in SEPARATORS + "\n" for char in token):
            commands.append([])
            continue
        commands[-1].append(token)
    return [args for args in commands if args]


def seconds(value):
    found = DURATION.match(value or "")
    if not found:
        return None
    return float(found.group(1)) * UNITS[found.group(2)]


def is_gh(token):
    return token == "gh" or token.endswith("/gh")


def gh_invocations(args):
    return [args[index:] for index, token in enumerate(args) if is_gh(token)]


def watch_flag(invocation):
    return "--watch" in invocation or "watch" in invocation[1:3]


def watch_command_interval(args):
    """Seconds between rounds of a `watch` call, or None when this is not `watch`."""
    start = None
    for index, token in enumerate(args):
        if token.rsplit("/", 1)[-1] == "watch":
            start = index
            break
    if start is None:
        return None
    every = 2
    rest = args[start + 1:]
    for index, token in enumerate(rest):
        if token in ("-n", "--interval") and index + 1 < len(rest):
            every = seconds(rest[index + 1])
            break
        for head in ("--interval=", "-n="):
            if token.startswith(head):
                every = seconds(token.split("=", 1)[1])
    return 2 if every is None else every


def sleeps_in(tokens):
    found = []
    for index, token in enumerate(tokens):
        if token == "sleep" and index + 1 < len(tokens):
            for value in tokens[index + 1:]:
                if value.startswith("-") and not seconds(value):
                    continue
                parsed = seconds(value)
                if parsed is not None:
                    found.append(parsed)
                break
    return found


def loop_is_loud(tokens):
    """A loop body that calls gh with no sleep at all, or with a sleep under 60 seconds."""
    if not any(is_gh(token) for token in tokens):
        return False
    slept = sleeps_in(tokens)
    return not slept or min(slept) < 60


def loud_loop(cmd) -> bool:
    tokens = tokens_of(cmd)
    depth = 0
    region = []
    for token in tokens:
        if token in LOOP_WORDS:
            if depth == 0:
                region = []
            depth += 1
            region.append(token)
            continue
        if token == "done" and depth:
            depth -= 1
            if depth == 0 and loop_is_loud(region):
                return True
            region.append(token)
            continue
        if depth:
            region.append(token)
    return depth > 0 and loop_is_loud(region)


def nested_shell(args):
    """The script a `bash -c '...'` carries, or None. A leading nohup or sudo does not hide it."""
    for index, token in enumerate(args):
        if token.rsplit("/", 1)[-1] not in SHELLS:
            continue
        rest = args[index + 1:]
        for position, option in enumerate(rest):
            if option.startswith("--"):
                continue
            if option.startswith("-") and "c" in option[1:] and position + 1 < len(rest):
                return rest[position + 1]
            if not option.startswith("-"):
                return None
    return None


def verdict(cmd):
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    for args in simple_commands(cmd):
        script = nested_shell(args)
        if script is not None and verdict(script):
            return MESSAGE
        every = watch_command_interval(args)
        if every is not None:
            if every < 60 and gh_invocations(args):
                return MESSAGE
            continue
        for invocation in gh_invocations(args):
            if watch_flag(invocation):
                return MESSAGE
    if loud_loop(cmd):
        return MESSAGE
    return None


def self_test():
    blocked = [
        "gh pr checks 223 --watch",
        "cd /home/valentin/projects/vstack && gh pr checks 223 --watch --fail-fast",
        "while true; do gh pr checks 223 --repo valentinyeo/vstack; sleep 30; done",
        "while :; do gh pr view 223 --json state,mergeable; sleep 45; done",
        "for i in $(seq 1 40); do gh pr checks 12; sleep 15; done",
        "while ! gh pr checks 12; do sleep 10; done",
        "until gh pr checks 12 >/dev/null; do sleep 20; done",
        "watch -n 30 gh pr checks 12",
        "watch gh pr checks 12",
        "nohup bash -c 'while true; do gh pr checks 12; sleep 20; done' &",
        "bash -lc \"while true; do gh pr checks 7; sleep 30; done\"",
        "gh run watch 4931",
        "while true; do gh pr checks 12; done",
    ]
    allowed = [
        "gh pr checks 223",
        "gh pr view 223 --json body,state",
        "gh api -X PUT repos/valentinyeo/vstack/pulls/223/merge -f merge_method=squash",
        "gh budget",
        "tools/gh-wrapper/wait-checks valentinyeo/vstack 223 &",
        "nohup tools/gh-wrapper/wait-checks valentinyeo/vstack 223 >/tmp/wc.log 2>&1 &",
        "while true; do gh pr checks 223; sleep 120; done",
        "while true; do git fetch origin main; sleep 30; done",
        "watch -n 90 gh pr view 223",
        'grep -n "gh pr checks --watch" tools/gh-wrapper/README.md',
        'echo "while true; do gh pr checks 1; sleep 30; done"',
        "for f in a b c; do sleep 5; done",
        "gh api repos/valentinyeo/vstack/pulls/223",
        "git status",
    ]
    for cmd in blocked:
        assert verdict(cmd) == MESSAGE, f"blocked: {cmd}"
    for cmd in allowed:
        assert verdict(cmd) is None, f"allowed: {cmd}"
    print("gh-watch-guard self-test ok")


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
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    command = tool_input.get("command")
    if not verdict(command if isinstance(command, str) else ""):
        return 0
    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
