#!/usr/bin/env python3
"""PreToolUse gate: no chat starts a worker or a heavy job while the server is full.

A Bash call that starts a worker, a build or a test run asks
`vps-state --can-launch worker --no-write` first. HOLD (exit 2) blocks the call.
ADD, CAREFUL, a probe failure and a timeout all allow it, and a failure says so on
stderr. LAUNCH_GATE=off lifts the gate, in the environment or as a leading assignment.
A read or a mention never costs a probe.

    launch-gate.py --install-for-project [DIR]   register this hook for one project
    launch-gate.py --check-project [DIR]         exit 0 when DIR has the hook
    launch-gate.py --self-test
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

_PROJECT_HOOKS_MODULE = None


def ph():
    """Load hooks/project_hooks.py when install, check or heal need it."""
    global _PROJECT_HOOKS_MODULE
    if _PROJECT_HOOKS_MODULE is not None:
        return _PROJECT_HOOKS_MODULE
    here = Path(__file__).resolve().parent
    for candidate in (here / 'project_hooks.py', here.parent / 'hooks' / 'project_hooks.py'):
        if not candidate.is_file():
            continue
        loader = importlib.machinery.SourceFileLoader('project_hooks', str(candidate))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        _PROJECT_HOOKS_MODULE = module
        return module
    raise ModuleNotFoundError('project_hooks.py')


PROBE_TIMEOUT = 5
HOOK_BASENAME = 'launch-gate.py'
HOOK_PREFIX = 'launch-gate'
HOOK_FILE = '$HOME/.claude/hooks/launch-gate.py'
HOOK_COMMAND = (
    "sh -c 'f=\"" + HOOK_FILE + "\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\"'"
)
OLD_COMMAND = HOOK_FILE
MESSAGE = ('BLOCKED by launch-gate: server is full ({brief}). Start nothing new. '
           'Finish, merge or clean up what you have, tell the user you are holding, '
           'run vps-state again in 10 minutes. Only the user can lift this: LAUNCH_GATE=off.')
ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
PACKAGE_MANAGERS = frozenset(('npm', 'pnpm', 'yarn', 'bun'))
PACKAGE_SCRIPTS = frozenset(('build', 'test'))
WHOLE_COMMAND = frozenset(('cursor-agent', 'hax', 'jest', 'make', 'pytest', 'spawn-worker', 'vitest'))
BUILD_SUBCOMMAND = {
    'cargo': ('build', 'test'),
    'go': ('test',),
    'next': ('build',),
    'playwright': ('test',),
    'tsc': ('-b', '--build'),
    'turbo': ('run',),
    'vite': ('build',),
    'zig': ('build',),
}
READ_ONLY = frozenset((
    'ag', 'awk', 'basename', 'cat', 'cmp', 'cut', 'diff', 'dirname', 'echo', 'egrep', 'fgrep',
    'file', 'find', 'git', 'gh', 'grep', 'head', 'jq', 'ls', 'md5sum', 'printf', 'pwd',
    'readlink', 'realpath', 'rg', 'sed', 'sha256sum', 'sort', 'stat', 'tail', 'tr', 'tree',
    'uniq', 'wc', 'which', 'whoami',
))


def load_launch_argv():
    """book-check's argv splitter, so a wrapper chain splits the same way in both hooks."""
    path = Path(__file__).resolve().parent / 'book-check.py'
    loader = importlib.machinery.SourceFileLoader('book_check_for_launch_gate', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.launch_argv


try:
    launch_argv = load_launch_argv()
except (OSError, ImportError, AttributeError, SyntaxError):
    launch_argv = None


def package_target(args):
    """The argv a package manager runs, or None when it runs no script."""
    rest = args[1:]
    if rest[:1] and rest[0] in PACKAGE_SCRIPTS:
        return rest
    for marker in ('run', 'exec'):
        if marker in rest:
            target = [word for word in rest[rest.index(marker) + 1:] if not word.startswith('-')]
            return target or None
    return None


def heavy(args, depth=0):
    """This argv starts a worker, a build or a test run."""
    if not args or depth > 2:
        return False
    name = Path(args[0]).name
    rest = args[1:]
    if name in PACKAGE_MANAGERS:
        target = package_target(args)
        if not target:
            return False
        if Path(target[0]).name in PACKAGE_SCRIPTS:
            return True
        return heavy(target, depth + 1)
    if name in WHOLE_COMMAND:
        return True
    if name == 'plan-pick':
        return any(word == '--run' or word.startswith('--run=') for word in rest)
    if name in ('pi', 'claude'):
        return bool({'-p', '--print'}.intersection(rest))
    if name == 'codex':
        return 'exec' in rest
    if name in ('python', 'python3'):
        return rest[:2] == ['-m', 'unittest']
    wanted = BUILD_SUBCOMMAND.get(name) or ()
    return any(word in wanted for word in rest)


def starts_launch(command):
    """Any argv in this command line starts a worker, a build or a test run."""
    if launch_argv is None:
        return False
    for args in launch_argv(command):
        if Path(args[0]).name in READ_ONLY:
            continue
        if heavy(args):
            return True
    return False


def overridden(command):
    """The user lifted the gate, in the environment or as a leading assignment."""
    if os.environ.get('LAUNCH_GATE') == 'off':
        return True
    words = command.split()
    index = 0
    while index < len(words) and (words[index] == 'env' or ASSIGNMENT.match(words[index])):
        key, _, value = words[index].partition('=')
        if key == 'LAUNCH_GATE' and value.strip('\'"') == 'off':
            return True
        index += 1
    return False


def resolve_vps_state():
    override = os.environ.get('LAUNCH_GATE_VPS_STATE')
    if override:
        return override
    found = shutil.which('vps-state')
    if found:
        return found
    for candidate in (Path.home() / '.local/bin/vps-state',
                      Path(__file__).resolve().parents[1] / 'skills/vps-state/vps-state'):
        if candidate.is_file():
            return str(candidate)
    return None


def probe(path, *args):
    """vps-state's answer, or 'timeout' or 'missing' when it did not answer."""
    try:
        return subprocess.run([path, *args], capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 'timeout'
    except (OSError, subprocess.SubprocessError):
        return 'missing'


def decide(command):
    """('allow', None), ('block', message) or ('warn', one line) for one command."""
    if not starts_launch(command):
        return 'allow', None
    path = resolve_vps_state()
    if not path:
        return 'warn', 'launch-gate: vps-state was not found, so this launch was not checked'
    answer = probe(path, '--can-launch', 'worker', '--no-write')
    if answer == 'timeout':
        return 'warn', ('launch-gate: vps-state did not answer in {}s, so this launch was not '
                        'checked'.format(PROBE_TIMEOUT))
    if answer == 'missing':
        return 'warn', 'launch-gate: could not run {}, so this launch was not checked'.format(path)
    if answer.returncode == 2:
        brief = probe(path, '--brief', '--no-write')
        line = getattr(brief, 'stdout', '').strip() or 'no reason given'
        return 'block', MESSAGE.format(brief=line)
    if answer.returncode in (0, 1):
        return 'allow', None
    return 'warn', ('launch-gate: vps-state exited {}, so this launch was not '
                    'checked'.format(answer.returncode))


def hook(payload):
    """Exit code and stderr for one PreToolUse payload."""
    if not isinstance(payload, dict) or payload.get('tool_name') != 'Bash':
        return 0, ''
    tool_input = payload.get('tool_input')
    command = tool_input.get('command') if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip() or overridden(command):
        return 0, ''
    if launch_argv is None:
        return 0, 'launch-gate: cannot read hooks/book-check.py, so no launch was checked'
    action, text = decide(command)
    return (2 if action == 'block' else 0), text or ''


def read_settings(path):
    return ph().read_settings(path)


def gate_items(settings):
    return ph().gate_items(settings, HOOK_BASENAME)


def upgrade_launch_gate_commands(settings):
    return ph().upgrade_hook_commands(settings, HOOK_BASENAME, HOOK_COMMAND)


def hook_project_dir(payload):
    """The project directory for an in-hook heal, or None when none is known."""
    env_dir = (os.environ.get('CLAUDE_PROJECT_DIR') or '').strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    if isinstance(payload, dict):
        cwd = payload.get('cwd')
        if isinstance(cwd, str) and cwd.strip():
            return Path(cwd).expanduser().resolve()
    try:
        return Path.cwd()
    except OSError:
        return None


def write_settings_atomic(path, settings):
    ph().write_settings_atomic(path, settings)


def heal_project_settings(payload):
    """Upgrade a stale launch-gate command in the project's settings.local.json. Errors stay quiet."""
    try:
        ph()
    except ModuleNotFoundError:
        return
    directory = hook_project_dir(payload)
    if directory is None:
        return
    path = directory / '.claude/settings.local.json'
    if path.is_symlink():
        try:
            path = path.resolve()
        except OSError:
            return
    try:
        text = path.read_text()
    except (OSError, UnicodeError):
        return
    if 'launch-gate' not in text or HOOK_COMMAND in text:
        return
    try:
        settings = json.loads(text)
    except ValueError:
        return
    if not isinstance(settings, dict):
        return
    if not upgrade_launch_gate_commands(settings):
        return
    try:
        write_settings_atomic(path, settings)
    except OSError:
        print('launch-gate: could not heal {}'.format(path), file=sys.stderr)


def registered(settings):
    return ph().registered(settings, HOOK_BASENAME)


def install_for_project(given):
    return ph().install_for_project(
        given, prefix=HOOK_PREFIX, hook_substring=HOOK_BASENAME,
        hook_file=HOOK_FILE, hook_command=HOOK_COMMAND)


def check_project(given):
    return ph().check_project(
        given, prefix=HOOK_PREFIX, hook_substring=HOOK_BASENAME,
        hook_file=HOOK_FILE, hook_command=HOOK_COMMAND,
        hook_label='launch-gate hook')


def self_test():
    saved = os.environ.pop('LAUNCH_GATE', None)
    for command in ('~/.local/bin/plan-pick --run', 'cursor-agent -p x', 'pi -p x', 'codex exec x',
                    'spawn-worker brief.txt', 'pnpm --filter web exec vite build', 'npm run build',
                    'tsc --build', 'cargo test', 'go test ./...', 'make', 'pytest -q',
                    'python3 -m unittest discover', 'timeout 600 jest', 'cd web && vite build'):
        assert starts_launch(command), command + ' starts heavy work and must be gated'
    for command in ('grep -rn pytest hooks/', 'cat package.json', 'git log --oneline',
                    'gh pr checks 4', 'echo "make build"', 'ls', 'npm run lint', 'cargo --version'):
        assert not starts_launch(command), command + ' launches nothing and must pass'
    text = MESSAGE.format(brief='HOLD worker, HOLD chat: load5 40.10')
    assert text.startswith('BLOCKED by launch-gate: server is full (HOLD worker'), text
    assert 'run vps-state again in 10 minutes' in text
    assert text.endswith('Only the user can lift this: LAUNCH_GATE=off.'), text
    assert overridden('LAUNCH_GATE=off pytest'), 'a leading assignment lifts the gate'
    assert overridden('env LAUNCH_GATE=off pytest'), 'env LAUNCH_GATE=off lifts the gate'
    assert not overridden('pytest'), 'a plain launch keeps the gate on'
    os.environ['LAUNCH_GATE'] = 'off'
    assert overridden('pytest'), 'the environment lifts the gate'
    if saved is None:
        del os.environ['LAUNCH_GATE']
    else:
        os.environ['LAUNCH_GATE'] = saved
    assert hook({'tool_name': 'Write', 'tool_input': {}}) == (0, ''), 'only Bash is gated'
    payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'pytest -q'}})
    with tempfile.TemporaryDirectory() as where:
        absent = subprocess.run(['sh', '-c', HOOK_COMMAND], input=payload, capture_output=True,
                                text=True, timeout=30,
                                env={'HOME': where, 'PATH': os.environ.get('PATH', '')})
        assert absent.returncode == 0, 'a missing hook file must not block: ' + absent.stderr
        assert absent.stderr == '', absent.stderr
        assert install_for_project([where]) == 0, 'install writes project settings'
        assert check_project([where]) == 0, 'check sees the hook it just installed'
        path = Path(where) / '.claude/settings.local.json'
        assert path.is_file(), 'settings file exists'
        assert [item['command'] for item in gate_items(ph().read_settings(path))] == [HOOK_COMMAND], \
            'install writes the fail-open command'
    with tempfile.TemporaryDirectory() as where:
        path = Path(where) / '.claude/settings.local.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'hooks': {'PreToolUse': [
            {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': OLD_COMMAND}]}]}}))
        assert check_project([where]) == 0, 'check accepts the old command form'
        assert install_for_project([where]) == 0, 'install upgrades the old command'
        found = gate_items(read_settings(path))
        assert [item['command'] for item in found] == [HOOK_COMMAND], 'the old command is replaced'
    print('launch-gate self-test ok')


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
        print('launch-gate: unknown argument {!r}; nothing was done'.format(args[0]),
              file=sys.stderr)
        return 0
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    heal_project_settings(payload)
    code, text = hook(payload)
    if text:
        print(text, file=sys.stderr)
    return code


if __name__ == '__main__':
    sys.exit(main())
