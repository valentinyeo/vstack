#!/usr/bin/env python3
"""PreToolUse guard: a chat Valentin talks to never writes code, and stays off heavy Bash while Claude is ahead of pace.

MULTIPROMPT_TAB set means this is a Valentin-facing Multibot chat, so code-write blocking applies.
Unset means a headless fleet run, so workers stay untouched. In a valentin-mode chat, Bash that runs tests,
builds, linters, installs, git merges, or long loops is blocked while Claude pace_ratio is above 1.1x; reads,
hypertask, plan-pick, vps-state and board-drain scripts always pass. Pace is cached five minutes under
~/.cache/pacer-guard/pace.json. Any pace read error allows the call. PACER_GUARD_PACE=off disables pace blocking.

pacer-guard.py --self-test"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

MESSAGE = ("BLOCKED by pacer-guard: this chat talks to Valentin, so it never writes code. "
           "Put the change in brief.txt and run ~/.local/bin/plan-pick --run.")
CODE_EXT = frozenset(
    ".py .js .mjs .cjs .ts .tsx .jsx .sh .bash .zsh .go .rs .rb .java .kt .swift .c .h .cc .cpp "
    ".cs .php .css .scss .vue .svelte .sql .lua".split())
TEXT_EXT = frozenset(".md .txt .json .toml .ini .env .html".split())
WORKFLOW = re.compile(r"(^|/)\.github/workflows/")
FILE_TOOLS = frozenset(('Edit', 'Write', 'MultiEdit', 'NotebookEdit'))
STOP = frozenset((';', ';;', '|', '||', '&', '&&', '(', ')', '\n'))
SCRIPT_FLAGS = frozenset(('-e', '--expression', '-f', '--file'))
PUNCTUATION = ';&|()<>'
PACE_LIMIT = 1.1
PACE_TTL = 300
PICKER = os.path.expanduser("~/.local/bin/plan-pick")
LADDER = os.path.expanduser("~/.local/bin/token-ladder")
NESTED = frozenset({"lease"})
BOARD_DRAIN = frozenset({"drain-check", "loop-state", "watch", "sync", "owners"})
READ_TOOLS = frozenset({"cat", "grep", "rg", "ls", "head", "tail", "less", "more", "wc", "find", "stat", "pwd",
                        "which", "file", "sort", "uniq", "cut", "tr", "awk", "jq", "yq", "true", "false"})
LINTERS = frozenset({"eslint", "ruff", "flake8", "pylint", "mypy", "biome", "golangci-lint", "shellcheck", "rubocop",
                     "stylelint", "tsc", "clippy"})
PACKAGE_MANAGERS = frozenset({"npm", "pnpm", "yarn", "bun"})
GIT_READ = frozenset({"log", "status", "diff", "show"})
GIT_BLOCK = frozenset({"rebase", "merge", "cherry-pick"})
GH_READ = frozenset({"view", "list", "checks"})
WHILE_LOOP = re.compile(r"\bwhile\s+(:|true|1|-)\b")
UNTIL_WAIT = re.compile(r"\buntil\b[^;]*;\s*do\s+(sleep|wait)\b")
FOR_C_LOOP = re.compile(r"\bfor\s+\(\(")
_here = Path(__file__).resolve()
_spec = importlib.util.spec_from_file_location("book_check", _here.with_name("book-check.py"))
book = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(book)
_spec = importlib.util.spec_from_file_location("test_timeout_guard", _here.with_name("test-timeout-guard.py"))
ttg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ttg)
_spec = importlib.util.spec_from_file_location("valentin_mode_loaded", _here.with_name("valentin_mode_loaded.py"))
valentin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(valentin)


def pace_message(ratio):
    shown = f"{ratio:.2f}".rstrip("0").rstrip(".")
    return (f"BLOCKED by pacer-guard: Claude is ahead of pace ({shown}x). "
            "Put this work in brief.txt and run ~/.local/bin/plan-pick --run in the background.")


def cache_path():
    override = os.environ.get("PACER_GUARD_PACE_FILE")
    return Path(override) if override else Path.home() / ".cache/pacer-guard/pace.json"


def read_cache():
    path = cache_path()
    try:
        data = json.loads(path.read_text())
        age = time.time() - float(data.get("fetched_at", 0))
        if age < PACE_TTL and "pace_ratio" in data:
            return float(data["pace_ratio"])
    except (OSError, ValueError, TypeError):
        pass
    return None


def write_cache(ratio):
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pace_ratio": ratio, "fetched_at": time.time()}))
    except OSError:
        pass


def fetch_pace():
    picker = os.environ.get("PLAN_PICK_BIN") or PICKER
    try:
        done = subprocess.run([picker, "--loop-interval", "--json"], capture_output=True, text=True, timeout=5)
        if done.returncode == 0:
            ratio = json.loads(done.stdout).get("pace_ratio")
            if ratio is not None:
                return float(ratio)
    except (OSError, ValueError, subprocess.SubprocessError, TypeError):
        pass
    ladder = os.environ.get("TOKEN_LADDER_BIN") or LADDER
    try:
        done = subprocess.run([ladder, "pools", "--json"], capture_output=True, text=True, timeout=5)
        if done.returncode == 0:
            ratio = (json.loads(done.stdout).get("claude") or {}).get("pace_ratio")
            if ratio is not None:
                return float(ratio)
    except (OSError, ValueError, subprocess.SubprocessError, TypeError):
        pass
    return None


def pace_ratio():
    cached = read_cache()
    if cached is not None:
        return cached
    ratio = fetch_pace()
    if ratio is not None:
        write_cache(ratio)
    return ratio


def clean(path):
    return str(path or '').strip().strip('\'"').strip()


def is_code(path, content=None):
    name = clean(path)
    if not name:
        return False
    suffix = Path(name).suffix.lower()
    if suffix in TEXT_EXT:
        return False
    if suffix in CODE_EXT:
        return True
    if suffix in ('.yml', '.yaml'):
        return bool(WORKFLOW.search(Path(name).as_posix()))
    if suffix:
        return False
    if content is not None:
        return content.lstrip().startswith('#!')
    try:
        with open(name, 'rb') as script:
            return script.read(2) == b'#!'
    except OSError:
        return False


def tokens(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=PUNCTUATION)
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return re.findall(r'>>?|[^\s;&|()<>]+', command)


def tee_paths(args):
    found = []
    for token in args:
        if token in STOP:
            break
        if not token.startswith('-'):
            found.append(token)
    return found


def inplace_paths(args):
    flags, rest, separate_script = [], [], False
    i = 0
    while i < len(args):
        token = args[i]
        if token in STOP:
            break
        if token.startswith('-') and len(token) > 1:
            flags.append(token)
            if token in SCRIPT_FLAGS:
                separate_script = True
                i += 2
                continue
        else:
            rest.append(token)
        i += 1
    if not any('i' in flag.lower() for flag in flags):
        return []
    return rest if separate_script else rest[1:]


def bash_paths(command):
    words = tokens(command)
    found = []
    for i, word in enumerate(words):
        if word in ('>', '>>'):
            if i + 1 < len(words):
                found.append(words[i + 1])
        elif word.rsplit('/', 1)[-1] in ('tee', 'sed', 'perl'):
            rest = words[i + 1:]
            found += tee_paths(rest) if word.rsplit('/', 1)[-1] == 'tee' else inplace_paths(rest)
    return found


def argv_list(cmd, depth=0):
    found = []
    for args in book.launch_argv(cmd):
        found.append(args)
        if depth < 4 and args and Path(args[0]).name in NESTED and "--" in args:
            tail = args[args.index("--") + 1:]
            if tail:
                found += argv_list(shlex.join(tail), depth + 1)
    return found


def plan_pick_in(cmd):
    for args in argv_list(cmd):
        if args and Path(args[0]).name == "plan-pick":
            return True
    return False


def board_drain_in(args):
    if not args:
        return False
    token = args[0]
    if "board-drain" in token:
        return True
    return Path(token).name in BOARD_DRAIN and "board-drain" in Path(token).as_posix()


def brief_only(command):
    paths = bash_paths(command)
    return bool(paths) and all(Path(clean(path)).name == "brief.txt" for path in paths)


def sed_read(args):
    if not args or Path(args[0]).name != "sed":
        return False
    flags = [arg for arg in args[1:] if arg.startswith("-")]
    return any(flag == "-n" or flag.startswith("-n") for flag in flags) and not any(
        "i" in flag for flag in flags)


def git_read(args):
    return len(args) >= 2 and Path(args[0]).name == "git" and args[1] in GIT_READ


def gh_read(args):
    return (len(args) >= 4 and Path(args[0]).name == "gh" and args[1] == "pr" and args[2] in GH_READ)


def hypertask_in(args):
    if not args:
        return False
    name = Path(args[0]).name
    return name in ("hypertask", "ht") or "hypertask" in args[0]


def pace_segment_allowed(text, args):
    if not args:
        return True
    name = Path(args[0]).name
    if name in READ_TOOLS:
        return True
    if sed_read(args) or git_read(args) or gh_read(args) or hypertask_in(args):
        return True
    if name == "vps-state" or board_drain_in(args) or plan_pick_in(text):
        return True
    if brief_only(text):
        return True
    if name.startswith("python") and any(Path(part).name == "pacer-guard.py" for part in args):
        return True
    return False


def install_blocked(args):
    if not args:
        return False
    name = Path(args[0]).name
    rest = args[1:]
    if name in ("pip", "pip3", "uv") and rest[:1] == ["install"]:
        return True
    if name in PACKAGE_MANAGERS and rest[:1] in (["install"], ["ci"], ["add"]):
        return True
    return False


def git_blocked(args):
    return len(args) >= 2 and Path(args[0]).name == "git" and args[1] in GIT_BLOCK


def gh_blocked(args):
    return len(args) >= 4 and Path(args[0]).name == "gh" and args[1] == "pr" and args[2] == "checkout"


def npm_script_blocked(args):
    if not args:
        return False
    name = Path(args[0]).name
    rest = args[1:]
    if name not in PACKAGE_MANAGERS or rest[:1] != ["run"] or len(rest) < 2:
        return False
    return rest[1] in ("test", "build", "lint", "check", "verify", "typecheck", "fmt")


def loop_blocked(text):
    if UNTIL_WAIT.search(text):
        return False
    return bool(WHILE_LOOP.search(text) or FOR_C_LOOP.search(text))


def pace_segment_blocked(args):
    if install_blocked(args) or git_blocked(args) or gh_blocked(args) or npm_script_blocked(args):
        return True
    if args and Path(args[0]).name in LINTERS:
        return True
    if args and Path(args[0]).name in PACKAGE_MANAGERS and args[1:2] == ["test"]:
        return True
    caught = ttg.runner(args)
    if caught:
        return True
    if args and Path(args[0]).name.startswith("python"):
        rest = args[1:]
        if "-m" in rest:
            module = rest[rest.index("-m") + 1] if rest.index("-m") + 1 < len(rest) else ""
            if module in ("unittest", "pytest"):
                return True
    return False


def pace_bash_verdict(command, ratio):
    if not isinstance(command, str) or not command.strip():
        return None
    if loop_blocked(command):
        return pace_message(ratio)
    for args in ttg.simple_commands(command):
        args, _wrapped = ttg.strip_wrappers(args)
        if not args:
            continue
        text = shlex.join(args)
        if pace_segment_allowed(text, args):
            continue
        if pace_segment_blocked(args):
            return pace_message(ratio)
    return None


def verdict_code(tool_name, tool_input):
    if tool_name in FILE_TOOLS:
        path = tool_input.get('file_path') or tool_input.get('notebook_path') or ''
        content = tool_input.get('content') if tool_name == 'Write' else None
        return MESSAGE if is_code(path, content) else None
    if tool_name == 'Bash':
        command = tool_input.get('command') or ''
        return MESSAGE if any(is_code(path) for path in bash_paths(command)) else None
    return None


def verdict_pace(tool_name, tool_input, ratio):
    if tool_name != "Bash":
        return None
    command = tool_input.get("command")
    return pace_bash_verdict(command if isinstance(command, str) else "", ratio)


def gate(payload):
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if os.environ.get("MULTIPROMPT_TAB"):
        why = verdict_code(tool_name, tool_input)
        if why:
            return why
    if os.environ.get("PACER_GUARD_PACE", "").lower() == "off":
        return None
    if not valentin.loaded(payload.get("transcript_path")):
        return None
    ratio = pace_ratio()
    if ratio is None or ratio <= PACE_LIMIT:
        return None
    return verdict_pace(tool_name, tool_input, ratio)


def self_test():
    assert is_code('x.py') and is_code('web/app.tsx') and is_code('style.scss'), "code extensions count"
    assert is_code('.github/workflows/a.yml'), "a workflow file is code"
    assert not is_code('ci/a.yml') and not is_code('deploy.yaml'), "other yml is not code"
    for docs in ('notes.md', 'brief.txt', 'data.json', 'config.toml', 'settings.ini', '.env', 'page.html'):
        assert not is_code(docs), f"{docs} is never code"
    assert is_code('/tmp/build.sh'), "a file under /tmp is still checked"
    with tempfile.TemporaryDirectory() as where:
        script = Path(where, 'deploy')
        script.write_text('#!/bin/sh\necho hi\n')
        notes = Path(where, 'notes')
        notes.write_text('hello\n')
        assert is_code(str(script)), "an extensionless shebang file is code"
        assert is_code('new-command', '#!/usr/bin/env python3\n'), "a shebang Write is code"
        assert not is_code(str(notes)), "an extensionless plain file is not code"
    assert verdict_code('Write', {'file_path': 'x.py'}) == MESSAGE, "a code Write is blocked"
    assert verdict_code('Edit', {'file_path': 'notes.md'}) is None, "a docs Edit passes"
    assert verdict_code('MultiEdit', {'file_path': 'a/go.mod'}) is None, "an unknown extension passes"
    assert verdict_code('NotebookEdit', {'notebook_path': 'lab.py'}) == MESSAGE, "a notebook code edit is blocked"
    assert verdict_code('Read', {'file_path': 'x.py'}) is None, "reading code passes"
    assert verdict_code('Bash', {'command': 'cat > foo.sh <<EOF\n#!/bin/sh\nEOF'}) == MESSAGE, "a heredoc into code is blocked"
    assert verdict_code('Bash', {'command': 'ls > out.txt'}) is None, "redirecting docs passes"
    assert verdict_code('Bash', {'command': 'echo x | tee app.js'}) == MESSAGE, "tee into code is blocked"
    assert verdict_code('Bash', {'command': "sed -i 's/a/b/' run.py"}) == MESSAGE, "an in-place edit of code is blocked"
    assert verdict_code('Bash', {'command': "sed -n 's/a/b/p' run.py"}) is None, "a plain sed read passes"
    assert verdict_code('Bash', {'command': 'python3 hooks/pacer-guard.py --self-test'}) is None, "running code passes"
    ahead = 1.21
    blocked_cmds = [
        'python3 -m unittest discover -s tests',
        'npm test',
        'pnpm run build',
        'pip install requests',
        'git rebase origin/main',
        'gh pr checkout 42',
        'ruff check .',
        'while true; do sleep 1; done',
        'cargo test',
    ]
    allowed_cmds = [
        'git status',
        'git log -1',
        'gh pr view 42',
        'cat README.md',
        "sed -n '1,5p' hooks/pacer-guard.py",
        '~/.local/bin/plan-pick --run',
        'lease SOFT-12 run -- plan-pick --run',
        'hypertask task list --project 1',
        '~/.local/bin/vps-state',
        'skills/board-drain/drain-check',
        'echo work > brief.txt',
        'grep pace hooks/pacer-guard.py',
        'until [ -f done ]; do sleep 1; done',
    ]
    for cmd in blocked_cmds:
        assert pace_bash_verdict(cmd, ahead), f"ahead must block: {cmd}"
    for cmd in allowed_cmds:
        assert pace_bash_verdict(cmd, ahead) is None, f"ahead must allow: {cmd}"
    with tempfile.TemporaryDirectory() as where:
        pace_file = Path(where, "pace.json")
        pace_file.write_text(json.dumps({"pace_ratio": ahead, "fetched_at": time.time()}))
        loaded = Path(where, "loaded.jsonl")
        loaded.write_text('{"type":"user","message":{"content":'
                          '"<command-name>/valentin-mode</command-name>"}}\n')
        plain = Path(where, "plain.jsonl")
        plain.write_text('{"type":"user","message":{"content":"hello"}}\n')
        os.environ["PACER_GUARD_PACE_FILE"] = str(pace_file)
        try:
            body = {"tool_name": "Bash", "transcript_path": str(loaded),
                    "tool_input": {"command": "python3 -m unittest discover -s tests"}}
            assert gate(body) and "ahead of pace" in gate(body), "valentin-mode ahead blocks tests"
            body["tool_input"] = {"command": "git status"}
            assert gate(body) is None, "reads pass ahead"
            body["transcript_path"] = str(plain)
            body["tool_input"] = {"command": "python3 -m unittest discover -s tests"}
            assert gate(body) is None, "plain chat is not pace-gated"
            pace_file.write_text(json.dumps({"pace_ratio": 0.8, "fetched_at": time.time()}))
            body["transcript_path"] = str(loaded)
            body["tool_input"] = {"command": "npm test"}
            assert gate(body) is None, "on-pace allows tests"
            os.environ["PACER_GUARD_PACE"] = "off"
            pace_file.write_text(json.dumps({"pace_ratio": ahead, "fetched_at": time.time()}))
            assert gate(body) is None, "override allows ahead"
            del os.environ["PACER_GUARD_PACE"]
            pace_file.write_text("not json")
            broken = Path(where, "broken-pick")
            broken.write_text("#!/bin/sh\nexit 1\n")
            broken.chmod(0o755)
            os.environ["PLAN_PICK_BIN"] = str(broken)
            os.environ["TOKEN_LADDER_BIN"] = str(broken)
            assert gate(body) is None, "unreadable pace allows"
        finally:
            os.environ.pop("PACER_GUARD_PACE_FILE", None)
            os.environ.pop("PACER_GUARD_PACE", None)
            os.environ.pop("PLAN_PICK_BIN", None)
            os.environ.pop("TOKEN_LADDER_BIN", None)
    print('pacer-guard self-test ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    why = gate(payload)
    if not why:
        return 0
    print(why, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())