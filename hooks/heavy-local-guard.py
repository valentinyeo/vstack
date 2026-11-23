#!/usr/bin/env python3
"""PreToolUse Bash guard: route heavy local jobs to GitHub before they start.

VSTA-162 put the guard in front of every chat's Bash. VSTA-165 moved the blocked list
into config/heavy-local.json, added `--shim` so pacer workers on harnesses that never
run Claude hooks get the same refusal, and moved the only exceptions into
config/heavy-local-allow.txt, one line each with its reason.

A worker shim sees only its own words (never a wrapping `timeout`), so the `timeout` <= 90s
exception for one named test file reaches a chat and not a shim: a worker pushes and reads CI.

heavy-local-guard.py --self-test
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import sys

_spec = importlib.util.spec_from_file_location(
    'test_timeout_guard', Path(__file__).resolve().with_name('test-timeout-guard.py'))
shell = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shell)

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / 'config/heavy-local.json'
ALLOW_FILE = ROOT / 'config/heavy-local-allow.txt'
HYPERTASK = Path('/home/valentin/projects/hypertask')
PACKAGE_OPTIONS = {'--prefix', '--cwd', '--dir', '-C', '--cache', '--userconfig',
                   '--workspace', '-w', '--package', '-p'}
HYPERTASK_SUITES = {'next', 'tsc', 'vitest', 'vitest.mjs', 'jest', 'jest.js', 'playwright',
                    'premerge-local.sh'}


def read_rules():
    """The blocked list and the exceptions, or (None, ()) when the data file is gone.

    A missing data file fails open, the way a missing hook link does: Bash stays usable
    and enforcement resumes as soon as the shared install has the file again.
    """
    try:
        data = json.loads(DATA_FILE.read_text())
    except (OSError, ValueError):
        return None, ()
    allow = []
    try:
        lines = ALLOW_FILE.read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or ' | ' not in line:
            continue
        pattern = line.rsplit(' | ', 1)[0]
        try:
            allow.append(re.compile(pattern))
        except re.error:
            continue
    return data, tuple(allow)


DATA, ALLOW = read_rules()
MESSAGE = (DATA or {}).get('message', 'BLOCKED by heavy-local-guard: {runner} runs on GitHub.')
ALWAYS = set((DATA or {}).get('always', ()))
VERBS = (DATA or {}).get('verbs', {})
PACKAGE_MANAGERS = set((DATA or {}).get('package_managers', ()))
PACKAGE_VERBS = set((DATA or {}).get('package_verbs', ()))
PY_MODULES = set((DATA or {}).get('python_modules', ()))
STANDALONE = set((DATA or {}).get('standalone', ()))
SCRIPTS = tuple((DATA or {}).get('scripts', ()))
SUFFIXES = tuple((DATA or {}).get('suffixes', ()))


def message(runner):
    return MESSAGE.format(runner=runner)


def exempt(args):
    """True when an allow line names this command; every line carries its reason."""
    line = ' '.join(args)
    return any(pattern.fullmatch(line) for pattern in ALLOW)


def positionals(args, value_options):
    """Arguments after leading options, with option values kept out of command position."""
    while args and args[0].startswith('-'):
        option = args[0]
        args = args[2:] if option in value_options else args[1:]
        if option == '--':
            break
    return args


def script(word):
    """True when a path names a script this host may not run."""
    return bool(SCRIPTS) and (Path(word).name in ALWAYS or word.endswith(SCRIPTS))


def heavy(args, cwd, depth):
    if not args:
        return None
    name, rest = Path(args[0]).name, args[1:]
    if script(args[0]):
        return message(name)
    if name in shell.SHELLS:
        while rest:
            word, rest = rest[0], rest[1:]
            if word in {'-o', '-O', '--rcfile', '--init-file'}:
                rest = rest[1:]
            elif word.startswith('-') and not word.startswith('--') and 'c' in word:
                return verdict(rest[0], cwd, depth + 1) if rest else None
            elif not word.startswith('-'):
                return message(Path(word).name) if script(word) else None
        return None
    if name in {'node', 'nodejs'} and '--test' not in rest:
        head = positionals(rest, {'--require', '-r', '--import', '--loader',
                                  '--experimental-loader', '--title'})
        if head and not any(flag in rest for flag in ('-e', '--eval', '-p', '--print')):
            return heavy(head, cwd, depth)
    name = {'npm-cli.js': 'npm', 'npx-cli.js': 'npx'}.get(name, name)
    if name in ALWAYS or (SUFFIXES and name.endswith(SUFFIXES)):
        return message(name)
    if name == 'java' and any('gradle' in word.lower() for word in rest):
        return message('java Gradle')
    verbs = VERBS.get(name)
    if verbs and rest and rest[0] in verbs:
        return message(f'{name} {rest[0]}')
    if name == 'make':
        targets = positionals(rest, {'-f', '--file', '-C', '--directory', '-j', '--jobs'})
        if not targets or any(word in verbs for word in targets):
            return message('make build')
    if name in STANDALONE:
        return message(name)
    if name.startswith('python'):
        for index, word in enumerate(rest):
            if word == '-m' and index + 1 < len(rest) and rest[index + 1] in PY_MODULES:
                return message(f'{name} -m {rest[index + 1]}')
    if name in PACKAGE_MANAGERS | {'npx'}:
        for index, word in enumerate(rest):
            if word in {'--prefix', '--cwd', '--dir', '-C'} and index + 1 < len(rest):
                cwd = str(Path(cwd) / rest[index + 1])
            elif word.startswith(('--prefix=', '--cwd=', '--dir=')):
                cwd = str(Path(cwd) / word.split('=', 1)[1])
        rest = positionals(rest, PACKAGE_OPTIONS)
        if rest[:1] == ['exec']:
            return heavy(positionals(rest[1:], PACKAGE_OPTIONS), cwd, depth) if len(rest) > 1 else None
        if rest[:1] == ['run']:
            rest = positionals(rest[1:], set())
        if rest and (rest[0] in PACKAGE_VERBS or rest[0].startswith(('build:', 'test:'))):
            return message(f'{name} {rest[0]}')
        if name == 'npx' and rest:
            return heavy(rest, cwd, depth)
    project = Path(os.path.normpath(cwd))
    if project == HYPERTASK or HYPERTASK in project.parents:
        if (name in HYPERTASK_SUITES
                or (name in {'node', 'nodejs'} and '--test' in rest)
                or (name in PACKAGE_MANAGERS and rest and rest[0] in {'test', 't', 'lint'})):
            return message(f'{name} full suite')
    return None


def verdict(command, cwd='/tmp', depth=0):
    if depth > 8 or DATA is None:
        return None
    for args in shell.simple_commands(command):
        if exempt(args):
            continue
        args, _wrapped = shell.strip_wrappers(args)
        if not args:
            continue
        if args[0] == 'cd' and len(args) == 2:
            cwd = str(Path(cwd) / args[1])
            continue
        why = heavy(args, cwd, depth)
        if why:
            return why
    return None


def shim(argv):
    """Stand in for one command in a pacer worker's PATH: refuse heavy, else exec the real one."""
    if len(argv) < 2:
        print('heavy-local-guard --shim needs NAME and the real path, empty when the host lacks it',
              file=sys.stderr)
        return 2
    name, real, args = argv[0], argv[1], argv[2:]
    why = verdict(' '.join(shlex.quote(word) for word in [name] + args))
    if why:
        print(why, file=sys.stderr)
        return 2
    if not real:
        print(f'heavy-local-guard: {name} is not installed on this host', file=sys.stderr)
        return 127
    try:
        os.execv(real, [real] + args)
    except OSError as exc:
        print(f'heavy-local-guard: cannot run {real}: {exc}', file=sys.stderr)
        return 127


def self_test():
    path = ROOT / 'tests/test_heavy_local_guard.py'
    spec = importlib.util.spec_from_file_location('test_heavy_local_guard', path)
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    assert DATA is not None, 'config/heavy-local.json is missing'
    for command in tests.BLOCKED:
        assert verdict(command), f'must block: {command}'
        assert len(verdict(command).splitlines()) == 1, f'one line: {command}'
    for command in tests.ALLOWED:
        assert verdict(command) is None, f'must allow: {command}'
    for line in ALLOW_FILE.read_text().splitlines():
        if line.strip() and not line.strip().startswith('#'):
            assert line.strip().rsplit(' | ', 1)[1].strip(), f'no reason: {line}'
    print('heavy-local-guard self-test ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
    if sys.argv[1:2] == ['--shim']:
        return shim(sys.argv[2:])
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict) or payload.get('tool_name') != 'Bash':
        return 0
    tool_input = payload.get('tool_input')
    command = tool_input.get('command') if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    cwd = payload.get('cwd')
    why = verdict(command, cwd if isinstance(cwd, str) else '/tmp')
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
