#!/usr/bin/env python3
"""PreToolUse guard: a gh poll loop spends the one GitHub token every chat shares.

2026-11-20: the shared call log held 69,442 GitHub calls in 24 hours, and two chats polled CI in
tight loops: `while true; do gh pr checks 223; sleep 30; done` and `watch -n 30 gh pr checks 223`.
Each poll is a fresh GraphQL call against one 5000 an hour budget, so one loop starves every other
chat. This guard blocks gh's own `--watch` and any loop that calls gh with a sleep under 60 seconds,
and names the quiet replacement, ~/.local/share/vstack/tools/gh-wrapper/wait-checks, which polls once
a minute through the wrapper cache. Start it as a tracked background command, not with & or nohup.

    gh-watch-guard.py --install-for-project [DIR]   register this hook for one project
    gh-watch-guard.py --check-project [DIR]         exit 0 when DIR has the hook
    gh-watch-guard.py --self-test
"""
import importlib.machinery
import importlib.util
import json
import re
import shlex
import sys
import tempfile
from pathlib import Path

_PROJECT_HOOKS_MODULE = None


def ph():
    """Load hooks/project_hooks.py when install or check need it."""
    global _PROJECT_HOOKS_MODULE
    if _PROJECT_HOOKS_MODULE is not None:
        return _PROJECT_HOOKS_MODULE
    here = Path(__file__).resolve().parent
    for candidate in (
        here / 'project_hooks.py',
        here.parent / 'hooks' / 'project_hooks.py',
        Path.home() / '.claude/hooks/project_hooks.py',
    ):
        if not candidate.is_file():
            continue
        loader = importlib.machinery.SourceFileLoader('project_hooks', str(candidate))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        _PROJECT_HOOKS_MODULE = module
        return module
    raise ModuleNotFoundError('project_hooks.py')


RULES = "~/.local/share/vstack/tools/gh-wrapper/USING-GITHUB.md"
REPLACEMENT = "~/.local/share/vstack/tools/gh-wrapper/wait-checks <repo> <pr>"
MESSAGE = ("BLOCKED by gh-watch-guard: a gh --watch or a gh loop sleeping under 60 s spends the one "
           "shared GitHub token, so every chat slows down. Start "
           + REPLACEMENT
           + " as a tracked background command (Claude: Bash with run_in_background), never with & "
           "or nohup, so its end wakes the chat (one cached call a minute, exits 0 pass, 1 fail). "
           "Rules: " + RULES)
HOOK_BASENAME = 'gh-watch-guard.py'
HOOK_PREFIX = 'gh-watch-guard'
HOOK_FILE = '$HOME/.claude/hooks/gh-watch-guard.py'
HOOK_COMMAND = (
    "sh -c 'f=\"" + HOOK_FILE + "\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\"'"
)
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
LOOP_WORDS = {"while", "until", "for"}
DURATION = re.compile(r"^([0-9.]+)([smhd]?)$")
UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
SEPARATORS = ";&|()"
DATA_COMMANDS = frozenset(("echo", "printf", "cat", "tee"))
HEREDOC_TAIL = re.compile(r'<<-?(?:[\'"])?(\w+)(?:[\'"])?\s*$')


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


def heredoc_is_inert(line, start):
    """True when the heredoc only carries text into a file or message, not an executed script."""
    prefix = line[:start].strip()
    if not prefix:
        return False
    tokens = tokens_of(prefix)
    if not tokens:
        return False
    names = [token.rsplit("/", 1)[-1] for token in tokens]
    if any(name in SHELLS for name in names):
        return False
    return any(name in DATA_COMMANDS for name in names)


def strip_heredocs(cmd):
    """Drop inert heredoc bodies (cat/tee); keep executable shell heredocs for matching."""
    lines = cmd.split("\n")
    out = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if "<<" in line:
            start = line.rfind("<<")
            tail = line[start:]
            found = HEREDOC_TAIL.match(tail)
            if found and heredoc_is_inert(line, start):
                delim = found.group(1)
                indented = tail.startswith("<<-")
                out.append((line[:start] + tail[: found.start()]).rstrip())
                index += 1
                while index < len(lines):
                    body = lines[index].lstrip("\t") if indented else lines[index]
                    if body == delim:
                        index += 1
                        break
                    index += 1
                continue
        out.append(line)
        index += 1
    return "\n".join(out)


