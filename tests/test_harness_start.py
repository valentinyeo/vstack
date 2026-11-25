"""A chat switched from Claude to Codex, Antigravity or Pi keeps valentin-mode (VSTA-305).

The test drives the hook the installer actually registered, in a throwaway HOME: the real
~/.codex, ~/.gemini and ~/.pi are never read or written.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BARE_PATH = '/usr/bin:/bin'
TAB = 'switched-chat'
CHAT = 'Switched Chat'
BOARD = 13556
LABEL = 'Switched'
SCRIPT = 'harness-start.py'


def loop_state_module(state_dir):
    """board-drain's loop-state, the one owner of the records this test plants."""
    os.environ['BOARD_DRAIN_STATE_DIR'] = str(state_dir)
    name = 'board_drain_loop_state'
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / 'skills/board-drain/loop-state'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def install(home):
    env = {
        **os.environ,
        'HOME': str(home),
        'PATH': BARE_PATH,
        'VSTACK_INSTALL_ANYWHERE': '1',
        'VSTACK_DIR': str(home / '.local' / 'share' / 'vstack'),
    }
    return subprocess.run([str(ROOT / 'install')], env=env, cwd=str(ROOT),
                          capture_output=True, text=True, timeout=180)


def entries(path, event):
    data = json.loads(path.read_text())
    return [hook for group in data.get('hooks', {}).get(event, [])
            if isinstance(group, dict)
            for hook in group.get('hooks', []) if isinstance(hook, dict)]


def ours(path, event, harness):
    return [hook for hook in entries(path, event)
            if SCRIPT in hook.get('command', '') and f'--harness {harness}' in hook.get('command', '')]


def run_hook(command, payload, home, state_dir, cwd):
    """Run the registered hook command the way the harness runs it."""
    env = {**os.environ, 'HOME': str(home), 'BOARD_DRAIN_STATE_DIR': str(state_dir),
           'MULTIBOT_SESSION': TAB, 'PATH': BARE_PATH}
    for key in ('ZSB_SESSION', 'MULTIPROMPT_TAB'):
        env.pop(key, None)
    return subprocess.run(command, shell=True, input=json.dumps(payload), env=env, cwd=str(cwd),
                          capture_output=True, text=True, timeout=30)


def context_of(stdout):
    if not stdout.strip():
        return ''
    answer = json.loads(stdout)
    return answer.get('hookSpecificOutput', {}).get('additionalContext', '')


class HarnessStartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = tempfile.TemporaryDirectory()
        cls.home = Path(cls.raw.name)
        cls.installed = install(cls.home)
        cls.codex = cls.home / '.codex' / 'hooks.json'
        cls.repo = cls.home / 'repo'
        cls.repo.mkdir()
        (cls.repo / 'AGENTS.md').write_text(f'Hypertask board: {BOARD}, label: {LABEL}\n')
        announce = cls.home / '.local' / 'state' / 'roster' / 'announce'
        announce.mkdir(parents=True)
        (announce / f'{TAB}.json').write_text(json.dumps({'tmux': TAB, 'multibot': CHAT}))
        # The installed view has no git history, so version.sh reads this stamp (VSTA-203).
        stamp = cls.home / '.local/state/vstack/skills/valentin-mode/VERSION'
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text('count=111\nlatest=111\n')

    @classmethod
    def tearDownClass(cls):
        cls.raw.cleanup()

    def setUp(self):
        self.state = Path(tempfile.mkdtemp(dir=self.home, prefix='state-'))
        self.addCleanup(lambda: subprocess.run(['rm', '-rf', str(self.state)], check=False))

    def test_install_wires_codex_start_and_prompt_once(self):
        self.assertEqual(self.installed.returncode, 0, self.installed.stderr)
        for event, marker in (('SessionStart', '--event start'),
                              ('UserPromptSubmit', '--event prompt')):
            mine = ours(self.codex, event, 'codex')
            self.assertEqual(len(mine), 1, f'{event} registers the hook exactly once: {mine!r}')
            self.assertIn(marker, mine[0]['command'])
            self.assertEqual(mine[0]['timeout'], 5, f'{event} is capped at 5 seconds')

        before = self.codex.read_text()
        again = install(self.home)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.codex.read_text(), before, 'a second install writes nothing')

        agy = json.loads((self.home / '.gemini/config/hooks.json').read_text())
        block = agy.get('vstack-valentin-mode', {})
        invocations = block.get('PreInvocation', [])
        self.assertEqual(len(invocations), 1, f'antigravity runs the start hook once: {invocations!r}')
        self.assertIn(SCRIPT, invocations[0]['command'])
        self.assertLessEqual(invocations[0]['timeout'], 5)

        extension = self.home / '.pi/agent/extensions/vstack-valentin-mode.ts'
        self.assertTrue(extension.is_symlink(), 'install links the Pi extension')

    def test_a_switched_codex_chat_gets_the_version_and_the_skill(self):
        hook = ours(self.codex, 'SessionStart', 'codex')[0]['command']
        done = run_hook(hook, {'hook_event_name': 'SessionStart', 'session_id': 'sid-start',
                               'cwd': str(self.repo)}, self.home, self.state, self.repo)
        self.assertEqual(done.returncode, 0, done.stderr)
        context = context_of(done.stdout)
        self.assertRegex(context, r'valentin-mode v\d+',
                         f'the start line carries the installed version: {context!r}')
        self.assertIn('valentin-mode/SKILL.md', context)
        self.assertIn('in full', context)

    def test_a_switched_codex_chat_is_told_to_arm_its_loop(self):
        loop = loop_state_module(self.state)
        loop.arm(CHAT, every='2h', job='cron-old', board=BOARD, label=LABEL)
        record = loop.state_path(CHAT)
        stale = json.loads(record.read_text())
        stale['owner_pid'] = 2_000_000_000     # a pid no process holds: the abandoned chat
        record.write_text(json.dumps(stale))

        hook = ours(self.codex, 'SessionStart', 'codex')[0]['command']
        done = run_hook(hook, {'hook_event_name': 'SessionStart', 'session_id': 'sid-arm',
                               'cwd': str(self.repo)}, self.home, self.state, self.repo)
        context = context_of(done.stdout)
        self.assertIn('not armed', context)
        self.assertIn('loop-state arm', context, f'the start line names the recording command: {context!r}')
        self.assertIn(f'--board {BOARD}', context)
        self.assertIn(f'--label "{LABEL}"', context)
        self.assertIn('plan-pick --loop-interval', context)
        self.assertIn('drain-check', context)

    def test_the_prompt_hook_repeats_the_rearm_line_once_per_ten_minutes(self):
        hook = ours(self.codex, 'UserPromptSubmit', 'codex')[0]['command']
        payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'sid-prompt',
                   'cwd': str(self.repo)}
        first = context_of(run_hook(hook, payload, self.home, self.state, self.repo).stdout)
        self.assertIn('loop-state arm', first, f'an unarmed chat is told to re-arm: {first!r}')
        again = context_of(run_hook(hook, payload, self.home, self.state, self.repo).stdout)
        self.assertEqual(again, '', 'the re-arm line is capped per session')

        loop = loop_state_module(self.state)
        loop.arm(CHAT, every='2h', job='cron-new', board=BOARD, label=LABEL)
        armed = context_of(run_hook(hook, {**payload, 'session_id': 'sid-armed'},
                                    self.home, self.state, self.repo).stdout)
        self.assertEqual(armed, '', 'an armed chat is not nagged')

    def test_install_keeps_foreign_codex_hooks(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            codex = home / '.codex' / 'hooks.json'
            codex.parent.mkdir(parents=True)
            foreign = {'type': 'command', 'command': 'echo keep-me'}
            codex.write_text(json.dumps({'hooks': {
                'SessionStart': [{'hooks': [foreign]}],
                'Stop': [{'hooks': [{'type': 'command', 'command': 'echo keep-stop'}]}],
            }}))
            done = install(home)
            self.assertEqual(done.returncode, 0, done.stderr)
            kept = entries(codex, 'SessionStart')
            self.assertTrue(any(hook.get('command') == 'echo keep-me' for hook in kept),
                            f'the hook already there stays: {kept!r}')
            self.assertEqual(len(entries(codex, 'Stop')), 1, 'an unrelated event is untouched')

    def test_the_hook_fails_open_on_a_bad_payload(self):
        hook = ours(self.codex, 'SessionStart', 'codex')[0]['command']
        env = {**os.environ, 'HOME': str(self.home), 'PATH': BARE_PATH}
        done = subprocess.run(hook, shell=True, input='not json', env=env, cwd=str(self.repo),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        if done.stdout.strip():
            self.assertIsInstance(json.loads(done.stdout), dict,
                                  'a hook that cannot read its payload still answers in JSON')

    def test_a_home_with_nothing_installed_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as raw:
            bare = Path(raw)
            done = subprocess.run(
                ['python3', str(ROOT / 'hooks' / SCRIPT), '--harness', 'pi', '--event', 'start'],
                input='{}', env={**os.environ, 'HOME': str(bare)}, cwd=str(bare),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn('valentin-mode/SKILL.md', done.stdout)


class HarnessStartHookSelfTest(unittest.TestCase):
    def test_self_test_passes(self):
        done = subprocess.run(['python3', str(ROOT / 'hooks' / SCRIPT), '--self-test'],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == '__main__':
    unittest.main()
