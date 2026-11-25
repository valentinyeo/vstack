"""The pacer rule and its guard follow a chat to Codex and Antigravity (VSTA-283).

Every test runs against a throwaway HOME: the real ~/.codex and ~/.gemini are never read or written.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RULE = ROOT / 'skills/valentin-mode/references/pacer-rule.md'
GUARD = 'pacer-guard.py'
BEGIN = 'vstack:pacer-rule:begin'


def install(home):
    env = {**os.environ, 'HOME': str(home), 'VSTACK_INSTALL_ANYWHERE': '1',
           'VSTACK_DIR': str(home / '.local/share/vstack')}
    return subprocess.run([str(ROOT / 'install')], env=env, cwd=str(ROOT),
                          capture_output=True, text=True, timeout=600)


def run_hook(command, payload, home, owner):
    """Run one installed hook command the way its harness does, inside a scratch HOME."""
    env = {'PATH': os.environ['PATH'], 'HOME': str(home)}
    if owner:
        env['MULTIPROMPT_TAB'] = 'pacer-harness-test'
    return subprocess.run(['bash', '-c', command], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, timeout=120)


def commands(path, event, harness):
    """Every hook command registered for that event whose registration names the harness."""
    data = json.loads(path.read_text())
    blocks = [data.get('hooks')] if isinstance(data.get('hooks'), dict) else []
    blocks += [block for key, block in data.items() if isinstance(block, dict) and key != 'hooks']
    found = []
    for block in blocks:
        for group in block.get(event) or []:
            for hook in (group or {}).get('hooks') or []:
                command = str(hook.get('command') or '') if isinstance(hook, dict) else ''
                if harness in command:
                    found.append(command)
    return found


class HarnessPacer(unittest.TestCase):
    def scratch(self):
        home = Path(tempfile.mkdtemp(prefix='pacer-harness-'))
        self.addCleanup(shutil.rmtree, home, True)
        return home

    def installed(self):
        home = self.scratch()
        result = install(home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return home

    def test_install_writes_one_rule_block_per_harness_and_writes_it_once(self):
        home = self.scratch()
        (home / '.codex').mkdir(parents=True)
        (home / '.codex/AGENTS.md').write_text('# house rules\n\nkeep this line\n')
        self.assertEqual(install(home).returncode, 0)
        codex = home / '.codex/AGENTS.md'
        agy = home / '.gemini/GEMINI.md'
        for path in (codex, agy):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), path)
                text = path.read_text()
                self.assertEqual(text.count(BEGIN), 1, text)
                self.assertIn(RULE.read_text().strip().splitlines()[2], text)
        self.assertIn('keep this line', codex.read_text())
        before = (codex.read_text(), agy.read_text(), (home / '.codex/hooks.json').read_text())
        self.assertEqual(install(home).returncode, 0)
        self.assertEqual(before, (codex.read_text(), agy.read_text(), (home / '.codex/hooks.json').read_text()),
                         'a second install rewrote a file it had already written')

    def test_codex_hooks_merge_keeps_the_entries_already_there(self):
        home = self.scratch()
        (home / '.codex').mkdir(parents=True)
        (home / '.codex/hooks.json').write_text(json.dumps({'hooks': {'PreToolUse': [
            {'matcher': 'exec_command',
             'hooks': [{'type': 'command', 'command': 'my own pre-tool check'}]}],
            'SessionStart': [{'hooks': [{'type': 'command', 'command': 'my own session start'}]}]}}))
        self.assertEqual(install(home).returncode, 0)
        data = json.loads((home / '.codex/hooks.json').read_text())
        registered = json.dumps(data)
        self.assertIn('my own pre-tool check', registered)
        self.assertIn('my own session start', registered)
        self.assertEqual(registered.count(GUARD), 1, registered)
        self.assertEqual(len(commands(home / '.codex/hooks.json', 'PreToolUse', '--harness codex')), 1)
        self.assertEqual(install(home).returncode, 0)
        again = (home / '.codex/hooks.json').read_text()
        self.assertEqual(json.loads(again), data, 'the second install registered the guard again')

    def test_agy_hooks_carry_the_guard(self):
        home = self.installed()
        found = commands(home / '.gemini/config/hooks.json', 'PreToolUse', '--harness agy')
        self.assertEqual(len(found), 1, found)

    def test_an_owner_edit_on_codex_is_blocked(self):
        home = self.installed()
        for command in commands(home / '.codex/hooks.json', 'PreToolUse', '--harness codex'):
            for payload in (
                {'tool_name': 'exec_command', 'hook_event_name': 'PreToolUse',
                 'tool_input': {'command': 'cat > app.py <<EOF\nprint(1)\nEOF'}},
                {'tool_name': 'apply_patch', 'hook_event_name': 'PreToolUse',
                 'tool_input': {'patch': '*** Begin Patch\n*** Update File: hooks/x.py\n@@ -1 +1 @@\n'
                                         '*** End Patch\n'}},
            ):
                with self.subTest(tool=payload['tool_name']):
                    result = run_hook(command, payload, home, owner=True)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('plan-pick --run', result.stderr)
            docs = {'tool_name': 'exec_command', 'hook_event_name': 'PreToolUse',
                    'tool_input': {'command': 'echo words > brief.txt'}}
            self.assertEqual(run_hook(command, docs, home, owner=True).returncode, 0, 'a brief is not code')

    def test_a_worker_run_on_codex_is_not_blocked(self):
        home = self.installed()
        for command in commands(home / '.codex/hooks.json', 'PreToolUse', '--harness codex'):
            payload = {'tool_name': 'exec_command', 'hook_event_name': 'PreToolUse',
                       'tool_input': {'command': 'cat > app.py <<EOF\nprint(1)\nEOF'}}
            result = run_hook(command, payload, home, owner=False)
            self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout + result.stderr)

    def test_an_owner_edit_on_agy_is_denied_and_a_worker_run_is_not(self):
        home = self.installed()
        for command in commands(home / '.gemini/config/hooks.json', 'PreToolUse', '--harness agy'):
            for payload in (
                {'hookEventName': 'PreToolUse',
                 'toolCall': {'id': 't1', 'name': 'run_command', 'args': {'CommandLine': 'printf x > run.sh'}}},
                {'hookEventName': 'PreToolUse',
                 'toolCall': {'id': 't2', 'name': 'write_file',
                              'args': {'TargetFile': 'web/app.tsx', 'CodeContent': 'export {}\n'}}},
            ):
                with self.subTest(tool=payload['toolCall']['name']):
                    result = run_hook(command, payload, home, owner=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    answer = json.loads(result.stdout)
                    self.assertEqual(answer.get('decision'), 'deny', result.stdout)
                    self.assertIn('plan-pick --run', answer.get('reason', ''))
            worker = {'hookEventName': 'PreToolUse',
                      'toolCall': {'id': 't3', 'name': 'write_file',
                                   'args': {'TargetFile': 'web/app.tsx', 'CodeContent': 'export {}\n'}}}
            result = run_hook(command, worker, home, owner=False)
            self.assertEqual((result.returncode, json.loads(result.stdout)), (0, {}), result.stdout + result.stderr)

    def test_an_owner_read_on_agy_is_allowed(self):
        home = self.installed()
        for command in commands(home / '.gemini/config/hooks.json', 'PreToolUse', '--harness agy'):
            payload = {'hookEventName': 'PreToolUse',
                       'toolCall': {'id': 't4', 'name': 'view_file',
                                    'args': {'AbsolutePath': '/tmp/hooks/pacer-guard.py'}}}
            result = run_hook(command, payload, home, owner=True)
            self.assertEqual(json.loads(result.stdout), {}, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
