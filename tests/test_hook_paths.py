"""Replay VSTA-156's missing UserPromptSubmit hook without touching a real home."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / 'scripts/check-hook-paths'
LAUNCHER = ROOT / 'hooks/run-hook'
FIXTURE = ROOT / 'tests/fixtures/hook-paths/skill-update-missing.json'
ORCA = ROOT / 'tests/fixtures/hook-paths/orca-inline-guard.json'


class HookPaths(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / 'project'
        self.project.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home)}

    def settings(self, path, command):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'hooks': {'UserPromptSubmit': [
            {'hooks': [{'type': 'command', 'command': command}]}]}}))

    def check(self, *args):
        return subprocess.run(['python3', str(CHECK), *map(str, args)], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def launch(self, script, *args):
        return subprocess.run([str(LAUNCHER), str(script), *args], env=self.env,
                              input='the prompt goes through\n', capture_output=True,
                              text=True, timeout=10)

    def test_real_global_settings_with_absent_skill_update_fails(self):
        path = self.home / '.claude/settings.json'
        path.parent.mkdir()
        shutil.copyfile(FIXTURE, path)
        before = path.read_bytes()
        result = self.check('--root', self.project)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for expected in (str(path), 'UserPromptSubmit', 'skill-update.py',
                         'reinstall vstack: ~/.local/share/vstack/install', 'remove the hook'):
            self.assertIn(expected, result.stderr)
        self.assertEqual(path.read_bytes(), before)
        script = self.home / '.claude/hooks/skill-update.py'
        script.parent.mkdir()
        script.write_text('')
        self.assertEqual(self.check('--root', self.project).returncode, 0)

    def test_global_local_and_nested_project_settings_are_checked(self):
        for path in (self.home / '.claude/settings.local.json',
                     self.project / '.claude/settings.json',
                     self.project / 'nested/.claude/settings.local.json'):
            self.settings(path, 'python3 "$CLAUDE_PROJECT_DIR/missing.py"')
        result = self.check('--root', self.project)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.count('; command '), 3, result.stderr)

    def test_wrapped_target_is_checked_not_just_the_launcher(self):
        self.settings(self.project / '.claude/settings.json',
                      f'"{LAUNCHER}" "$CLAUDE_PROJECT_DIR/missing.py"')
        result = self.check('--root', self.project)
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(self.project / 'missing.py'), result.stderr)
        self.assertNotIn(f'missing {LAUNCHER};', result.stderr)

    def test_inline_script_that_file_tests_its_own_script_passes(self):
        # Copied verbatim from ~/.claude/settings.json hooks.PostToolBatch[0] (Orca).
        path = self.home / '.claude/settings.json'
        path.parent.mkdir()
        shutil.copyfile(ORCA, path)
        before = path.read_bytes()
        result = self.check('--root', self.project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_sh_c_guard_that_exits_when_its_script_is_absent_passes(self):
        self.settings(self.project / '.claude/settings.json',
                      'sh -c \'f="$HOME/.claude/hooks/launch-gate.py"; '
                      '[ -f "$f" ] || exit 0; exec python3 "$f"\'')
        self.assertEqual(self.check('--root', self.project).returncode, 0)

    def test_plain_missing_script_still_fails(self):
        script = self.home / '.claude/hooks/gone.py'
        for command in (f'python3 {script}', '/abs/missing.sh',
                        f'[ -f {self.home}/present.sh ] || exit 0; {script}'):
            with self.subTest(command=command):
                self.settings(self.project / '.claude/settings.json', command)
                result = self.check('--root', self.project)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(str(script) if str(script) in command else '/abs/missing.sh',
                              result.stderr)

    def test_deleted_hook_allows_prompt_and_logs_once(self):
        hook = self.home / 'skill-update.py'
        hook.write_text('#!/usr/bin/env python3\nprint("must not run")\n')
        hook.chmod(0o755)
        hook.unlink()
        result = self.launch(hook)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertIn(str(hook), result.stderr)
        log = self.home / '.local/state/vstack/hook-missing.log'
        self.assertEqual(log.read_text(), result.stderr)
        # The caller receives success, so a UserPromptSubmit hook cannot drop the prompt.
        prompt = subprocess.run(['sh', '-c', '"$1" "$2" && cat', 'sh', str(LAUNCHER), str(hook)],
                                input='the prompt goes through\n', env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(prompt.returncode, 0)
        self.assertEqual(prompt.stdout, 'the prompt goes through\n')

    def test_non_executable_and_dangling_link_fail_open(self):
        script = self.home / 'not-executable'
        script.write_text('#!/bin/sh\nexit 2\n')
        link = self.home / 'broken-link'
        link.symlink_to(self.home / 'gone.py')
        for path in (script, link):
            with self.subTest(path=path):
                result = self.launch(path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(str(path), result.stderr)

    def test_logging_failure_does_not_drop_prompt(self):
        (self.home / '.local').write_text('not a directory')
        result = self.launch(self.home / 'missing.py')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stderr.splitlines()), 1)

    def test_existing_block_is_preserved_with_stdin_args_and_output(self):
        hook = self.home / 'guard with spaces'
        hook.write_text('#!/usr/bin/env python3\nimport sys\n'
                        'print(sys.stdin.read().strip() + sys.argv[1])\n'
                        'print("intentional block", file=sys.stderr)\nsys.exit(2)\n')
        hook.chmod(0o755)
        result = self.launch(hook, ' argument')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, 'the prompt goes through argument\n')
        self.assertEqual(result.stderr, 'intentional block\n')
        self.assertFalse((self.home / '.local/state/vstack/hook-missing.log').exists())

    def test_install_migrates_owned_commands_and_renders_skill_hooks(self):
        settings = self.home / '.claude/settings.json'
        settings.parent.mkdir()
        shutil.copyfile(FIXTURE, settings)
        settings.chmod(0o600)
        local = self.home / '.claude/settings.local.json'
        self.settings(local, 'python3 ~/.claude/hooks/user-owned.py')
        unrelated = local.read_bytes()
        source = (ROOT / 'skills/valentin-mode/SKILL.md').read_bytes()
        staged = self.home / '.local/state/vstack/skills/valentin-mode'
        staged.parent.mkdir(parents=True)
        staged.symlink_to(ROOT / 'skills/valentin-mode')
        env = {**self.env, 'VSTACK_INSTALL_ANYWHERE': '1',
               'VSTACK_DIR': str(self.home / '.local/share/vstack')}
        for _ in range(2):
            result = subprocess.run([str(ROOT / 'install')], env=env,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(settings.stat().st_mode & 0o777, 0o600)
        command = json.loads(settings.read_text())['hooks']['UserPromptSubmit'][0]['hooks'][0]['command']
        self.assertEqual(command.count('hooks/run-hook'), 1)
        self.assertEqual(local.read_bytes(), unrelated)
        self.assertEqual((ROOT / 'skills/valentin-mode/SKILL.md').read_bytes(), source)
        skill = self.home / '.claude/skills/valentin-mode'
        installed = (skill / 'SKILL.md').read_text()
        commands = [line.split('command:', 1)[1].strip() for line in installed.splitlines()
                    if line.strip().startswith('command:')]
        self.assertEqual(len(commands), 4)
        self.assertTrue(all('hooks/run-hook' in c for c in commands))
        # Remove the installed script, then invoke the actual installed frontmatter command.
        (skill / 'context.py').unlink()
        done = subprocess.run(['sh', '-c', commands[0]],
                              env={**env, 'CLAUDE_PLUGIN_ROOT': str(skill)},
                              input='{}', capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('context.py', done.stderr)

    def test_repo_mode_never_checks_home_settings(self):
        self.settings(self.home / '.claude/settings.json', 'python3 /absent.py')
        self.assertEqual(self.check('--repo', self.project).returncode, 0)

    def test_deletion_fails_for_each_shipped_reference_kind(self):
        for source, contents in (
            ('.claude/settings.json', FIXTURE.read_text()),
            ('config/merge-hooks.json', FIXTURE.read_text()),
            ('skills/example/setup.md', '```json\n' + FIXTURE.read_text() + '```\n'),
            ('skills/example/SKILL.md', '---\nhooks:\n  Stop:\n    command: python3 "$CLAUDE_PLUGIN_ROOT/gone.py"\n---\n'),
            ('scripts/merge-hooks.py', 'snippet = ' + FIXTURE.read_text()),
            ('install', 'link_one skill-update.py "$ROOT/hooks/skill-update.py" "$HOME/.claude/hooks"\n'),
        ):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as raw:
                repo = Path(raw)
                path = repo / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
                result = self.check('--repo', repo)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(str(path), result.stderr)
                self.assertIn('gone.py' if 'SKILL' in source else 'skill-update.py', result.stderr)

    def test_repository_wiring_passes(self):
        result = self.check('--repo', ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
