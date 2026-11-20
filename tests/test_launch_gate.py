import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / 'hooks/launch-gate.py'
GRADE = ROOT / '.claude/skills/verify-launch-gate/grade.py'
BRIEF = 'HOLD worker, HOLD chat: load5 40.10 is 2.23x 18 cores, cpu some60 92%'
OLD_COMMAND = '$HOME/.claude/hooks/launch-gate.py'
REGISTERED = ('sh -c \'f="$HOME/.claude/hooks/launch-gate.py"; [ -f "$f" ] || exit 0; '
              'exec python3 "$f"\'')

# The chat that froze the VPS on 2026-11-20 launched every one of these at load 40.
LAUNCHES = [
    '~/.local/bin/plan-pick --run',
    'plan-pick --run brief.txt',
    'spawn-worker --level normal brief.txt',
    'pi -p "read brief.txt"',
    'pi --print "read brief.txt"',
    'codex exec "read brief.txt"',
    'cursor-agent -p x',
    'claude -p x',
    'claude --print x',
    'hax',
    'npm run build',
    'pnpm --filter web exec vite build',
    'yarn run build',
    'bun run build',
    'next build',
    'vite build',
    'turbo run build',
    'tsc -b',
    'tsc --build',
    'cargo build',
    'cargo test',
    'zig build',
    'go test ./...',
    'pytest -q',
    'python3 -m unittest discover -s tests',
    'vitest run',
    'jest',
    'playwright test',
    'make',
    'timeout 600 pytest',
    'cd web && pnpm run build',
    'env FOO=1 pytest',
]

NOT_LAUNCHES = [
    'grep -rn pytest hooks/',
    'cat package.json',
    'git log --oneline -3',
    'gh pr checks 4',
    'ls',
    'echo "make build"',
    'npm run lint',
    'python3 hooks/launch-gate.py --self-test',
    'vps-state --can-launch worker',
    'cargo --version',
    'gh pr create --body-file ~/.cache/x/body.md',
]


def registered_command(project):
    """The command the project settings register for launch-gate.py."""
    settings = json.loads((Path(project) / '.claude/settings.local.json').read_text())
    for entry in settings.get('hooks', {}).get('PreToolUse', []):
        for item in entry.get('hooks', []):
            if 'launch-gate.py' in item.get('command', ''):
                return item['command']
    return None


def fake_state(directory, code, brief=BRIEF, sleep=0):
    """A stand-in vps-state: a fixed exit code, one brief line, and a probe log."""
    log = Path(directory, 'probe.log')
    path = Path(directory, 'vps-state')
    path.write_text(
        '#!/usr/bin/env python3\n'
        'import sys, time\n'
        'from pathlib import Path\n'
        'Path({log!r}).open("a").write(" ".join(sys.argv[1:]) + "\\n")\n'
        'if {sleep}:\n'
        '    time.sleep({sleep})\n'
        'if "--brief" in sys.argv[1:]:\n'
        '    print({brief!r})\n'
        '    sys.exit(0)\n'
        'sys.exit({code})\n'.format(log=str(log), sleep=sleep, brief=brief, code=code))
    path.chmod(0o755)
    return str(path), log


