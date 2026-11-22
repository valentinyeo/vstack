#!/usr/bin/env python3
"""PreToolUse guard: a chat Valentin talks to never writes code, and stays off heavy Bash.

MULTIPROMPT_TAB set means this is a Valentin-facing Multibot chat, so code-write blocking applies.
Unset means a headless fleet run, so workers stay untouched. In a valentin-mode chat, Bash that runs tests,
builds, linters, installs, git merges, or long loops is blocked; reads, hypertask, plan-pick, vps-state and
board-drain scripts always pass. PACER_GUARD_INLINE=off disables heavy-Bash blocking.

pacer-guard.py --self-test"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile

MESSAGE = ("BLOCKED by pacer-guard: this chat talks to Valentin, so it never writes code. "
           "Put the change in brief.txt and run ~/.local/bin/plan-pick --run.")
WORKER_MESSAGE = ("BLOCKED by pacer-guard: this chat talks to Valentin, so it hands work to workers. "
                  "Put this work in brief.txt and run ~/.local/bin/plan-pick --run in the background "
                  "(or a Claude helper when plan-pick --claude-helper allows).")
CODE_EXT = frozenset(
    ".py .js .mjs .cjs .ts .tsx .jsx .sh .bash .zsh .go .rs .rb .java .kt .swift .c .h .cc .cpp "
    ".cs .php .css .scss .vue .svelte .sql .lua".split())
TEXT_EXT = frozenset(".md .txt .json .toml .ini .env .html".split())
WORKFLOW = re.compile(r"(^|/)\.github/workflows/")
FILE_TOOLS = frozenset(('Edit', 'Write', 'MultiEdit', 'NotebookEdit'))
STOP = frozenset((';', ';;', '|', '||', '&', '&&', '(', ')', '\n'))
SCRIPT_FLAGS = frozenset(('-e', '--expression', '-f', '--file'))
PUNCTUATION = ';&|()<>'
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
UNTIL_WAIT = re.compile(r"\buntil\b[^;]*;\s*do\s+(sleep|wait)\b")
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
_spec = importlib.util.spec_from_file_location("subagent_call", _here.with_name("subagent_call.py"))
subagent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(subagent)


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


def strip_heredocs(cmd):
    if "<<" not in cmd:
        return cmd
    lines = cmd.split("\n")
    out, delim = [], None
    for line in lines:
        if delim is not None:
            if line.strip() == delim:
                delim = None
            continue
        hit = re.search(r"<<-?\s*(?:'(\w+)'|\"(\w+)\"|(\w+))", line)
        if hit:
            delim = next(part for part in hit.groups() if part)
            out.append(line)
            continue
        out.append(line)
    return "\n".join(out)


def loop_segment_blocked(args):
    if not args:
        return False
    head = args[0]
    if head == "while" and len(args) >= 2 and args[1] in (":", "true", "1", "-"):
        return True
    if head == "for" and len(args) >= 2 and args[1].startswith("(("):
        return True
    if head == "until" and "do" in args:
        chunk = " ".join(args)
        if UNTIL_WAIT.search(chunk):
            return False
        return True
    return False


def shell_c_strings(args):
    if not args:
        return []
    name = Path(args[0]).name
    if name not in frozenset({"bash", "sh", "zsh", "dash"}):
        return []
    rest = args[1:]
    found, idx = [], 0
    while idx < len(rest):
        word = rest[idx]
        if word in ("-c", "--command"):
            if idx + 1 < len(rest):
                found.append(rest[idx + 1])
            idx += 2
        elif word == "--":
            break
        elif word.startswith("-"):
            idx += 1
        else:
            idx += 1
    return found


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


def pace_bash_verdict(command, _depth=0):
    if not isinstance(command, str) or not command.strip():
        return None
    scrubbed = strip_heredocs(command)
    for args in ttg.simple_commands(scrubbed):
        args, _wrapped = ttg.strip_wrappers(args)
        if not args:
            continue
        text = shlex.join(args)
        if loop_segment_blocked(args):
            return WORKER_MESSAGE
        if pace_segment_allowed(text, args):
            continue
        if pace_segment_blocked(args):
            return WORKER_MESSAGE
        if _depth < 4:
            for inner in shell_c_strings(args):
                why = pace_bash_verdict(inner, _depth + 1)
                if why:
                    return why
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


def verdict_worker_bash(tool_name, tool_input):
    if tool_name != "Bash":
        return None
    command = tool_input.get("command")
    return pace_bash_verdict(command if isinstance(command, str) else "")


def gate(payload):
    if not isinstance(payload, dict):
        return None
    if subagent.from_hook(payload):
        return None
    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if os.environ.get("MULTIPROMPT_TAB"):
        why = verdict_code(tool_name, tool_input)
        if why:
            return why
    if os.environ.get("PACER_GUARD_INLINE", "").lower() == "off":
        return None
    if not valentin.loaded(payload.get("transcript_path")):
        return None
    return verdict_worker_bash(tool_name, tool_input)


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
        assert pace_bash_verdict(cmd), f"valentin-mode must block: {cmd}"
    for cmd in allowed_cmds:
        assert pace_bash_verdict(cmd) is None, f"valentin-mode must allow: {cmd}"
    with tempfile.TemporaryDirectory() as where:
        loaded = Path(where, "loaded.jsonl")
        loaded.write_text('{"type":"user","message":{"content":'
                          '"<command-name>/valentin-mode</command-name>"}}\n')
        plain = Path(where, "plain.jsonl")
        plain.write_text('{"type":"user","message":{"content":"hello"}}\n')
        try:
            body = {"tool_name": "Bash", "transcript_path": str(loaded),
                    "tool_input": {"command": "python3 -m unittest discover -s tests"}}
            assert gate(body) and "hands work to workers" in gate(body), "valentin-mode blocks tests"
            body["tool_input"] = {"command": "git status"}
            assert gate(body) is None, "reads pass"
            body["transcript_path"] = str(plain)
            body["tool_input"] = {"command": "python3 -m unittest discover -s tests"}
            assert gate(body) is None, "plain chat is not worker-gated"
            body["transcript_path"] = str(loaded)
            body["tool_input"] = {"command": "npm test"}
            os.environ["PACER_GUARD_INLINE"] = "off"
            assert gate(body) is None, "override allows heavy bash"
            del os.environ["PACER_GUARD_INLINE"]
            body = {"tool_name": "Bash", "transcript_path": str(loaded),
                    "tool_input": {"command": "git clone https://github.com/x/y /tmp/y && gh pr checkout 13"},
                    "agent_id": "def456", "agent_type": "general-purpose"}
            assert gate(body) is None, "subagent heavy bash passes with parent valentin transcript"
            body = {"tool_name": "Bash", "transcript_path": str(loaded),
                    "tool_input": {"command": "git clone https://github.com/x/y /tmp/y && gh pr checkout 13"}}
            assert gate(body) and "hands work to workers" in gate(body), "main chat still blocks clones"
        finally:
            os.environ.pop("PACER_GUARD_INLINE", None)
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