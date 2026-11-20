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

PROBE_TIMEOUT = 5
HOOK_FILE = '$HOME/.claude/hooks/launch-gate.py'
# Fail open when the file is missing: a broken link exits 2 from python, and Claude
# Code reads exit 2 as a block, so the chat can run no Bash at all. exec keeps stdin.
HOOK_COMMAND = 'sh -c \'f="{}"; [ -f "$f" ] || exit 0; exec python3 "$f"\''.format(HOOK_FILE)
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


def project_dir(given):
    if given:
        return Path(given[0]).expanduser().resolve()
    try:
        done = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        done = None
    if done is not None and done.returncode == 0 and done.stdout.strip():
        return Path(done.stdout.strip())
    return Path.cwd()


def read_settings(path):
    """The settings object at path, or None when the file is absent. ValueError when broken."""
    try:
        text = path.read_text()
    except OSError:
        return None
    return json.loads(text)


def gate_items(settings):
    """Every hook item in this settings object that registers launch-gate.py."""
    hooks = settings.get('hooks') if isinstance(settings, dict) else None
    entries = hooks.get('PreToolUse') if isinstance(hooks, dict) else None
    found = []
    for entry in entries if isinstance(entries, list) else []:
        items = entry.get('hooks') if isinstance(entry, dict) else None
        for item in items if isinstance(items, list) else []:
            command = item.get('command') if isinstance(item, dict) else None
            if isinstance(command, str) and 'launch-gate.py' in command:
                found.append(item)
    return found


def registered(settings):
    """This settings object registers the launch-gate hook, in either command form."""
    return bool(gate_items(settings))


def refuse(path, why):
    print('launch-gate: cannot use {}: {}'.format(path, why), file=sys.stderr)
    return 1


def write_settings(path, settings):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + '\n')
    except OSError as error:
        refuse(path, 'it could not be written: {}'.format(error))
        return False
    return True


def install_for_project(given):
    directory = project_dir(given)
    path = directory / '.claude/settings.local.json'
    existed = path.is_file()
    try:
        settings = read_settings(path)
    except ValueError:
        return refuse(path, 'it is not valid JSON; fix it and run this again')
    settings = {} if settings is None else settings
    if not isinstance(settings, dict):
        return refuse(path, 'the top level is not a JSON object')
    items = gate_items(settings)
    old = [item for item in items if item.get('command') != HOOK_COMMAND]
    if old:
        for item in old:
            item['command'] = HOOK_COMMAND
        if not write_settings(path, settings):
            return 1
        print('launch-gate: upgraded the Bash hook in {}'.format(path))
        return 0
    if items:
        print('launch-gate: already registered in {}; nothing changed'.format(path))
        return 0
    hooks = settings.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        return refuse(path, '"hooks" is not an object')
    entries = hooks.setdefault('PreToolUse', [])
    if not isinstance(entries, list):
        return refuse(path, '"hooks.PreToolUse" is not a list')
    entries.append({'matcher': 'Bash',
                    'hooks': [{'type': 'command', 'command': HOOK_COMMAND}]})
    if not write_settings(path, settings):
        return 1
    print('launch-gate: {} the Bash hook in {}'.format(
        'created' if not existed else 'registered', path))
    return 0


def check_project(given):
    directory = project_dir(given)
    for path in (directory / '.claude/settings.json', directory / '.claude/settings.local.json',
                 Path.home() / '.claude/settings.json'):
        try:
            settings = read_settings(path)
        except ValueError:
            continue
        if registered(settings):
            print('launch-gate: {} registers the Bash hook, in {}'.format(directory, path))
            if any(item.get('command') != HOOK_COMMAND for item in gate_items(settings)):
                print('launch-gate: {} has the old command, which blocks every Bash call when '
                      'the file is missing. Upgrade it with: python3 {} '
                      '--install-for-project {}'.format(directory, HOOK_FILE, directory))
            return 0
    print('launch-gate: {} has no launch-gate hook. Install it with: python3 {} '
          '--install-for-project {}'.format(directory, HOOK_FILE, directory))
    return 1


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
        assert [item['command'] for item in gate_items(read_settings(path))] == [HOOK_COMMAND], \
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
    code, text = hook(payload)
    if text:
        print(text, file=sys.stderr)
    return code


if __name__ == '__main__':
    sys.exit(main())