class LaunchGate(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def gate(self, *args, home=None, cwd=None):
        env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(home or self.dir)}
        return subprocess.run([sys.executable, str(GATE), *args], capture_output=True, text=True,
                              env=env, cwd=str(cwd or self.dir), timeout=60)

    def run_registered(self, command, home, state=None):
        """Run a registered hook command the way Claude Code does, through a shell."""
        environ = {'PATH': os.environ.get('PATH', ''), 'HOME': str(home)}
        if state:
            environ['LAUNCH_GATE_VPS_STATE'] = state
        body = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': LAUNCHES[0]}})
        return subprocess.run(['sh', '-c', command], input=body, capture_output=True, text=True,
                              env=environ, timeout=60)

    def hook(self, command=None, state=None, env=None, tool='Bash', payload=None, home=None):
        body = payload if payload is not None else json.dumps(
            {'tool_name': tool, 'tool_input': {'command': command or ''}})
        environ = {'PATH': os.environ.get('PATH', ''), 'HOME': str(home or self.dir)}
        if state:
            environ['LAUNCH_GATE_VPS_STATE'] = state
        environ.update(env or {})
        return subprocess.run([sys.executable, str(GATE)], input=body, capture_output=True,
                              text=True, env=environ, timeout=60)

    def test_self_test_passes(self):
        result = self.gate('--self-test')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_not_a_bash_call_passes(self):
        state, log = fake_state(self.dir, 2)
        result = self.hook(payload=json.dumps({'tool_name': 'Write',
                                               'tool_input': {'file_path': 'x.py'}}), state=state)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(log.exists())

    def test_a_command_that_is_not_a_string_passes(self):
        state, log = fake_state(self.dir, 2)
        result = self.hook(payload=json.dumps({'tool_name': 'Bash',
                                               'tool_input': {'command': {'cmd': 'pytest'}}}),
                           state=state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertFalse(log.exists())

    def test_an_unknown_argument_says_so_and_does_nothing(self):
        result = self.gate('--banana')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('unknown argument', result.stderr)

    def test_broken_json_passes(self):
        state, log = fake_state(self.dir, 2)
        self.assertEqual(self.hook(payload='not json', state=state).returncode, 0)
        self.assertFalse(log.exists())

    def test_the_command_table(self):
        hold, _log = fake_state(self.dir, 2)
        for command in LAUNCHES:
            with self.subTest(command=command):
                result = self.hook(command, hold)
                self.assertEqual(result.returncode, 2, command + ' must be gated: ' + result.stderr)

    def test_reads_and_mentions_pass_without_a_probe(self):
        hold, log = fake_state(self.dir, 2)
        for command in NOT_LAUNCHES:
            with self.subTest(command=command):
                result = self.hook(command, hold)
                self.assertEqual(result.returncode, 0, command + ': ' + result.stderr)
                self.assertEqual(result.stderr, '')
        self.assertFalse(log.exists(), 'a read must not ask vps-state')

    def test_a_hold_blocks_with_the_reason(self):
        hold, _log = fake_state(self.dir, 2)
        result = self.hook('~/.local/bin/plan-pick --run', hold)
        self.assertEqual(result.returncode, 2)
        why = result.stderr
        self.assertTrue(why.startswith('BLOCKED by launch-gate: server is full ('), why)
        self.assertIn(BRIEF, why)
        self.assertIn('Start nothing new.', why)
        self.assertIn('run vps-state again in 10 minutes', why)
        self.assertIn('Only the user can lift this: LAUNCH_GATE=off.', why)

    def test_careful_and_add_allow(self):
        for code in (0, 1):
            with self.subTest(code=code):
                state, _log = fake_state(self.dir, code)
                result = self.hook('pytest -q', state)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')

    def test_a_probe_failure_fails_open_with_one_line(self):
        state, _log = fake_state(self.dir, 3)
        result = self.hook('pytest -q', state)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertTrue(lines[0].startswith('launch-gate:'), lines[0])

    def test_a_missing_vps_state_fails_open_with_one_line(self):
        result = self.hook('pytest -q', str(self.dir / 'no-such-vps-state'))
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertIn('could not run', lines[0])

    def test_a_slow_probe_fails_open(self):
        state, _log = fake_state(self.dir, 0, sleep=6)
        result = self.hook('pytest -q', state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('launch-gate:', result.stderr)

    def test_a_hook_without_its_splitter_fails_open_with_one_line(self):
        lone = self.dir / 'launch-gate.py'
        shutil.copy(GATE, lone)
        hold, _log = fake_state(self.dir, 2)
        env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(self.dir),
               'LAUNCH_GATE_VPS_STATE': hold}
        result = subprocess.run(
            [sys.executable, str(lone)],
            input=json.dumps({'tool_name': 'Bash',
                              'tool_input': {'command': '~/.local/bin/plan-pick --run'}}),
            capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertTrue(lines[0].startswith('launch-gate:'), lines[0])

    def test_the_override_lifts_the_gate(self):
        hold, log = fake_state(self.dir, 2)
        allowed = self.hook('pytest -q', hold, env={'LAUNCH_GATE': 'off'})
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(allowed.stderr, '')
        self.assertFalse(log.exists())

        leading = self.hook('LAUNCH_GATE=off pytest -q', hold)
        self.assertEqual(leading.returncode, 0, leading.stderr)
        self.assertFalse(log.exists())

    def test_install_creates_the_project_hook(self):
        project = self.dir / 'proj'
        project.mkdir()
        result = self.gate('--install-for-project', str(project))
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads((project / '.claude/settings.local.json').read_text())
        self.assertEqual(settings['hooks']['PreToolUse'], [
            {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': REGISTERED}]}])
        self.assertIn(str(project / '.claude/settings.local.json'), result.stdout)

    def test_install_keeps_other_keys_and_entries(self):
        project = self.dir / 'proj'
        (project / '.claude').mkdir(parents=True)
        before = {
            'permissions': {'allow': ['Bash(ls:*)']},
            'hooks': {
                'PreToolUse': [{'matcher': 'Write', 'hooks': [
                    {'type': 'command', 'command': '/usr/bin/python3 other-guard.py'}]}],
                'SessionStart': [{'hooks': [{'type': 'command', 'command': 'vps-state-hook'}]}],
            },
        }
        (project / '.claude/settings.local.json').write_text(json.dumps(before))
        self.assertEqual(self.gate('--install-for-project', str(project)).returncode, 0)
        settings = json.loads((project / '.claude/settings.local.json').read_text())
        self.assertEqual(settings['permissions'], before['permissions'])
        self.assertEqual(settings['hooks']['SessionStart'], before['hooks']['SessionStart'])
        self.assertEqual(settings['hooks']['PreToolUse'][0], before['hooks']['PreToolUse'][0])
        self.assertIn('launch-gate.py', json.dumps(settings['hooks']['PreToolUse'][1]))

    def test_install_is_idempotent(self):
        project = self.dir / 'proj'
        project.mkdir()
        self.gate('--install-for-project', str(project))
        path = project / '.claude/settings.local.json'
        first = path.read_text()
        second = self.gate('--install-for-project', str(project))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(path.read_text(), first)
        self.assertIn('nothing', second.stdout.lower())

    def test_install_defaults_to_the_current_directory(self):
        project = self.dir / 'proj'
        project.mkdir()
        self.assertEqual(self.gate('--install-for-project', cwd=project).returncode, 0)
        self.assertTrue((project / '.claude/settings.local.json').is_file())

    def test_the_registered_command_fails_open_without_the_hook_file(self):
        project = self.dir / 'proj'
        home = self.dir / 'home'
        project.mkdir()
        home.mkdir()
        self.assertEqual(self.gate('--install-for-project', str(project), home=home).returncode, 0)
        command = registered_command(project)
        self.assertEqual(command, REGISTERED)
        hold, log = fake_state(self.dir, 2)
        self.assertFalse((home / '.claude/hooks/launch-gate.py').exists())
        result = self.run_registered(command, home, hold)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertFalse(log.exists(), 'no probe without the hook file')

    def test_the_registered_command_fails_open_on_a_broken_link(self):
        project = self.dir / 'proj'
        home = self.dir / 'home'
        project.mkdir()
        (home / '.claude/hooks').mkdir(parents=True)
        (home / '.claude/hooks/launch-gate.py').symlink_to(home / 'gone')
        self.assertEqual(self.gate('--install-for-project', str(project), home=home).returncode, 0)
        hold, _log = fake_state(self.dir, 2)
        result = self.run_registered(registered_command(project), home, hold)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def test_the_registered_command_still_blocks_at_hold(self):
        project = self.dir / 'proj'
        home = self.dir / 'home'
        project.mkdir()
        (home / '.claude/hooks').mkdir(parents=True)
        (home / '.claude/hooks/launch-gate.py').symlink_to(GATE)
        self.assertEqual(self.gate('--install-for-project', str(project), home=home).returncode, 0)
        hold, _log = fake_state(self.dir, 2)
        result = self.run_registered(registered_command(project), home, hold)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('BLOCKED by launch-gate: server is full (', result.stderr)
        self.assertIn(BRIEF, result.stderr)

    def test_the_registered_command_survives_a_path_with_spaces(self):
        project = self.dir / 'my proj'
        home = self.dir / 'home dir'
        project.mkdir()
        home.mkdir()
        self.assertEqual(self.gate('--install-for-project', str(project), home=home).returncode, 0)
        command = registered_command(project)
        hold, _log = fake_state(self.dir, 2)
        missing = self.run_registered(command, home, hold)
        self.assertEqual(missing.returncode, 0, missing.stderr)
        (home / '.claude/hooks').mkdir(parents=True)
        (home / '.claude/hooks/launch-gate.py').symlink_to(GATE)
        blocked = self.run_registered(command, home, hold)
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn(BRIEF, blocked.stderr)

    def test_install_upgrades_the_old_command_in_place(self):
        project = self.dir / 'proj'
        (project / '.claude').mkdir(parents=True)
        before = {
            'permissions': {'allow': ['Bash(ls:*)']},
            'hooks': {'PreToolUse': [
                {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': OLD_COMMAND}]},
                {'matcher': 'Write', 'hooks': [
                    {'type': 'command', 'command': '/usr/bin/python3 other-guard.py'}]}]},
        }
        path = project / '.claude/settings.local.json'
        path.write_text(json.dumps(before))
        result = self.gate('--install-for-project', str(project))
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(path.read_text())
        self.assertEqual(settings['permissions'], before['permissions'])
        self.assertEqual(settings['hooks']['PreToolUse'][1], before['hooks']['PreToolUse'][1])
        self.assertEqual(len(settings['hooks']['PreToolUse']), 2, 'no second entry')
        self.assertEqual(settings['hooks']['PreToolUse'][0]['matcher'], 'Bash')
        self.assertEqual(settings['hooks']['PreToolUse'][0]['hooks'],
                         [{'type': 'command', 'command': REGISTERED}])
        self.assertIn('upgraded', result.stdout)
        upgraded = path.read_text()
        again = self.gate('--install-for-project', str(project))
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(path.read_text(), upgraded)
        self.assertIn('nothing', again.stdout.lower())

    def test_install_registers_when_the_settings_have_no_hooks_key(self):
        project = self.dir / 'proj'
        (project / '.claude').mkdir(parents=True)
        (project / '.claude/settings.local.json').write_text(json.dumps({'permissions': {}}))
        self.assertEqual(self.gate('--install-for-project', str(project)).returncode, 0)
        self.assertEqual(registered_command(project), REGISTERED)

    def test_check_project_accepts_both_command_forms(self):
        for name, command in (('new', REGISTERED), ('old', OLD_COMMAND)):
            with self.subTest(form=name):
                project = self.dir / ('proj-' + name)
                (project / '.claude').mkdir(parents=True)
                (project / '.claude/settings.local.json').write_text(json.dumps(
                    {'hooks': {'PreToolUse': [
                        {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': command}]}]}}))
                result = self.gate('--check-project', str(project))
                self.assertEqual(result.returncode, 0, result.stderr)
                if name == 'old':
                    self.assertIn('--install-for-project', result.stdout,
                                  'an old form asks for the upgrade')

    def test_install_refuses_a_settings_file_it_cannot_write(self):
        project = self.dir / 'proj'
        (project / '.claude/settings.local.json').mkdir(parents=True)
        result = self.gate('--install-for-project', str(project))
        self.assertEqual(result.returncode, 1)
        self.assertIn('could not be written', result.stderr)
        self.assertTrue((project / '.claude/settings.local.json').is_dir())

    def test_install_refuses_broken_settings_json(self):
        project = self.dir / 'proj'
        (project / '.claude').mkdir(parents=True)
        path = project / '.claude/settings.local.json'
        path.write_text('{not json')
        result = self.gate('--install-for-project', str(project))
        self.assertEqual(result.returncode, 1)
        self.assertIn('not valid JSON', result.stderr)
        self.assertEqual(path.read_text(), '{not json')
        self.assertEqual(self.gate('--check-project', str(project)).returncode, 1)

    def test_check_project_passes_after_install_and_fails_before(self):
        project = self.dir / 'proj'
        project.mkdir()
        before = self.gate('--check-project', str(project))
        self.assertEqual(before.returncode, 1)
        self.assertIn('--install-for-project', before.stdout + before.stderr)
        self.gate('--install-for-project', str(project))
        after = self.gate('--check-project', str(project))
        self.assertEqual(after.returncode, 0, after.stderr)

    def test_check_project_reads_the_global_settings(self):
        home = self.dir / 'home'
        (home / '.claude').mkdir(parents=True)
        (home / '.claude/settings.json').write_text(json.dumps({'hooks': {'PreToolUse': [
            {'matcher': 'Bash', 'hooks': [
                {'type': 'command', 'command': '$HOME/.claude/hooks/launch-gate.py'}]}]}}))
        project = self.dir / 'proj'
        project.mkdir()
        self.assertEqual(self.gate('--check-project', str(project), home=home).returncode, 0)

    def test_check_project_reads_a_project_settings_json(self):
        project = self.dir / 'proj'
        (project / '.claude').mkdir(parents=True)
        (project / '.claude/settings.json').write_text(json.dumps({'hooks': {'PreToolUse': [
            {'matcher': 'Bash', 'hooks': [
                {'type': 'command', 'command': '$HOME/.claude/hooks/launch-gate.py'}]}]}}))
        self.assertEqual(self.gate('--check-project', str(project)).returncode, 0)

    def test_check_project_never_edits_the_global_settings(self):
        home = self.dir / 'home'
        (home / '.claude').mkdir(parents=True)
        path = home / '.claude/settings.json'
        path.write_text('{}\n')
        project = self.dir / 'proj'
        project.mkdir()
        self.gate('--install-for-project', str(project), home=home)
        self.assertEqual(path.read_text(), '{}\n')


class VerifyLaunchGateGrade(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, name, text):
        (self.dir / name).write_text(text)

    def evidence(self):
        settings = {'hooks': {'PreToolUse': [
            {'matcher': 'Bash', 'hooks': [
                {'type': 'command', 'command': '$HOME/.claude/hooks/launch-gate.py'}]}]}}
        self.write('meta.json', json.dumps({'hook': str(GATE), 'project': '/tmp/p',
                                            'empty': '/tmp/e', 'git_sha': 'abc'}))
        self.write('doctor.txt', 'PASS hook: executable\n')
        self.write('install-1.json', json.dumps({
            'code': 0, 'path': '/tmp/p/.claude/settings.local.json',
            'stdout': 'launch-gate: created the Bash hook in /tmp/p/.claude/settings.local.json'}))
        self.write('settings-1.json', json.dumps(settings, indent=2) + '\n')
        self.write('install-2.json', json.dumps({
            'code': 0, 'path': '/tmp/p/.claude/settings.local.json',
            'stdout': 'launch-gate: already registered in /tmp/p/.claude/settings.local.json; '
                      'nothing changed'}))
        self.write('settings-2.json', json.dumps(settings, indent=2) + '\n')
        self.write('check-project.code', '0\n')
        self.write('check-project.out', 'launch-gate: /tmp/p registers the Bash hook\n')
        self.write('check-empty.code', '1\n')
        self.write('check-empty.out', 'launch-gate: /tmp/e has no launch-gate hook. Install it with: '
                   'python3 ~/.claude/hooks/launch-gate.py --install-for-project /tmp/e\n')
        self.write('missing.code', '0\n')
        self.write('missing.err', '')
        self.write('registered-hold.code', '2\n')
        self.write('registered-hold.err', 'BLOCKED by launch-gate: server is full (' + BRIEF +
                   '). Start nothing new. Only the user can lift this: LAUNCH_GATE=off.\n')
        self.write('hold.code', '2\n')
        self.write('hold.err', 'BLOCKED by launch-gate: server is full (' + BRIEF + '). Start nothing '
                   'new. Only the user can lift this: LAUNCH_GATE=off.\n')
        self.write('add.code', '0\n')
        self.write('add.err', '')
        self.write('careful.code', '0\n')
        self.write('careful.err', '')
        self.write('open.code', '0\n')
        self.write('open.err', 'launch-gate: vps-state exited 3, so this launch was not checked\n')
        self.write('live.code', '2\n')
        self.write('live.out', BRIEF + '\n')
        return self.dir

    def grade(self, directory):
        result = subprocess.run([sys.executable, str(GRADE), str(directory)],
                                capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout

    def test_a_full_evidence_directory_grades_pass(self):
        code, out = self.grade(self.evidence())
        self.assertEqual(code, 0, out)
        self.assertIn('VERDICT PASS', out)
        for check in ('install', 'idempotent', 'check-project', 'registered', 'hold', 'verdicts',
                      'fail-open', 'live'):
            self.assertIn('PASS ' + check + ':', out)

    def test_a_missing_hook_registration_fails_install(self):
        directory = self.evidence()
        (directory / 'settings-1.json').write_text('{}\n')
        code, out = self.grade(directory)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL install:', out)
        self.assertIn('VERDICT FAIL', out)

    def test_a_second_install_that_changes_the_file_fails_idempotent(self):
        directory = self.evidence()
        (directory / 'settings-2.json').write_text('{"hooks": {}}\n')
        code, out = self.grade(directory)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL idempotent:', out)

    def test_a_registered_command_that_blocks_without_the_file_fails_registered(self):
        directory = self.evidence()
        (directory / 'missing.code').write_text('2\n')
        (directory / 'missing.err').write_text("python3: can't open file\n")
        code, out = self.grade(directory)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL registered:', out)

    def test_a_registered_command_that_allows_a_hold_fails_registered(self):
        directory = self.evidence()
        (directory / 'registered-hold.code').write_text('0\n')
        (directory / 'registered-hold.err').write_text('')
        code, out = self.grade(directory)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL registered:', out)

    def test_an_unblocked_launch_fails_hold(self):
        directory = self.evidence()
        (directory / 'hold.code').write_text('0\n')
        (directory / 'hold.err').write_text('')
        code, out = self.grade(directory)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL hold:', out)

    def test_a_hold_without_the_override_line_fails_hold(self):
        directory = self.evidence()
        (directory / 'hold.err').write_text('BLOCKED by launch-gate: server is full (' + BRIEF + ').\n')
        code, out = self.grade(directory)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL hold:', out)

    def test_a_second_install_that_is_silent_fails_idempotent(self):
        directory = self.evidence()
        (directory / 'install-2.json').write_text(json.dumps({'code': 0, 'stdout': 'ok'}))
        code, out = self.grade(directory)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL idempotent:', out)


if __name__ == '__main__':
    unittest.main()
