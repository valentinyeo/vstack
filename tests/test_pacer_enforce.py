import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'hooks/pacer-guard.py'
CHECK = ROOT / 'scripts/pacer-check.py'


def run_script(script, args, payload=None, tab=False):
    env = {'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', '/tmp')}
    env['MULTIPROMPT_TAB'] = 'tab-1' if tab else ''
    if not tab:
        env.pop('MULTIPROMPT_TAB')
    return subprocess.run([sys.executable, str(script), *args], input=payload, text=True,
                          capture_output=True, env=env, cwd=str(ROOT))


class PacerGuard(unittest.TestCase):
    def guard(self, tool, tool_input, tab=True):
        payload = json.dumps({'tool_name': tool, 'tool_input': tool_input})
        result = run_script(GUARD, [], payload, tab=tab)
        return result.returncode, result.stderr

    def test_a_code_write_from_valentins_chat_is_blocked(self):
        code, why = self.guard('Write', {'file_path': 'x.py', 'content': 'print(1)\n'})
        self.assertEqual(code, 2)
        self.assertIn('pacer-guard', why)
        self.assertIn('plan-pick --run', why)

    def test_a_code_write_from_a_fleet_run_passes(self):
        code, why = self.guard('Write', {'file_path': 'x.py', 'content': 'print(1)\n'}, tab=False)
        self.assertEqual(code, 0)
        self.assertEqual(why, '')

    def test_docs_and_briefs_pass(self):
        for path in ('notes.md', 'brief.txt'):
            with self.subTest(path=path):
                code, why = self.guard('Write', {'file_path': path, 'content': 'words\n'})
                self.assertEqual(code, 0)
                self.assertEqual(why, '')

    def test_a_workflow_edit_is_blocked(self):
        code, why = self.guard('Edit', {'file_path': '.github/workflows/a.yml',
                                        'old_string': 'a', 'new_string': 'b'})
        self.assertEqual(code, 2)

    def test_a_heredoc_into_a_script_is_blocked(self):
        code, why = self.guard('Bash', {'command': 'cat > foo.sh <<EOF\n#!/bin/sh\necho hi\nEOF'})
        self.assertEqual(code, 2)

    def test_redirecting_docs_is_allowed(self):
        code, why = self.guard('Bash', {'command': 'ls > out.txt'})
        self.assertEqual(code, 0)
        self.assertEqual(why, '')


class PacerCheck(unittest.TestCase):
    def check(self, body, changed):
        with tempfile.TemporaryDirectory() as where:
            body_file = Path(where, 'body.md')
            files_file = Path(where, 'changed.txt')
            body_file.write_text(body)
            files_file.write_text('\n'.join(changed) + '\n')
            result = run_script(CHECK, ['--body-file', str(body_file),
                                        '--changed-files-file', str(files_file)])
        return result.returncode, result.stdout.strip()

    def test_a_claude_authored_code_change_fails(self):
        code, out = self.check('Author model: anthropic/claude-opus-5-5\n'
                               'Pacer launch: vercel 2026-11-19T22:00:00Z\n',
                               ['hooks/pacer-guard.py'])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('pacer-check: FAIL'), out)
        self.assertIn('anthropic/claude-opus-5-5', out)

    def test_a_code_change_with_no_pacer_launch_fails(self):
        code, out = self.check('Author model: deepseek/deepseek-v4.1-flash\n'
                               'Owner chat: PR Housekeeping\n', ['x.py'])
        self.assertEqual(code, 1)
        self.assertIn('Pacer launch', out)

    def test_a_code_change_with_no_owner_chat_fails(self):
        code, out = self.check('Author model: deepseek/deepseek-v4.1-flash\n'
                               'Pacer launch: vercel 2026-11-19T22:00:00Z\n', ['x.py'])
        self.assertEqual(code, 1)
        self.assertIn('Owner chat', out)

    def test_a_worker_code_change_passes(self):
        code, out = self.check('Author model: deepseek/deepseek-v4.1-flash\n'
                               'Pacer launch: vercel 2026-11-19T22:00:00Z\n'
                               'Owner chat: PR Housekeeping\n', ['x.py'])
        self.assertEqual((code, out), (0, 'pacer-check: PASS'))

    def test_a_docs_only_change_from_a_claude_author_passes(self):
        code, out = self.check('Author model: anthropic/claude-opus-5-5\n', ['notes.md', 'brief.txt'])
        self.assertEqual((code, out), (0, 'pacer-check: PASS'))

    def test_an_extensionless_script_in_scripts_is_code(self):
        code, out = self.check('Author model: anthropic/claude-opus-5-5\n', ['scripts/run-verifier'])
        self.assertEqual(code, 1)


if __name__ == '__main__':
    unittest.main()
