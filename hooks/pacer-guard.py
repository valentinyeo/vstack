#!/usr/bin/env python3
"""PreToolUse guard: a chat Valentin talks to never writes code. Code goes to plan-pick workers.

MULTIPROMPT_TAB set means this is a Valentin-facing Multibot chat, so the guard applies.
Unset means a headless fleet run, so every call passes and workers stay untouched.
A code file is a known code extension, a workflow under .github/workflows/, or a
shebang file with no extension. Docs, notes and data are never code. Files under /tmp
are still checked. This is a seatbelt, not a sandbox.

pacer-guard.py --self-test"""
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile

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


def clean(path):
    """A path token without shell quoting."""
    return str(path or '').strip().strip('\'"').strip()


def is_code(path, content=None):
    """This path is a code file. `content` is the text a Write would put there."""
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
    """Shell words, with redirection and control operators kept as their own tokens."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=PUNCTUATION)
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return re.findall(r'>>?|[^\s;&|()<>]+', command)


def tee_paths(args):
    """The files `tee` writes: every non-flag argument, before the next operator."""
    found = []
    for token in args:
        if token in STOP:
            break
        if not token.startswith('-'):
            found.append(token)
    return found


def inplace_paths(args):
    """The files `sed -i` or `perl -i` rewrites. A script argument is skipped, never a target."""
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
    """Every path this Bash command writes through redirection, tee, or an in-place edit."""
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


def verdict(tool_name, tool_input):
    """Why this call is blocked, or None."""
    if tool_name in FILE_TOOLS:
        path = tool_input.get('file_path') or tool_input.get('notebook_path') or ''
        content = tool_input.get('content') if tool_name == 'Write' else None
        return MESSAGE if is_code(path, content) else None
    if tool_name == 'Bash':
        command = tool_input.get('command') or ''
        return MESSAGE if any(is_code(path) for path in bash_paths(command)) else None
    return None


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
    assert verdict('Write', {'file_path': 'x.py'}) == MESSAGE, "a code Write is blocked"
    assert verdict('Edit', {'file_path': 'notes.md'}) is None, "a docs Edit passes"
    assert verdict('MultiEdit', {'file_path': 'a/go.mod'}) is None, "an unknown extension passes"
    assert verdict('NotebookEdit', {'notebook_path': 'lab.py'}) == MESSAGE, "a notebook code edit is blocked"
    assert verdict('Read', {'file_path': 'x.py'}) is None, "reading code passes"
    assert verdict('Bash', {'command': 'cat > foo.sh <<EOF\n#!/bin/sh\nEOF'}) == MESSAGE, "a heredoc into code is blocked"
    assert verdict('Bash', {'command': 'ls > out.txt'}) is None, "redirecting docs passes"
    assert verdict('Bash', {'command': 'echo x | tee app.js'}) == MESSAGE, "tee into code is blocked"
    assert verdict('Bash', {'command': "sed -i 's/a/b/' run.py"}) == MESSAGE, "an in-place edit of code is blocked"
    assert verdict('Bash', {'command': "sed -n 's/a/b/p' run.py"}) is None, "a plain sed read passes"
    assert verdict('Bash', {'command': 'python3 hooks/pacer-guard.py --self-test'}) is None, "running code passes"
    print('pacer-guard self-test ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
    if not os.environ.get('MULTIPROMPT_TAB'):
        return 0
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get('tool_input')
    why = verdict(payload.get('tool_name') or '', tool_input if isinstance(tool_input, dict) else {})
    if not why:
        return 0
    print(why, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
