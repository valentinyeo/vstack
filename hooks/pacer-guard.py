#!/usr/bin/env python3
"""PreToolUse guard: a chat Valentin talks to never writes code, and stays off heavy Bash.

MULTIPROMPT_TAB set means this is a Valentin-facing Multibot chat, so code-write blocking applies.
Unset means a headless fleet run, so workers stay untouched. A subagent the chat starts (Agent tool) may edit
code only when `plan-pick --claude-helper` exits 0; the chat itself never edits code.
In a valentin-mode chat, Bash that runs tests, builds, linters, installs, git merges, or long loops is blocked;
reads, hypertask, plan-pick, vps-state and board-drain scripts always pass. PACER_GUARD_INLINE=off disables
heavy-Bash blocking.

The rule follows a chat to Codex and Antigravity, which name their tools and send their payloads
their own way: `--harness codex` and `--harness agy` translate one call into the Claude shape and
answer in the harness's blocking format (Codex: exit 2 and stderr; agy: JSON decision on stdout).
Workers stay allowed because plan-pick unsets MULTIPROMPT_TAB for them, on every harness.

pacer-guard.py --self-test"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
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
PICKER_TIMEOUT = 3
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
CODEX = 'codex'
AGY = 'agy'
HARNESSES = (CODEX, AGY)
COMMAND_KEYS = frozenset({'command', 'cmd', 'commandline', 'command_line', 'commands', 'argv'})
PATCH_KEYS = frozenset({'patch', 'patch_text', 'input', 'diff', 'content', 'text', 'code'})
PATCH_FILE = re.compile(r'^\*\*\* (?:Add|Update|Delete) File: (.+)$', re.M)
PATCH_MOVE = re.compile(r'^\*\*\* Move to: (.+)$', re.M)
DIFF_FILE = re.compile(r'^(?:\+\+\+ b/|--- a/)(.+)$', re.M)
# Antigravity names a write tool rather than a tool family, and passes the file under its own key.
AGY_WRITE = frozenset({'write_file', 'create_file', 'replace_file_content', 'multi_replace_file_content',
                       'edit_file', 'apply_patch', 'insert_content', 'delete_file', 'move_file'})
PATH_KEYS = frozenset({'targetfile', 'target_file', 'file_path', 'filepath', 'path', 'absolutepath', 'file'})
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


def picker():
    for candidate in (shutil.which("plan-pick"), Path.home() / ".local" / "bin" / "plan-pick"):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def helper_allowed():
    """plan-pick decides whether a chat may use a Claude helper. Missing, slow or failing means no."""
    found = picker()
    if not found:
        return False
    try:
        answered = subprocess.run([found, "--claude-helper"], capture_output=True, text=True,
                                  timeout=PICKER_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False
    return answered.returncode == 0


def command_of(tool_input):
    """The shell command one harness call carries, or None when it carries no command."""
    if not isinstance(tool_input, dict):
        return None
    for key, value in tool_input.items():
        if str(key).lower() not in COMMAND_KEYS:
            continue
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list) and value and all(isinstance(part, str) for part in value):
            return shlex.join(value)
    return None


def patch_paths(tool_input):
    """Every file an apply_patch call touches, whatever key or harness carries the patch."""
    if isinstance(tool_input, str):
        texts = [tool_input]
    elif isinstance(tool_input, dict):
        texts = [value for key, value in tool_input.items()
                 if str(key).lower() in PATCH_KEYS and isinstance(value, str)]
    else:
        return []
    found = []
    for text in texts:
        found += PATCH_FILE.findall(text) + PATCH_MOVE.findall(text) + DIFF_FILE.findall(text)
    return [clean(path) for path in found if clean(path)]


def task_paths(tool_input):
    """The file an Antigravity write tool names under its own argument key."""
    if not isinstance(tool_input, dict):
        return []
    lowered = {str(key).lower(): value for key, value in tool_input.items()}
    return [clean(lowered[key]) for key in PATH_KEYS
            if isinstance(lowered.get(key), str) and clean(lowered[key])]


def normalized(tool_name, tool_input):
    """One harness call as Claude-shaped (tool, input) calls, by what it does, not by its name."""
    command = command_of(tool_input)
    if command is not None:
        return [('Bash', {'command': command})]
    paths = patch_paths(tool_input)
    if not paths and str(tool_name or '').lower() in AGY_WRITE:
        paths = task_paths(tool_input)
    return [('Write', {'file_path': path}) for path in paths]


def harness_call(payload, harness):
    """The tool name, input and transcript one harness payload carries."""
    if harness == AGY:
        call = payload.get('toolCall') if isinstance(payload.get('toolCall'), dict) else {}
        return call.get('name') or '', call.get('args'), payload.get('transcriptPath')
    return payload.get('tool_name') or '', payload.get('tool_input'), payload.get('transcript_path')


def harness_verdict(payload, harness):
    """Why this harness call is refused, or None. Workers pass because plan-pick unsets MULTIPROMPT_TAB."""
    if not isinstance(payload, dict):
        return None
    tool_name, tool_input, transcript = harness_call(payload, harness)
    for tool, call in normalized(tool_name, tool_input):
        why = gate({'tool_name': tool, 'tool_input': call, 'transcript_path': transcript,
                    'agent_id': payload.get('agent_id'), 'agent_type': payload.get('agent_type')})
        if why:
            return why
    return None


def gate(payload):
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    from_subagent = subagent.from_hook(payload)
    if os.environ.get("MULTIPROMPT_TAB"):
        why = verdict_code(tool_name, tool_input)
        if why and not (from_subagent and helper_allowed()):
            return why
    if from_subagent:
        return None
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
    codex_edit = {'tool_name': 'exec_command', 'tool_input': {
        'command': 'cat > app.ts <<EOF\nexport const a = 1\nEOF'}}
    codex_patch = {'tool_name': 'apply_patch',
                   'tool_input': {'patch': '*** Begin Patch\n*** Update File: hooks/pacer-guard.py\n'
                                           '@@ -1 +1 @@\n*** End Patch\n'}}
    agy_edit = {'toolCall': {'id': 't1', 'name': 'run_command',
                             'args': {'CommandLine': 'printf x > run.sh'}}}
    agy_write = {'toolCall': {'id': 't2', 'name': 'write_file',
                              'args': {'TargetFile': 'web/app.tsx', 'CodeContent': 'export {}\n'}}}
    assert normalized('exec_command', codex_edit['tool_input'])[0][0] == 'Bash', "a codex shell is a Bash"
    assert [path for _tool, call in normalized('apply_patch', codex_patch['tool_input'])
            for path in call.values()] == ['hooks/pacer-guard.py'], "a codex patch names its files"
    assert normalized('write_file', agy_write['toolCall']['args']) == [
        ('Write', {'file_path': 'web/app.tsx'})], "an agy write names its file"
    os.environ['MULTIPROMPT_TAB'] = 'self-test'
    try:
        assert harness_verdict(codex_edit, CODEX) == MESSAGE, "an owner codex shell into code is blocked"
        assert harness_verdict(codex_patch, CODEX) == MESSAGE, "an owner codex patch is blocked"
        assert harness_verdict(agy_edit, AGY) == MESSAGE, "an owner agy shell into code is blocked"
        assert harness_verdict(agy_write, AGY) == MESSAGE, "an owner agy file write is blocked"
        assert harness_verdict({'tool_name': 'exec_command',
                                'tool_input': {'command': 'npm test'}}, CODEX) is None, "a codex read passes"
        assert harness_verdict({'toolCall': {'name': 'view_file',
                                             'args': {'AbsolutePath': '/tmp/x.py'}}}, AGY) is None, \
            "an agy read passes"
    finally:
        os.environ.pop('MULTIPROMPT_TAB', None)
    assert harness_verdict(codex_edit, CODEX) is None, "a worker's codex run is never blocked"
    assert harness_verdict(agy_write, AGY) is None, "a worker's agy run is never blocked"
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
            os.environ["MULTIPROMPT_TAB"] = "self-test"
            keep_path, keep_home = os.environ.get("PATH", ""), os.environ.get("HOME")
            sub_write = {"tool_name": "Write", "transcript_path": str(loaded),
                         "tool_input": {"file_path": "x.py", "content": "print(1)\n"},
                         "agent_id": "def456", "agent_type": "general-purpose"}
            sub_edit = {"tool_name": "Edit", "transcript_path": str(loaded),
                        "tool_input": {"file_path": "hooks/x.py", "old_string": "a", "new_string": "b"},
                        "agent_id": "def456", "agent_type": "general-purpose"}
            main_write = {"tool_name": "Write", "transcript_path": str(loaded),
                          "tool_input": {"file_path": "x.py", "content": "print(1)\n"}}
            try:
                with tempfile.TemporaryDirectory() as pickers:
                    way = Path(pickers, "bin")
                    way.mkdir()
                    os.environ["PATH"] = str(way)
                    os.environ["HOME"] = pickers
                    assert gate(sub_write) == MESSAGE, "no picker means a subagent stays blocked"
                    assert gate(main_write) == MESSAGE, "no picker means the main chat stays blocked"
                    approve = way / "plan-pick"
                    approve.write_text("#!/bin/sh\nexit 0\n")
                    approve.chmod(0o755)
                    assert gate(sub_write) is None, "an approved helper may Write code"
                    assert gate(sub_edit) is None, "an approved helper may Edit code"
                    assert gate(main_write) == MESSAGE, "the main chat never writes code, helper or not"
                    approve.write_text("#!/bin/sh\nexit 1\n")
                    assert gate(sub_write) == MESSAGE, "a refused helper stays blocked"
            finally:
                os.environ["PATH"] = keep_path
                if keep_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = keep_home
        finally:
            os.environ.pop("PACER_GUARD_INLINE", None)
            os.environ.pop("MULTIPROMPT_TAB", None)
    print('pacer-guard self-test ok')


def arguments(argv):
    """The harness this registration serves (None means Claude Code) and the flags left."""
    rest, harness, index = [], None, 0
    while index < len(argv):
        word = argv[index]
        if word == '--harness' and index + 1 < len(argv):
            harness = argv[index + 1]
            index += 2
            continue
        if word.startswith('--harness='):
            harness = word.split('=', 1)[1]
            index += 1
            continue
        rest.append(word)
        index += 1
    return harness, rest


def main():
    harness, rest = arguments(sys.argv[1:])
    if rest == ['--self-test']:
        self_test()
        return 0
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if harness not in HARNESSES:
        why = gate(payload)
        if not why:
            return 0
        print(why, file=sys.stderr)
        return 2
    why = harness_verdict(payload, harness)
    if harness == AGY:
        # Antigravity blocks on a JSON decision, not on an exit status.
        print(json.dumps({'decision': 'deny', 'reason': why} if why else {}))
        return 0
    if not why:
        return 0
    print(why, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())