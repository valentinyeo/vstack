#!/usr/bin/env python3
"""Route Bash ticket writes through bin/poteto-ticket."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXES = {
    ('task', 'create'): 'new "<brief>"',
    ('task', 'update'): 'claim <id>, review <id>, done <id> "<verdict URL>", or ask <id> "<question>"',
    ('task', 'move'): 'review <id>, done <id> "<verdict URL>", or ask <id> "<question>"',
    ('task', 'assign'): 'claim <id>',
    ('comment', 'add'): 'log <id> "<status>", done <id> "<verdict URL>", or ask <id> "<question>"',
    ('activity', 'add'): 'log <id> "<text>"',
    ('agent', 'take'): 'claim <id>',
    ('agent', 'move'): 'review <id>',
    ('agent', 'say'): 'log <id> "<text>"',
}
ASSIGN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=(.*)$', re.S)
VARIABLE = re.compile(r'\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))')


def violation(command, variables=None, depth=0):
    if depth > 8:
        return None
    variables = dict(variables or {})
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|()\n')
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    start = True
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token and all(c in ';&|()\n' for c in token):
            start = True
            i += 1
            continue
        token = VARIABLE.sub(lambda m: variables.get(m[1] or m[2], m[0]), token)
        assignment = ASSIGN.match(token)
        if start and assignment:
            variables[token.split('=', 1)[0]] = assignment[1]
            i += 1
            continue
        if start and token.startswith('-'):
            i += 2 if token in {'-u', '--unset', '--user', '-g', '--group'} else 1
            continue
        name = token.rsplit('/', 1)[-1]
        if start and name in {'export', 'env', 'command', 'exec', 'nohup', 'sudo'}:
            i += 1
            continue
        if start and name == 'timeout':
            i += 2
            continue
        if start and name in {'sh', 'bash', 'dash', 'zsh'}:
            for j in range(i + 1, len(tokens) - 1):
                if tokens[j].startswith('-') and 'c' in tokens[j][1:]:
                    found = violation(tokens[j + 1], variables, depth + 1)
                    if found:
                        return found
                    break
        if start and name == 'hypertask':
            words = []
            j = i + 1
            while j < len(tokens) and len(words) < 2:
                word = tokens[j]
                if word in {'--token', '--api-url'}:
                    j += 2
                    continue
                if word.startswith('-'):
                    j += 1
                    continue
                if word and all(c in ';&|()\n' for c in word):
                    break
                words.append(word)
                j += 1
            end = next((k for k in range(j, len(tokens))
                        if tokens[k] and all(c in ';&|()\n' for c in tokens[k])), len(tokens))
            fix = FIXES.get(tuple(words))
            if fix and not any(t in {'--help', '-h'} for t in tokens[i + 1:end]):
                return f'Use bin/poteto-ticket {fix}. Raw Hypertask ticket writes are blocked here.'
        start = False
        i += 1
    return None


def main():
    if sys.argv[1:] == ['--self-test']:
        return subprocess.call([sys.executable, str(ROOT / 'tests/test_ticket_way.py')])
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get('tool_name') != 'Bash':
        return 0
    message = violation((data.get('tool_input') or {}).get('command', ''))
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
