#!/usr/bin/env python3
"""Keep plan and scope changes in the visible ticket description."""
import html
import json
import re
import shlex
import sys
from pathlib import Path

MESSAGE = 'Plan or scope change: update the ticket description instead.'
MARKER = re.compile(r'(?:^|[\n.!?]\s*|\b)(?:scope\s+(?:add|cut|change|is|includes|now)|(?:new\s+)?plan\s*(?::|\b(?:to|for|is|change)\b)|scope\s*:|fix\s*:|done\s+when\b)', re.I)


def activity_texts(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|()\n')
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []
    texts = []
    for i, token in enumerate(tokens):
        if Path(token).name not in {'hypertask', 'vcc', 'poteto-ticket'}:
            continue
        # Global flags may precede the activity subcommand.
        end = next((j for j in range(i + 1, len(tokens)) if tokens[j] and set(tokens[j]) <= set(';&|()\n')), len(tokens))
        args = tokens[i + 1:end]
        if Path(token).name == 'poteto-ticket':
            if args[:1] != ['log']:
                continue
            args = args[1:]
        else:
            try:
                at = args.index('activity')
            except ValueError:
                continue
            if args[at:at + 2] != ['activity', 'add']:
                continue
            args = args[at + 2:]
        values = []
        positional = []
        j = 0
        while j < len(args):
            arg = args[j]
            option, equals, value = arg.partition('=')
            if option in {'--file', '--text-file', '--text', '--body'}:
                if not equals:
                    if j + 1 >= len(args):
                        break
                    value = args[j + 1]
                    j += 1
                if option in {'--file', '--text-file'}:
                    try:
                        value = Path(value).expanduser().read_text()
                    except OSError:
                        value = ''
                values.append(value)
            elif option in {'--project', '--task', '--ticket', '--kind', '--type', '--run-id'}:
                if not equals:
                    j += 1
            elif not arg.startswith('-'):
                positional.append(arg)
            j += 1
        if positional and re.fullmatch(r'(?:[A-Za-z]+-)?[0-9]+', positional[0]):
            positional.pop(0)
        texts.append('\n'.join(values + positional))
    return texts


def verdict(command):
    for text in activity_texts(command):
        text = html.unescape(re.sub(r'<[^>]+>', '\n', text))
        if MARKER.search(text) or re.search(r'(?:^|\n)\s*(?:scope|plan)\b', text, re.I):
            return MESSAGE
    return None


def self_test():
    import tempfile
    import subprocess
    fixture = Path(__file__).resolve().parents[1] / 'tests/fixtures/soft-2608/scope-add.txt'
    assert verdict('hypertask activity add SOFT-2446 --text ' + shlex.quote(fixture.read_text())) == MESSAGE
    for marker in ['Scope: add X', 'Plan: build X', 'Fix: add X', 'Done when tests pass', 'New plan: X', 'Plan build X', '<h2>Scope</h2><p>Add X</p>']:
        assert verdict('hypertask --token dummy activity add T --text ' + shlex.quote(marker)) == MESSAGE
    assert verdict('bin/poteto-ticket log SOFT-1 "Scope: add X"') == MESSAGE
    for command in ['bin/poteto-ticket log SOFT-1 "CI passed."',
                    'hypertask activity add T --text "CI passed."',
                    'hypertask task update T --description "Plan: X"',
                    'echo "hypertask activity add T Plan: X"', 'echo "unterminated']:
        assert verdict(command) is None, command
    with tempfile.NamedTemporaryFile('w') as f:
        f.write('Scope add: another change'); f.flush()
        assert verdict(f'hypertask activity add T --file {f.name}') == MESSAGE
    r = subprocess.run([sys.executable, __file__], input='{bad json', text=True, capture_output=True)
    assert r.returncode == 0
    print('plan-activity self-test ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get('tool_name') != 'Bash':
        return 0
    tool_input = data.get('tool_input')
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get('command'), str):
        return 0
    why = verdict(tool_input['command'])
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
