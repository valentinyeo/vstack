import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/column-verifier.py'


class ColumnVerifierTests(unittest.TestCase):
    def run_verifier(self, commands_seen, dirty=False, verdict="PASS", required=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@users.noreply.github.com')
            (root / 'tracked').write_text('original')
            git('add', 'tracked')
            git('commit', '-qm', 'fixture')
            sha = git('rev-parse', 'HEAD')
            git('update-ref', 'refs/remotes/origin/main', sha)
            events = []
            for n, command in enumerate(commands_seen):
                events += [dict(type='tool_execution_start', toolCallId=str(n), toolName='bash', args={'command': command}),
                           dict(type='tool_execution_end', toolCallId=str(n), toolName='bash', isError=False,
                                result={'structuredContent': {'output': 'fixture output', 'exit_code': 0}, 'isError': False})]
            events.append(dict(type='message_end', message={'role': 'assistant', 'content': [
                {'type': 'text', 'text': 'VERDICT: ' + verdict}]}))
            fake_bin = root / 'bin'
            fake_bin.mkdir()
            trace = '\n'.join(json.dumps(e) for e in events)
            npx = fake_bin / 'npx'
            npx.write_text('#!/usr/bin/python3\nfrom pathlib import Path\n' +
                           ('Path("tracked").write_text("changed")\n' if dirty else '') +
                           'print(' + repr(trace) + ')\n')
            npx.chmod(0o755)
            gh = fake_bin / 'gh'
            gh.write_text('#!/bin/sh\nexit 0\n')
            gh.chmod(0o755)
            env = dict(os.environ, PATH=str(fake_bin) + ':' + os.environ['PATH'],
                       HEAD_SHA=sha, BASE_REF='main', BASE_SHA='0' * 40,
                       RUNNER_TEMP=str(root), OPENCODE_API_KEY='fixture-key',
                       VERIFY_COMMANDS=json.dumps(required if required is not None else ['printf one', 'printf two']),
                       PR_NUMBER='1', GITHUB_REPOSITORY='fixture/repo', GITHUB_RUN_ID='1')
            result = subprocess.run(['/usr/bin/python3', str(SCRIPT)], cwd=root, env=env,
                                    capture_output=True, text=True)
            comment = root / 'column-verifier/comment.md'
            return result.returncode, comment.read_text() if comment.exists() else result.stderr

    def test_pass_with_notes_accepts_successful_required_commands(self):
        code, body = self.run_verifier([], verdict='PASS+NOTES')
        self.assertEqual(code, 0, body)
        self.assertIn('pstack-verifier: PASS+NOTES', body)

    def test_fail_verdict_still_fails(self):
        code, body = self.run_verifier([], verdict='FAIL')
        self.assertNotEqual(code, 0, body)
        self.assertIn('pstack-verifier: FAIL', body)

    def test_required_commands_run_even_when_agent_wraps_them(self):
        code, body = self.run_verifier(['printf one 2>&1 | tail -40'], verdict='PASS+NOTES')
        self.assertEqual(code, 0, body)
        self.assertIn('pstack-verifier: PASS+NOTES', body)

    def test_failed_required_command_overrides_pass(self):
        code, body = self.run_verifier(['printf one', 'printf two'],
                                       required=['printf one', 'printf two; exit 1'])
        self.assertNotEqual(code, 0, body)
        self.assertIn('pstack-verifier: FAIL', body)

    def test_empty_required_command_output_overrides_pass(self):
        code, body = self.run_verifier([], required=['true'])
        self.assertNotEqual(code, 0, body)
        self.assertIn('pstack-verifier: FAIL', body)

    def test_complete_command_evidence_can_pass(self):
        code, body = self.run_verifier(['printf one', 'printf two'])
        self.assertEqual(code, 0, body)
        self.assertIn('pstack-verifier: PASS', body)

    def test_correct_checkout_cd_prefix_preserves_execution_evidence(self):
        code, body = self.run_verifier(['cd . && printf one', 'cd . && printf two'])
        self.assertEqual(code, 0, body)
        self.assertIn('pstack-verifier: PASS', body)

    def test_tracked_edits_fail_verification(self):
        code, body = self.run_verifier(['printf one && printf two'], dirty=True)
        self.assertNotEqual(code, 0)
        self.assertIn('pstack-verifier: FAIL', body)

    def test_agent_claims_do_not_replace_required_execution(self):
        code, body = self.run_verifier(["echo 'printf one && printf two'"],
                                       required=['exit 1'])
        self.assertNotEqual(code, 0, body)
        self.assertIn('pstack-verifier: FAIL', body)

    def test_invalid_verdict_does_not_match_pass_prefix(self):
        for verdict in ('PASS+NOTES-invalid', 'PASS+NOTESX', 'PASS+UNKNOWN', 'PASSING', ''):
            with self.subTest(verdict=verdict):
                code, body = self.run_verifier([], verdict=verdict)
                self.assertNotEqual(code, 0, body)
                self.assertIn('pstack-verifier: FAIL', body)
