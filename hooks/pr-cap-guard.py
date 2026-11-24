#!/usr/bin/env python3
"""PreToolUse guard: no new pull request on a repo that already holds more than its cap.

scripts/pr-cap.py owns the repo table, the cap and the count (one `gh api` search call,
cached 5 minutes, fail open with one warning line). This guard reads the command forms that
open a PR and asks it:

  gh pr create ...                              any -R / --repo form, or the cwd remote
  gh api ... /pulls -X POST | --method POST      a field flag implies POST too
  mcp__*create_pull_request                      owner/repo in the tool input

scripts/worker-shims writes a `gh` shim that calls this guard with `--shim`, so a
plan-pick worker on OpenCode or Antigravity reads the same refusal (VSTA-204).

pr-cap-guard.py --self-test
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cap = load('pr_cap', ROOT / 'scripts/pr-cap.py')
shell = load('test_timeout_guard', ROOT / 'hooks/test-timeout-guard.py')

SHELLS = {'bash', 'sh', 'zsh'}
REMOTE = re.compile(r'github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$')
API_VALUE_FLAGS = {'-X', '--method', '-f', '--field', '-F', '--field-file', '--raw-field',
                   '-H', '--header', '-q', '--jq', '-p', '--preview', '-t', '--template',
                   '--input', '--cache', '-i', '--include', '--hostname'}
POST_FIELDS = {'-f', '--field', '-F', '--field-file', '--raw-field'}


def remote(cwd):
    """owner/name of the cwd's origin remote, or None when git cannot say."""
    try:
        result = subprocess.run(['git', '-C', str(cwd), 'remote', 'get-url', 'origin'],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    match = REMOTE.search((result.stdout or '').strip())
    return match[1] if match else None


def named_repo(args):
    """The repo named by -R / --repo, or None."""
    for index, word in enumerate(args):
        if word in ('-R', '--repo') and index + 1 < len(args):
            return args[index + 1]
        if word.startswith('--repo='):
            return word.split('=', 1)[1]
    return None


def api_call(rest):
    """(repo named by the path or None, whether the call is a POST) for `gh api` arguments."""
    method, posted, path = None, False, None
    index = 0
    while index < len(rest):
        word = rest[index]
        if word in ('-X', '--method') and index + 1 < len(rest):
            method = rest[index + 1]
            index += 2
            continue
        if word.startswith('--method='):
            method = word.split('=', 1)[1]
            index += 1
            continue
        if word.startswith('-X') and len(word) > 2:
            method = word[2:]
            index += 1
            continue
        if word in POST_FIELDS:
            posted = True
            index += 2
            continue
        if word in API_VALUE_FLAGS:
            index += 2
            continue
        if word.startswith('-'):
            index += 1
            continue
        if path is None:
            path = word.lstrip('/')
        index += 1
    if (method or '').upper() != 'POST' and not (method is None and posted):
        return None, False
    if not path or not path.rstrip('/').endswith('/pulls'):
        return None, False
    match = re.match(r'repos/([^/]+/[^/]+)/pulls$', path.rstrip('/'))
    return (match[1] if match else None), True


def check(args, cwd):
    """The refusal for one gh command line, or None."""
    name = Path(args[0]).name
    if name != 'gh':
        return None
    rest = args[1:]
    for index in range(len(rest) - 1):
        if rest[index] == 'pr' and rest[index + 1] == 'create':
            return cap.block(named_repo(rest) or remote(cwd))
    if rest[:1] == ['api']:
        repo, post = api_call(rest[1:])
        return cap.block(repo or remote(cwd)) if post else None
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
        if Path(args[0]).name in SHELLS:
            rest = args[1:]
            if rest[:1] == ['-c'] and len(rest) > 1:
                why = verdict(rest[1], cwd, depth + 1)
                if why:
                    return why
            continue
        why = check(args, cwd)
        if why:
            return why
    return None


def mcp_repo(tool_input):
    """owner/name from an MCP create_pull_request tool input, or None."""
    if not isinstance(tool_input, dict):
        return None
    owner, name = tool_input.get('owner'), tool_input.get('repo')
    if isinstance(owner, str) and isinstance(name, str) and owner and name:
        return f'{owner}/{name}'
    if isinstance(tool_input.get('repository'), str) and '/' in tool_input['repository']:
        return tool_input['repository']
    return None


def shim(argv):
    """Stand in for `gh` in a pacer worker's PATH: refuse a capped create, else exec the real gh."""
    if len(argv) < 2:
        print('pr-cap-guard --shim needs REAL, empty when the host lacks it', file=sys.stderr)
        return 2
    real, args = argv[0], argv[1:]
    why = verdict(' '.join(shlex.quote(word) for word in ['gh'] + args), os.getcwd())
    if why:
        print(why, file=sys.stderr)
        return 2
    if not real:
        print('pr-cap-guard: gh is not installed on this host', file=sys.stderr)
        return 127
    try:
        os.execv(real, [real] + args)
    except OSError as error:
        print(f'pr-cap-guard: cannot run {real}: {error}', file=sys.stderr)
        return 127


def self_test():
    path = ROOT / 'tests/test_pr_cap.py'
    spec = importlib.util.spec_from_file_location('test_pr_cap', path)
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    assert tests.HOOK == str(Path(__file__).resolve()), 'self-test must exercise this file'
    print('pr-cap-guard self-test ok')


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
    if not isinstance(payload, dict):
        return 0
    tool_name = payload.get('tool_name')
    if not isinstance(tool_name, str):
        return 0
    tool_input = payload.get('tool_input')
    why = None
    if tool_name == 'Bash' and isinstance(tool_input, dict) and isinstance(tool_input.get('command'), str):
        cwd = payload.get('cwd')
        why = verdict(tool_input['command'], cwd if isinstance(cwd, str) else '/tmp')
    elif 'create_pull_request' in tool_name:
        repo = mcp_repo(tool_input)
        if repo:
            why = cap.block(repo)
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
