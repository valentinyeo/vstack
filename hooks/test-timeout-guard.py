#!/usr/bin/env python3
"""PreToolUse guard: every test or build runner runs under `timeout`, or it can hold a core for hours.

2026-11-20: four `python3 -m unittest discover -s scripts` runs hung for 10 to 15 hours and each kept a
core busy. With parallel builds the 18 core VPS reached load 38 and no chat answered the owner. The host
proc-watchdog only stops node and bun runners, so python, pytest, go, cargo, make and shell test scripts
ran unbounded. This guard blocks a runner with no `timeout <duration>` in front of it in the same simple
command, and names the fix. Node builds stay with the watchdog.

test-timeout-guard.py --self-test
"""
import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path

MESSAGE = ("BLOCKED by test-timeout-guard: {runner} can hang for hours. Run every test or build under "
           "timeout: prefix it with `timeout 600` (10 minutes, the default) or `timeout 1800` "
           "(30 minutes, full builds), then run it again.")

WRAPPERS = {"env", "timeout", "nohup", "setsid", "sudo", "command", "nice", "stdbuf", "xargs", "exec"}
# Each wrapper owns its own options. Sharing one set let `env -i pytest` swallow the runner as a
# value, which is the one kind of miss this guard exists to prevent.
TAKES_VALUE = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "sudo": {"-u", "--user", "-g", "--group", "-p", "--prompt", "-C", "-U", "-r", "-t", "--role", "--type"},
    "nice": {"-n", "--adjustment"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "xargs": {"-n", "-I", "-L", "-P", "-s", "-d", "-a", "-E"},
    "exec": {"-a"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
DURATION = re.compile(r"[0-9.]+[smhd]?")
PY_RUNNERS = {"unittest", "pytest", "py.test"}
STANDALONE = {"pytest", "py.test", "vitest", "jest"}
PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
SHELLS = {"bash", "sh", "zsh"}
TSC_FLAGS = {"-b", "--build", "-p"}


def simple_commands(cmd):
    """The command split at `;`, `&`, `|`, `(` and `)`, one token list per simple command."""
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    commands = [[]]
    try:
        for token in lexer:
            if all(char in ";&|()\n" for char in token):
                commands.append([])
            else:
                commands[-1].append(token)
    except ValueError:
        return []
    return [args for args in commands if args]


def strip_wrappers(args):
    """The arguments after every leading assignment and wrapper, and whether a timeout came with them."""
    wrapped = False
    while args:
        if ASSIGNMENT.match(args[0]):
            args = args[1:]
            continue
        name = Path(args[0]).name
        if name not in WRAPPERS:
            break
        args = args[1:]
        takes_value = TAKES_VALUE.get(name, set())
        while args and args[0].startswith("-"):
            option = args[0]
            args = args[2:] if option in takes_value else args[1:]
            if option == "--":
                break
        if name == "timeout" and args and DURATION.fullmatch(args[0]):
            wrapped = True
            args = args[1:]
    return args, wrapped


def runner(args):
    """The runner this simple command starts, as it should read in the block message, or None."""
    name = Path(args[0]).name
    rest = args[1:]
    if name.startswith("python"):
        for i, word in enumerate(rest):
            module = rest[i + 1] if i + 1 < len(rest) else ""
            if word == "-m" and module in PY_RUNNERS:
                return f"{name} -m {module}"
        return None
    if name in STANDALONE:
        return name
    if name in PACKAGE_MANAGERS:
        if rest[:1] == ["test"]:
            return f"{name} test"
        if rest[:2] == ["run", "test"]:
            return f"{name} run test"
        return None
    if name == "playwright" and rest[:1] == ["test"]:
        return "playwright test"
    if name == "cargo" and rest[:1] in (["test"], ["build"]):
        return f"cargo {rest[0]}"
    if name == "go" and rest[:1] == ["test"]:
        return "go test"
    if name == "zig" and rest[:1] == ["build"]:
        return "zig build"
    if name == "make":
        for i, word in enumerate(rest):
            if not word.startswith("-") and word in {"test", "check"}:
                return " ".join(args[:i + 2])
        return None
    if name in SHELLS:
        for i, word in enumerate(rest):
            if word.startswith("-"):
                continue
            if word.endswith(".sh") and "tests" in Path(word).parts[:-1]:
                return " ".join(args[:i + 2])
            return None
        return None
    if name == "node" and "--test" in rest:
        return "node --test"
    if name == "tsc" and any(word in TSC_FLAGS or word.startswith("--build=") or word.startswith("-p=")
                             for word in rest):
        return "tsc"
    return None


def verdict(command):
    """Why this command is blocked, or None."""
    for args in simple_commands(command):
        args, wrapped = strip_wrappers(args)
        if not args or wrapped:
            continue
        caught = runner(args)
        if caught:
            return MESSAGE.format(runner=caught)
    return None


def tables():
    """BLOCKED and ALLOWED from the guard's own test file, so the two can never drift apart."""
    path = Path(__file__).resolve().parents[1] / "tests" / "test_test_timeout_guard.py"
    spec = importlib.util.spec_from_file_location("test_test_timeout_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BLOCKED, module.ALLOWED


def self_test():
    blocked, allowed = tables()
    for command in blocked:
        why = verdict(command)
        assert why, f"must be blocked: {command}"
        assert "timeout 600" in why and why.count("\n") == 0, f"one line naming timeout 600: {why}"
    for command in allowed:
        assert verdict(command) is None, f"must pass: {command}"
    hung = "python3 -m unittest discover -s scripts"
    assert verdict(hung) and "python3 -m unittest" in verdict(hung), f"{hung} froze this VPS on 2026-11-20"
    for command in ("grep pytest", "echo pytest", "cat tests/install.sh", "git log --oneline -- pytest"):
        assert verdict(command) is None, f"naming a runner starts nothing: {command}"
    for command in ("npm run testify", "npm run build", "go build ./...", "cargo run", "node build.js",
                    "make install", "yarn build"):
        assert verdict(command) is None, f"not a runner this guard owns: {command}"
    for command in ("bash tests/install.sh", "sh tests/*.sh", "tsc -p=tsconfig.json", "tsc --build=x"):
        assert verdict(command), f"must be blocked: {command}"
    for command in ("bash scripts/deploy.sh", "sh deploy.sh", "tsc --version"):
        assert verdict(command) is None, f"must pass: {command}"
    print("test-timeout-guard self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input")
    why = verdict((tool_input if isinstance(tool_input, dict) else {}).get("command") or "")
    if not why:
        return 0
    print(why, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
