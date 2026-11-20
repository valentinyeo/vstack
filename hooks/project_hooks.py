"""Register a vstack PreToolUse hook in a project's .claude/settings.local.json."""
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


def hook_spec(hook_basename):
    """Fail-open command shape and paths for one hook file under ~/.claude/hooks/."""
    hook_file = '$HOME/.claude/hooks/' + hook_basename
    hook_command = (
        "sh -c 'f=\"" + hook_file + "\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\"'"
    )
    return hook_file, hook_command


def project_dir(given):
    if given:
        return Path(given[0]).expanduser().resolve()
    try:
        done = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            timeout=5,
        )
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


def gate_items(settings, hook_substring):
    """Every hook item in this settings object that registers hook_substring."""
    hooks = settings.get('hooks') if isinstance(settings, dict) else None
    entries = hooks.get('PreToolUse') if isinstance(hooks, dict) else None
    found = []
    for entry in entries if isinstance(entries, list) else []:
        items = entry.get('hooks') if isinstance(entry, dict) else None
        for item in items if isinstance(items, list) else []:
            command = item.get('command') if isinstance(item, dict) else None
            if isinstance(command, str) and hook_substring in command:
                found.append(item)
    return found


def upgrade_hook_commands(settings, hook_substring, hook_command):
    """Replace stale hook commands with hook_command. Return True when any changed."""
    items = gate_items(settings, hook_substring)
    stale = [item for item in items if item.get('command') != hook_command]
    if not stale:
        return False
    for item in stale:
        item['command'] = hook_command
    return True


def registered(settings, hook_substring):
    return bool(gate_items(settings, hook_substring))


def refuse(prefix, path, why):
    print('{}: cannot use {}: {}'.format(prefix, path, why), file=sys.stderr)
    return 1


def write_settings(path, settings, prefix):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + '\n')
    except OSError as error:
        refuse(prefix, path, 'it could not be written: {}'.format(error))
        return False
    return True


def write_settings_atomic(path, settings):
    """Write settings to path with a temp file and os.replace, keeping the file mode."""
    text = json.dumps(settings, indent=2) + '\n'
    mode = stat.S_IMODE(path.stat().st_mode) if path.is_file() else 0o644
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.settings.local.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install_for_project(given, *, prefix, hook_substring, hook_file, hook_command):
    directory = project_dir(given)
    path = directory / '.claude/settings.local.json'
    existed = path.is_file()
    try:
        settings = read_settings(path)
    except ValueError:
        return refuse(prefix, path, 'it is not valid JSON; fix it and run this again')
    settings = {} if settings is None else settings
    if not isinstance(settings, dict):
        return refuse(prefix, path, 'the top level is not a JSON object')
    if upgrade_hook_commands(settings, hook_substring, hook_command):
        if not write_settings(path, settings, prefix):
            return 1
        print('{}: upgraded the Bash hook in {}'.format(prefix, path))
        return 0
    if gate_items(settings, hook_substring):
        print('{}: already registered in {}; nothing changed'.format(prefix, path))
        return 0
    hooks = settings.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        return refuse(prefix, path, '"hooks" is not an object')
    entries = hooks.setdefault('PreToolUse', [])
    if not isinstance(entries, list):
        return refuse(prefix, path, '"hooks.PreToolUse" is not a list')
    entries.append({
        'matcher': 'Bash',
        'hooks': [{'type': 'command', 'command': hook_command}],
    })
    if not write_settings(path, settings, prefix):
        return 1
    print('{}: {} the Bash hook in {}'.format(
        prefix, 'created' if not existed else 'registered', path))
    return 0


def check_project(given, *, prefix, hook_substring, hook_file, hook_command, hook_label):
    directory = project_dir(given)
    for path in (directory / '.claude/settings.json', directory / '.claude/settings.local.json',
                 Path.home() / '.claude/settings.json'):
        try:
            settings = read_settings(path)
        except ValueError:
            continue
        if registered(settings, hook_substring):
            print('{}: {} registers the Bash hook, in {}'.format(prefix, directory, path))
            if any(item.get('command') != hook_command for item in gate_items(settings, hook_substring)):
                print('{}: {} has the old command, which blocks every Bash call when '
                      'the file is missing. Upgrade it with: python3 {} '
                      '--install-for-project {}'.format(prefix, directory, hook_file, directory))
            return 0
    print('{}: {} has no {}. Install it with: python3 {} '
          '--install-for-project {}'.format(prefix, directory, hook_label, hook_file, directory))
    return 1