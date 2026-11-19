import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/column-verifier.py'
FAKE_NPX = '''#!/usr/bin/python3
import json
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
args = sys.argv[1:]
lane = args[args.index("--provider") + 1]
model = args[args.index("--model") + 1]
(here / "attempts.log").open("a").write(lane + " " + model + "\\n")
mode = json.loads((here / "plan.json").read_text()).get(model, "")
if mode == "429":
    sys.stderr.write("429 Too Many Requests: quota used up\\n")
    sys.exit(1)
if mode == "error":
    sys.exit(2)
if mode == "empty":
    sys.exit(0)
verdict = mode if mode in ("PASS", "PASS+NOTES", "FAIL") else (here / "verdict.txt").read_text().strip()
if (here / "dirty").exists():
    Path("tracked").write_text("changed")
print("\\n".join(json.dumps(event) for event in [
    dict(type="tool_execution_start", toolCallId="0", toolName="bash", args={"command": "printf one"}),
    dict(type="tool_execution_end", toolCallId="0", toolName="bash", isError=False,
         result={"structuredContent": {"output": "fixture output", "exit_code": 0}, "isError": False}),
    dict(type="message_end", message={"role": "assistant", "content": [
        {"type": "text", "text": "VERDICT: " + verdict}]}),
]))
'''
FAKE_PICKER = '''#!/usr/bin/env python3
import os
import sys

models = (os.environ.get("FAKE_MODELS") or os.environ["VERIFIER_MODEL"]).split()
if os.environ.get("FAKE_PICKER_NO_ALL") and "--all" in sys.argv:
    sys.exit(2)
print("\\n".join(models) if "--all" in sys.argv else models[0])
'''


class ColumnVerifierTests(unittest.TestCase):
    def run_verifier(self, commands_seen, dirty=False, verdict="PASS", required=None, plan=None, keys=None,
                     models=None, env_extra=None):
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
            fake_bin = root / 'bin'
            fake_bin.mkdir()
            npx = fake_bin / 'npx'
            npx.write_text(FAKE_NPX)
            npx.chmod(0o755)
            gh = fake_bin / 'gh'
            gh.write_text('#!/bin/sh\nexit 0\n')
            gh.chmod(0o755)
            (fake_bin / 'plan.json').write_text(json.dumps(plan or {}))
            (fake_bin / 'verdict.txt').write_text(verdict)
            if dirty:
                (fake_bin / 'dirty').write_text('1')
            workspace = root / 'workspace'
            picker_dir = workspace / 'picker-base/scripts'
            picker_dir.mkdir(parents=True)
            picker = picker_dir / 'pick-verifier-model'
            picker.write_text(FAKE_PICKER)
            picker.chmod(0o755)
            log = fake_bin / 'attempts.log'
            env = dict(os.environ, PATH=str(fake_bin) + ':' + os.environ['PATH'],
                       HEAD_SHA=sha, VERIFIER_MODEL='glm-5.3-flash', BASE_REF='main', BASE_SHA='0' * 40,
                       RUNNER_TEMP=str(root), GITHUB_WORKSPACE=str(workspace),
                       FAKE_MODELS=models or 'glm-5.3-flash',
                       VERIFY_COMMANDS=json.dumps(required if required is not None else ['printf one', 'printf two']),
                       PR_NUMBER='1', GITHUB_REPOSITORY='fixture/repo', GITHUB_RUN_ID='1')
            for name in ('OPENCODE_API_KEY', 'AI_GATEWAY_API_KEY'):
                env.pop(name, None)
            env.update({'OPENCODE_API_KEY': 'fixture-key'} if keys is None else keys)
            env.update(env_extra or {})
            result = subprocess.run(['/usr/bin/python3', str(SCRIPT)], cwd=root, env=env,
                                    capture_output=True, text=True)
            self.attempts = log.read_text().splitlines() if log.exists() else []
            comment = root / 'column-verifier/comment.md'
            return result.returncode, comment.read_text() if comment.exists() else result.stderr

    def test_pass_with_notes_accepts_successful_required_commands(self):
        code, body = self.run_verifier([], verdict='PASS+NOTES')
        self.assertEqual(code, 0, body)
        self.assertIn('pstack-verifier: PASS+NOTES', body)
        self.assertIn('Verifier model: opencode-go/glm-5.3-flash', body)

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

    def test_an_empty_reply_falls_through_to_the_next_model(self):
        code, body = self.run_verifier([], plan={'deepseek-v4.1-flash': 'empty'},
                                       models='deepseek-v4.1-flash\nglm-5.3-flash')
        self.assertEqual(code, 0, body)
        self.assertEqual(self.attempts, ['opencode-go deepseek-v4.1-flash', 'opencode-go glm-5.3-flash'])
        self.assertIn('Verifier model: opencode-go/glm-5.3-flash', body)
        self.assertIn('pstack-verifier: PASS', body)

    def test_a_429_falls_through_every_model_then_the_gateway(self):
        plan = {'deepseek-v4.1-flash': '429', 'glm-5.3-flash': 'empty',
                'deepseek/deepseek-v4.1-flash': 'error', 'zai/glm-5.3-flash': 'PASS+NOTES'}
        code, body = self.run_verifier([], plan=plan, models='deepseek-v4.1-flash\nglm-5.3-flash',
                                       keys={'OPENCODE_API_KEY': 'opencode-key',
                                             'AI_GATEWAY_API_KEY': 'gateway-key'})
        self.assertEqual(code, 0, body)
        self.assertEqual(self.attempts, ['opencode-go deepseek-v4.1-flash', 'opencode-go glm-5.3-flash',
                                         'vercel-ai-gateway deepseek/deepseek-v4.1-flash',
                                         'vercel-ai-gateway zai/glm-5.3-flash'])
        self.assertIn('Verifier model: vercel-ai-gateway/zai/glm-5.3-flash', body)
        self.assertIn('pstack-verifier: PASS+NOTES', body)

    def test_the_gateway_key_alone_is_enough(self):
        code, body = self.run_verifier([], keys={'AI_GATEWAY_API_KEY': 'gateway-key'})
        self.assertEqual(code, 0, body)
        self.assertEqual(self.attempts, ['vercel-ai-gateway zai/glm-5.3-flash'])
        self.assertIn('Verifier model: vercel-ai-gateway/zai/glm-5.3-flash', body)

    def test_no_key_stops_before_any_attempt(self):
        code, body = self.run_verifier([], keys={})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.attempts, [])
        self.assertIn('OPENCODE_API_KEY or AI_GATEWAY_API_KEY', body)

    def test_an_older_picker_without_all_still_checks_the_verifier_model(self):
        code, body = self.run_verifier([], env_extra={'FAKE_PICKER_NO_ALL': '1'})
        self.assertEqual(code, 0, body)
        self.assertEqual(self.attempts, ['opencode-go glm-5.3-flash'])

    def test_every_lane_failing_reports_fail_and_names_the_last_attempt(self):
        code, body = self.run_verifier([], plan={'glm-5.3-flash': 'empty', 'kimi-k3': '429'},
                                       models='glm-5.3-flash\nkimi-k3')
        self.assertNotEqual(code, 0)
        self.assertEqual(self.attempts, ['opencode-go glm-5.3-flash', 'opencode-go kimi-k3'])
        self.assertIn('pstack-verifier: FAIL', body)
        self.assertIn('no verdict on opencode-go/kimi-k3', body)
