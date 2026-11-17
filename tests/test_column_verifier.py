import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/column-verifier.py'


class ColumnVerifierTests(unittest.TestCase):
    def run_verifier(self, commands_seen, dirty=False, output=True, exit_code=0):
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
                                result={'structuredContent': {'output': 'fixture output' if output else '',
                                                              'exit_code': exit_code}, 'isError': False})]
            events.append(dict(type='message_end', message={'role': 'assistant', 'content': [
                {'type': 'text', 'text': 'VERDICT: PASS'}]}))
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
                       VERIFY_COMMANDS=json.dumps(['printf one', 'printf two']),
                       PR_NUMBER='1', GITHUB_REPOSITORY='fixture/repo', GITHUB_RUN_ID='1')
            result = subprocess.run(['/usr/bin/python3', str(SCRIPT)], cwd=root, env=env,
                                    capture_output=True, text=True)
            comment = root / 'column-verifier/comment.md'
            return result.returncode, comment.read_text() if comment.exists() else result.stderr

    def test_pass_requires_every_command(self):
        for commands in ([], ['printf one']):
            with self.subTest(commands=commands):
                code, body = self.run_verifier(commands)
                self.assertNotEqual(code, 0)
                self.assertIn('pstack-verifier: FAIL', body)

    def test_complete_command_evidence_can_pass(self):
        code, body = self.run_verifier(['printf one', 'printf two'])
        self.assertEqual(code, 0, body)
        self.assertIn('pstack-verifier: PASS', body)

    def test_tracked_edits_fail_verification(self):
        code, body = self.run_verifier(['printf one && printf two'], dirty=True)
        self.assertNotEqual(code, 0)
        self.assertIn('pstack-verifier: FAIL', body)

    def test_echoed_command_names_are_not_execution(self):
        code, body = self.run_verifier(["echo 'printf one && printf two'"])
        self.assertNotEqual(code, 0, body)
        self.assertIn('pstack-verifier: FAIL', body)

    def test_empty_or_failed_tool_results_are_not_evidence(self):
        for options in ({'output': False}, {'exit_code': 1}):
            with self.subTest(options=options):
                code, body = self.run_verifier(['printf one', 'printf two'], **options)
                self.assertNotEqual(code, 0, body)
