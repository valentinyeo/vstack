"""install wires the Token Ladder prompt hook into Claude, Codex and Antigravity (VSTA-286).

Every test runs against a throwaway HOME: the real ~/.claude, ~/.codex and ~/.gemini are never read or written.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BARE_PATH = '/usr/bin:/bin'


def plant_ladder(path, body=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        body = (
            '#!/usr/bin/env python3\n'
            'import json, sys\n'
            'if sys.argv[1:] != ["hook-prompt"]:\n'
            '    sys.exit(2)\n'
            'data = json.loads(sys.stdin.read() or "{}")\n'
            'print("Token ladder: Claude ON; Codex ON sid=" + str(data.get("session_id", "")))\n'
        )
    path.write_text(body)
    path.chmod(0o755)
    return path


def run_install(home, path_env=BARE_PATH):
    env = {
        **os.environ,
        'HOME': str(home),
        'PATH': path_env,
        'VSTACK_INSTALL_ANYWHERE': '1',
        'VSTACK_DIR': str(home / '.local' / 'share' / 'vstack'),
    }
    return subprocess.run(
        [str(ROOT / 'install')],
        env=env,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )


def user_prompt_hooks(path):
    data = json.loads(path.read_text())
    return [
        hook
        for group in data.get('hooks', {}).get('UserPromptSubmit', [])
        if isinstance(group, dict)
        for hook in group.get('hooks', [])
        if isinstance(hook, dict)
    ]


class LadderHookInstallTest(unittest.TestCase):
    def scratch(self):
        home = Path(tempfile.mkdtemp(prefix='ladder-hook-'))
        self.addCleanup(shutil.rmtree, home, True)
        return home

    def test_install_wires_all_harnesses_idempotently(self):
        home = self.scratch()
        ladder = plant_ladder(home / '.local' / 'bin' / 'token-ladder')

        first = run_install(home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

        claude_path = home / '.claude' / 'settings.json'
        codex_path = home / '.codex' / 'hooks.json'
        agy_path = home / '.gemini' / 'config' / 'hooks.json'

        claude_ladder = [h for h in user_prompt_hooks(claude_path) if 'hook-prompt' in h.get('command', '')]
        self.assertEqual(len(claude_ladder), 1, claude_ladder)
        self.assertIn(str(ladder), claude_ladder[0]['command'])
        self.assertIn('hooks/run-hook', claude_ladder[0]['command'])
        self.assertLessEqual(claude_ladder[0]['timeout'], 5)

        codex_ladder = [h for h in user_prompt_hooks(codex_path) if 'token-ladder-prompt.py' in h.get('command', '')]
        self.assertEqual(len(codex_ladder), 1, codex_ladder)
        self.assertIn('--harness codex', codex_ladder[0]['command'])
        self.assertIn(str(ladder), codex_ladder[0]['command'])
        self.assertLessEqual(codex_ladder[0]['timeout'], 5)

        agy_data = json.loads(agy_path.read_text())
        self.assertIn('vstack-valentin-mode', agy_data)
        agy_hooks = agy_data.get('vstack-token-ladder', {}).get('PreInvocation', [])
        self.assertEqual(len(agy_hooks), 1, agy_hooks)
        self.assertIn('--harness agy', agy_hooks[0]['command'])
        self.assertIn(str(ladder), agy_hooks[0]['command'])
        self.assertLessEqual(agy_hooks[0]['timeout'], 5)

        snapshot = (claude_path.read_text(), codex_path.read_text(), agy_path.read_text())
        second = run_install(home)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(snapshot, (claude_path.read_text(), codex_path.read_text(), agy_path.read_text()))

    def test_install_resolves_token_ladder_from_path(self):
        home = self.scratch()
        extra_bin = home / 'custom-bin'
        ladder = plant_ladder(extra_bin / 'token-ladder')

        result = run_install(home, path_env=f'{extra_bin}:{BARE_PATH}')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        claude_hooks = [h for h in user_prompt_hooks(home / '.claude' / 'settings.json')
                        if 'hook-prompt' in h.get('command', '')]
        self.assertEqual(len(claude_hooks), 1)
        self.assertIn(str(ladder), claude_hooks[0]['command'])

    def test_install_merges_without_dropping_existing_hooks(self):
        home = self.scratch()
        plant_ladder(home / '.local' / 'bin' / 'token-ladder')

        claude_path = home / '.claude' / 'settings.json'
        claude_path.parent.mkdir(parents=True)
        claude_path.write_text(json.dumps({
            'env': {'KEEP': 'yes'},
            'hooks': {
                'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'echo existing-claude'}]}],
                'Stop': [{'hooks': [{'type': 'command', 'command': 'echo existing-stop'}]}],
            },
        }))
        claude_path.chmod(0o600)

        codex_path = home / '.codex' / 'hooks.json'
        codex_path.parent.mkdir(parents=True)
        codex_path.write_text(json.dumps({
            'hooks': {
                'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'echo existing-codex'}]}],
                'PreToolUse': [{'hooks': [{'type': 'command', 'command': 'echo existing-pretool'}]}],
            },
        }))
        codex_path.chmod(0o600)

        agy_path = home / '.gemini' / 'config' / 'hooks.json'
        agy_path.parent.mkdir(parents=True)
        agy_path.write_text(json.dumps({'custom-hook': {'enabled': False}}))

        result = run_install(home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        claude_data = json.loads(claude_path.read_text())
        self.assertEqual(claude_data['env'], {'KEEP': 'yes'})
        self.assertIn('echo existing-claude', json.dumps(claude_data['hooks']['UserPromptSubmit']))
        self.assertIn('echo existing-stop', json.dumps(claude_data['hooks']['Stop']))
        self.assertIn('hook-prompt', json.dumps(claude_data['hooks']['UserPromptSubmit']))
        self.assertEqual(claude_path.stat().st_mode & 0o777, 0o600)

        codex_data = json.loads(codex_path.read_text())
        self.assertIn('echo existing-codex', json.dumps(codex_data['hooks']['UserPromptSubmit']))
        self.assertIn('echo existing-pretool', json.dumps(codex_data['hooks']['PreToolUse']))
        self.assertIn('--harness codex', json.dumps(codex_data['hooks']['UserPromptSubmit']))
        self.assertEqual(codex_path.stat().st_mode & 0o777, 0o600)

        agy_data = json.loads(agy_path.read_text())
        self.assertEqual(agy_data.get('custom-hook'), {'enabled': False})
        self.assertIn('vstack-token-ladder', agy_data)

    def test_install_skips_cleanly_when_token_ladder_is_missing(self):
        home = self.scratch()
        result = run_install(home, path_env=BARE_PATH)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('token-ladder not installed', result.stderr)

        claude_hooks = user_prompt_hooks(home / '.claude' / 'settings.json')
        self.assertFalse(any('token-ladder' in h.get('command', '') for h in claude_hooks), claude_hooks)
        codex_path = home / '.codex' / 'hooks.json'
        codex_entries = json.dumps(json.loads(codex_path.read_text())) if codex_path.exists() else ''
        self.assertNotIn('token-ladder', codex_entries)
        agy_data = json.loads((home / '.gemini' / 'config' / 'hooks.json').read_text())
        self.assertNotIn('vstack-token-ladder', agy_data)

    def test_installed_hooks_execute_for_each_harness(self):
        home = self.scratch()
        plant_ladder(home / '.local' / 'bin' / 'token-ladder')
        result = run_install(home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        env = {'PATH': BARE_PATH, 'HOME': str(home)}

        claude_cmd = [h['command'] for h in user_prompt_hooks(home / '.claude' / 'settings.json')
                      if 'hook-prompt' in h.get('command', '')][0]
        claude_run = subprocess.run(['bash', '-c', claude_cmd], input='{"session_id":"c-1"}',
                                    capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(claude_run.returncode, 0, claude_run.stderr)
        self.assertIn('Token ladder: Claude ON; Codex ON sid=c-1', claude_run.stdout)

        codex_cmd = [h['command'] for h in user_prompt_hooks(home / '.codex' / 'hooks.json')
                     if 'token-ladder-prompt.py' in h.get('command', '')][0]
        codex_run = subprocess.run(['bash', '-c', codex_cmd], input='{"session_id":"x-1","prompt":"hi"}',
                                   capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(codex_run.returncode, 0, codex_run.stderr)
        codex_json = json.loads(codex_run.stdout)
        self.assertEqual(codex_json['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
        self.assertIn('sid=x-1', codex_json['hookSpecificOutput']['additionalContext'])

        agy_data = json.loads((home / '.gemini' / 'config' / 'hooks.json').read_text())
        agy_cmd = agy_data['vstack-token-ladder']['PreInvocation'][0]['command']
        first_payload = json.dumps({'conversationId': 'g-1', 'initialNumSteps': 2, 'invocationNum': 1})
        agy_first = subprocess.run(['bash', '-c', agy_cmd], input=first_payload,
                                   capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(agy_first.returncode, 0, agy_first.stderr)
        first_json = json.loads(agy_first.stdout)
        self.assertIn('sid=g-1', first_json['injectSteps'][0]['systemMessage']['systemMessage'])

        repeat_payload = json.dumps({'conversationId': 'g-1', 'initialNumSteps': 2, 'invocationNum': 2})
        agy_repeat = subprocess.run(['bash', '-c', agy_cmd], input=repeat_payload,
                                    capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(agy_repeat.returncode, 0, agy_repeat.stderr)
        self.assertEqual(json.loads(agy_repeat.stdout), {})

        next_payload = json.dumps({'conversationId': 'g-1', 'initialNumSteps': 7, 'invocationNum': 1})
        agy_next = subprocess.run(['bash', '-c', agy_cmd], input=next_payload,
                                  capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(agy_next.returncode, 0, agy_next.stderr)
        self.assertIn('sid=g-1', json.loads(agy_next.stdout)['injectSteps'][0]['systemMessage']['systemMessage'])

    def test_valentin_mode_skill_requires_token_ladder_prompt_source(self):
        skill = (ROOT / 'skills' / 'valentin-mode' / 'SKILL.md').read_text()
        pacer = skill.split('### Subscription pacer\n', 1)[1].split('\n### ', 1)[0]
        self.assertIn('Usage of any plan: run `~/.local/bin/plan-pick --plans`; '
                      'it is the one source, quote it, never guess.', pacer)

    def test_agy_dedupes_once_per_turn_when_initial_steps_arrive_as_a_string(self):
        home = self.scratch()
        ladder = plant_ladder(home / '.local' / 'bin' / 'token-ladder')
        hook = str(ROOT / 'hooks' / 'token-ladder-prompt.py')
        env = {'PATH': BARE_PATH, 'HOME': str(home)}
        payload = json.dumps({'conversationId': 'g5', 'initialNumSteps': '4', 'invocationNum': 1})

        first = subprocess.run([hook, '--harness', 'agy', '--ladder', str(ladder)], input=payload,
                               capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_json = json.loads(first.stdout)
        self.assertIn('sid=g5', first_json['injectSteps'][0]['systemMessage']['systemMessage'])

        second = subprocess.run([hook, '--harness', 'agy', '--ladder', str(ladder)], input=payload,
                                capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout), {})


if __name__ == '__main__':
    unittest.main()
