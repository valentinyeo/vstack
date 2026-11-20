#!/usr/bin/env python3
"""Grade one verify-launch-gate evidence directory.

    grade.py <evidence dir>

Prints one PASS or FAIL line per check, then VERDICT PASS or VERDICT FAIL.
Exit 0 PASS, 1 FAIL. It reads only the files the run saved, never the live host.
"""
import json
import sys
from pathlib import Path

PASS, FAIL = 'PASS', 'FAIL'
EXIT_FOR = {'ADD': 0, 'CAREFUL': 1, 'HOLD': 2}
CHECKS = ('doctor', 'install', 'idempotent', 'check-project', 'registered', 'hold', 'verdicts',
          'fail-open', 'live')


def text(directory, name):
    try:
        return (directory / name).read_text()
    except OSError:
        return None


def report(directory, name):
    """A saved command result: exit code, stdout, stderr."""
    try:
        payload = json.loads(text(directory, name) or '')
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def settings_file(directory, name):
    try:
        payload = json.loads(text(directory, name) or '')
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def exit_code(directory, name):
    value = (text(directory, name) or '').strip()
    return int(value) if value.lstrip('-').isdigit() else None


def carries_hook(settings):
    """This settings object registers the launch-gate hook for Bash."""
    hooks = settings.get('hooks') if isinstance(settings, dict) else None
    entries = hooks.get('PreToolUse') if isinstance(hooks, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or 'Bash' not in str(entry.get('matcher') or ''):
            continue
        for item in entry.get('hooks') or []:
            if isinstance(item, dict) and 'launch-gate.py' in str(item.get('command') or ''):
                return True
    return False


def check_doctor(directory):
    lines = [line for line in (text(directory, 'doctor.txt') or '').splitlines() if line.strip()]
    failed = [line for line in lines if not line.startswith('PASS ')]
    if not lines:
        return FAIL, 'doctor.txt is empty'
    if failed:
        return FAIL, 'the run was not worth driving: ' + '; '.join(failed)
    return PASS, 'the hook is executable and its self-test passes'


def check_install(directory):
    result = report(directory, 'install-1.json')
    settings = settings_file(directory, 'settings-1.json')
    if not result or result.get('code') != 0:
        return FAIL, 'install-for-project exited {}'.format((result or {}).get('code'))
    if not carries_hook(settings):
        return FAIL, 'the project settings carry no Bash launch-gate hook'
    target = result.get('path') or ''
    if target and target not in (result.get('stdout') or ''):
        return FAIL, 'install did not name the file it changed'
    return PASS, 'install-for-project created the project settings with the Bash hook'


def check_idempotent(directory):
    first = settings_file(directory, 'settings-1.json')
    second = settings_file(directory, 'settings-2.json')
    result = report(directory, 'install-2.json')
    if not result or result.get('code') != 0:
        return FAIL, 'the second install-for-project exited {}'.format((result or {}).get('code'))
    if json.dumps(first, sort_keys=True) != json.dumps(second, sort_keys=True):
        return FAIL, 'the second install changed the settings file'
    if 'nothing' not in (result.get('stdout') or '').lower():
        return FAIL, 'the second install did not say it changed nothing'
    return PASS, 'a second install left the file byte for byte the same'


def check_project(directory):
    project = exit_code(directory, 'check-project.code')
    empty = exit_code(directory, 'check-empty.code')
    if project != 0:
        return FAIL, 'check-project exited {} on the project it just installed into'.format(project)
    if empty != 1:
        return FAIL, 'check-project exited {} on a project with no hook, expected 1'.format(empty)
    if '--install-for-project' not in (text(directory, 'check-empty.out') or ''):
        return FAIL, 'the failing check-project line does not say how to install'
    return PASS, 'check-project passes on the installed project and fails with the install command'


def check_registered(directory):
    absent = exit_code(directory, 'missing.code')
    absent_err = (text(directory, 'missing.err') or '').strip()
    blocked = exit_code(directory, 'registered-hold.code')
    blocked_err = text(directory, 'registered-hold.err') or ''
    if absent != 0:
        return FAIL, 'the registered command exited {} with the hook file missing'.format(absent)
    if absent_err:
        return FAIL, 'a missing hook file printed on stderr: ' + absent_err[:200]
    if blocked != 2:
        return FAIL, 'the registered command exited {} at HOLD, expected 2'.format(blocked)
    if not blocked_err.startswith('BLOCKED by launch-gate: server is full ('):
        return FAIL, 'the registered command did not carry the block: ' + blocked_err.strip()[:200]
    return PASS, 'the command settings call exits 0 without the hook file, and blocks at HOLD'


def check_hold(directory):
    code = exit_code(directory, 'hold.code')
    err = text(directory, 'hold.err') or ''
    brief = (text(directory, 'brief.txt') or '').strip()
    if code != 2:
        return FAIL, 'a launch at HOLD exited {}, expected 2'.format(code)
    if not err.startswith('BLOCKED by launch-gate: server is full ('):
        return FAIL, 'the block message does not open with the gate name: ' + err.strip()[:200]
    if 'Only the user can lift this: LAUNCH_GATE=off.' not in err:
        return FAIL, 'the block message does not name the override'
    if brief and brief not in err:
        return FAIL, 'the block message does not carry the vps-state brief line'
    return PASS, 'a launch at HOLD is blocked with the reason and the override'


def check_verdicts(directory):
    add = exit_code(directory, 'add.code')
    careful = exit_code(directory, 'careful.code')
    if add != 0:
        return FAIL, 'a launch at ADD exited {}, expected 0'.format(add)
    if careful != 0:
        return FAIL, 'a launch at CAREFUL exited {}, expected 0'.format(careful)
    noise = [name for name in ('add.err', 'careful.err') if (text(directory, name) or '').strip()]
    if noise:
        return FAIL, 'an allowed launch printed on stderr: ' + ', '.join(noise)
    return PASS, 'ADD and CAREFUL both let the launch through, silent'


def check_fail_open(directory):
    code = exit_code(directory, 'open.code')
    err = text(directory, 'open.err') or ''
    lines = [line for line in err.splitlines() if line.strip()]
    if code != 0:
        return FAIL, 'a probe failure exited {}, expected 0'.format(code)
    if len(lines) != 1 or not lines[0].startswith('launch-gate:'):
        return FAIL, 'a probe failure must print exactly one warning line, got {!r}'.format(err)
    return PASS, 'a probe failure allows the launch and warns once'


def check_live(directory):
    code = exit_code(directory, 'live.code')
    out = text(directory, 'live.out') or ''
    first = out.splitlines()[0].strip() if out.strip() else ''
    word = first.split()[0] if first else ''
    if word not in EXIT_FOR:
        return FAIL, 'the live vps-state call printed no verdict line: {!r}'.format(out.strip()[:200])
    if code != EXIT_FOR[word]:
        return FAIL, 'the live brief says {} but --can-launch worker exited {}'.format(word, code)
    return PASS, 'the real host answered {} and the exit code agrees: {}'.format(word, first)


def grade(directory):
    """One (name, ok, detail) per check, read from the evidence directory."""
    results = []
    for name, check in (('doctor', check_doctor), ('install', check_install),
                        ('idempotent', check_idempotent), ('check-project', check_project),
                        ('registered', check_registered), ('hold', check_hold),
                        ('verdicts', check_verdicts),
                        ('fail-open', check_fail_open), ('live', check_live)):
        verdict, detail = check(directory)
        results.append((name, verdict == PASS, detail))
    return results


def render(directory):
    checks = grade(directory)
    verdict = PASS if checks and all(ok for _name, ok, _detail in checks) else FAIL
    lines = ['{} {}: {}'.format(PASS if ok else FAIL, name, detail)
             for name, ok, detail in checks]
    lines.append('VERDICT ' + verdict)
    (directory / 'verdict.txt').write_text('\n'.join(lines) + '\n')
    (directory / 'verdict.json').write_text(json.dumps({
        'verdict': verdict,
        'run_id': directory.name,
        'checks': [{'name': name, 'ok': ok, 'detail': detail} for name, ok, detail in checks],
    }, indent=2) + '\n')
    return lines, verdict


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print('usage: grade.py <evidence dir>', file=sys.stderr)
        return 2
    directory = Path(args[0])
    if not directory.is_dir():
        print('grade.py: no evidence directory at {}'.format(directory), file=sys.stderr)
        return 2
    lines, verdict = render(directory)
    print('\n'.join(lines))
    return 0 if verdict == PASS else 1


if __name__ == '__main__':
    sys.exit(main())