def strip_data_line(line):
    """Blank inert quoted payload on one command line; executable -c strings stay."""
    for args in simple_commands(line):
        if not args:
            return line
        head = args[0].rsplit("/", 1)[-1]
        if head in ("eval", "watch"):
            return line
        if head in SHELLS and nested_shell(args) is not None:
            return line
        if head in DATA_COMMANDS:
            return re.sub(
                r'^(\s*(?:\S+/)?(?:' + "|".join(DATA_COMMANDS) + r')\s+)'
                r'(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[^\s;|&]+)',
                r'\1""',
                line,
                count=1,
            )
        if head == "git":
            return re.sub(
                r'(-m|--message)\s+(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\S+)',
                r'\1 ""',
                line,
            )
        if head == "gh":
            line = re.sub(r'(-f\s+body=|body=)("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\S+)', r'\1', line)
        return line
    return line


def strip_data_quotes(cmd):
    """Blank quoted payload in echo/commit/gh-field arguments; leave shell -c strings alone."""
    return "\n".join(strip_data_line(part) for part in cmd.split("\n"))


def scrub_for_match(cmd):
    if not isinstance(cmd, str):
        return cmd
    text = strip_heredocs(cmd)
    text = strip_data_quotes(text)
    return text


def verdict(cmd):
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    cmd = scrub_for_match(cmd)
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


def gate_items(settings):
    return ph().gate_items(settings, HOOK_BASENAME)


def install_for_project(given):
    return ph().install_for_project(
        given, prefix=HOOK_PREFIX, hook_substring=HOOK_BASENAME,
        hook_file=HOOK_FILE, hook_command=HOOK_COMMAND)


def check_project(given):
    return ph().check_project(
        given, prefix=HOOK_PREFIX, hook_substring=HOOK_BASENAME,
        hook_file=HOOK_FILE, hook_command=HOOK_COMMAND,
        hook_label='gh-watch-guard hook')


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
        'bash -lc "while true; do gh pr checks 7; sleep 30; done"',
        "bash -c \"gh pr checks 1 --watch\"",
        "bash <<'E'\nwhile true; do gh pr checks 1; sleep 30; done\nE",
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
        'echo "never use gh pr checks --watch"',
        'git commit -m "block gh --watch loops"',
        "for f in a b c; do sleep 5; done",
        "gh api repos/valentinyeo/vstack/pulls/223",
        "git status",
        (
            "cat > brief.txt <<'E'\n"
            "sleeping under 60 s\n"
            "never gh --watch in production\n"
            "E"
        ),
    ]
    for cmd in blocked:
        assert verdict(cmd) == MESSAGE, "blocked: {}".format(cmd)
    for cmd in allowed:
        assert verdict(cmd) is None, "allowed: {}".format(cmd)
    with tempfile.TemporaryDirectory() as where:
        assert install_for_project([where]) == 0, 'install writes project settings'
        assert check_project([where]) == 0, 'check sees the hook it just installed'
        path = Path(where) / '.claude/settings.local.json'
        assert path.is_file(), 'settings file exists'
        assert [item['command'] for item in gate_items(ph().read_settings(path))] == [HOOK_COMMAND], \
            'install writes the fail-open command'
        assert install_for_project([where]) == 0, 'second install is idempotent'
        assert len(gate_items(ph().read_settings(path))) == 1, 'one hook entry'
    with tempfile.TemporaryDirectory() as where:
        path = Path(where) / '.claude/settings.local.json'
        path.parent.mkdir(parents=True)
        before = {'hooks': {'PreToolUse': [
            {'matcher': 'Write', 'hooks': [{'type': 'command', 'command': '/other.py'}]},
            {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': HOOK_COMMAND}]}]}}
        path.write_text(json.dumps(before))
        assert install_for_project([where]) == 0
        kept = json.loads(path.read_text())
        assert kept['hooks']['PreToolUse'][0] == before['hooks']['PreToolUse'][0]
        assert len(gate_items(kept)) == 1, 'no duplicate when already registered'
    print("gh-watch-guard self-test ok")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ['--self-test']:
        self_test()
        return 0
    if args[:1] == ['--install-for-project']:
        return install_for_project(args[1:2])
    if args[:1] == ['--check-project']:
        return check_project(args[1:2])
    if args:
        print('gh-watch-guard: unknown argument {!r}; nothing was done'.format(args[0]),
              file=sys.stderr)
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
