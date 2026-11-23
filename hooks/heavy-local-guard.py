#!/usr/bin/env python3
"""PreToolUse Bash guard: route heavy local jobs to GitHub before they start.

VSTA-162 replaces reliance on the host's process killer with each chat's own
registration. Command matching follows ceo/bin/heavy-guard for Zig, Gradle,
Wine and Hypertask suites, and also covers common full-app build entry points.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys

_spec = importlib.util.spec_from_file_location(
    'test_timeout_guard', Path(__file__).resolve().with_name('test-timeout-guard.py'))
shell = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shell)

MESSAGE = ('BLOCKED by heavy-local-guard: {runner} belongs on GitHub free runners, not this host; '
           'push and let CI run, or use `gh workflow run <workflow> --ref <branch>`.')
WINE = {'wine', 'wine64', 'wineserver', 'wineserver64', 'wine-preloader', 'wine64-preloader'}
BUILD = {
    'zig': {'build', 'test', 'build-exe', 'run'},
    'cargo': {'build'}, 'go': {'build'}, 'next': {'build'}, 'vite': {'build'},
    'ng': {'build'}, 'dotnet': {'build', 'publish'}, 'flutter': {'build'},
}
PACKAGE_OPTIONS = {'--prefix', '--cwd', '--dir', '-C', '--cache', '--userconfig',
                   '--workspace', '-w', '--package', '-p'}
HYPERTASK = Path('/home/valentin/projects/hypertask')


def positionals(args, value_options):
    """Arguments after leading options, with option values kept out of command position."""
    while args and args[0].startswith('-'):
        option = args[0]
        args = args[2:] if option in value_options else args[1:]
        if option == '--':
            break
    return args


def heavy(args, cwd, depth):
    if not args:
        return None
    name, rest = Path(args[0]).name, args[1:]
    if name in shell.SHELLS:
        while rest:
            word, rest = rest[0], rest[1:]
            if word in {'-o', '-O', '--rcfile', '--init-file'}:
                rest = rest[1:]
            elif word.startswith('-') and not word.startswith('--') and 'c' in word:
                return verdict(rest[0], cwd, depth + 1) if rest else None
            elif not word.startswith('-'):
                return MESSAGE.format(runner=word) if Path(word).name in {'gradle', 'gradlew'} else None
        return None
    if name in {'node', 'nodejs'} and '--test' not in rest:
        script = positionals(rest, {'--require', '-r', '--import', '--loader',
                                    '--experimental-loader', '--title'})
        if script and not any(flag in rest for flag in ('-e', '--eval', '-p', '--print')):
            return heavy(script, cwd, depth)
    name = {'npm-cli.js': 'npm', 'npx-cli.js': 'npx'}.get(name, name)
    if name in {'gradle', 'gradlew', 'gradle.bat', 'gradlew.bat'} or name in WINE:
        return MESSAGE.format(runner=name)
    if name == 'java' and any('gradle' in word.lower() for word in rest):
        return MESSAGE.format(runner='java Gradle')
    if name in BUILD and rest and rest[0] in BUILD[name]:
        return MESSAGE.format(runner=f'{name} {rest[0]}')
    if name == 'xcodebuild' or (name == 'cmake' and '--build' in rest):
        return MESSAGE.format(runner=name)
    if name == 'make':
        targets = positionals(rest, {'-f', '--file', '-C', '--directory', '-j', '--jobs'})
        if not targets or any(word in {'all', 'build'} for word in targets):
            return MESSAGE.format(runner='make build')
    if name in shell.PACKAGE_MANAGERS | {'npx'}:
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
        if rest and (rest[0] == 'build' or rest[0].startswith('build:')):
            return MESSAGE.format(runner=f'{name} build')
        if name == 'npx' and rest:
            return heavy(rest, cwd, depth)
    project = Path(os.path.normpath(cwd))
    if project == HYPERTASK or HYPERTASK in project.parents:
        if (name in {'next', 'tsc', 'vitest', 'vitest.mjs', 'jest', 'jest.js', 'playwright',
                     'premerge-local.sh'}
                or (name in {'node', 'nodejs'} and '--test' in rest)
                or (name in shell.PACKAGE_MANAGERS and rest and rest[0] in {'test', 't', 'lint'})):
            return MESSAGE.format(runner=f'{name} full suite')
    return None


def verdict(command, cwd='/tmp', depth=0):
    if depth > 8:
        return None
    for args in shell.simple_commands(command):
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


def self_test():
    path = Path(__file__).resolve().parents[1] / 'tests/test_heavy_local_guard.py'
    spec = importlib.util.spec_from_file_location('test_heavy_local_guard', path)
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    for command in tests.BLOCKED:
        assert verdict(command), f'must block: {command}'
    for command in tests.ALLOWED:
        assert verdict(command) is None, f'must allow: {command}'
    print('heavy-local-guard self-test ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
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
