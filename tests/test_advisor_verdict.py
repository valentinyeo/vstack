import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verification/advisor.py'
HEAD = 'a' * 40


class AdvisorVerdict(unittest.TestCase):
    def drive(self, content, error=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.claude/plugins/cache/cursor-plugins/pstack/0.15.43').mkdir(parents=True)
            brief = root / '.github/briefs/shared-worker-rules.md'
            brief.parent.mkdir(parents=True)
            brief.write_text('Fixture worker rules.\n')
            responses = [
                {'choices': [{'message': {'role': 'assistant', 'content': None,
                    'tool_calls': [{'id': 'probe', 'type': 'function', 'function': {
                        'name': 'run_command', 'arguments': json.dumps({'command': 'printf smoke-evidence'})}}]}}]},
                {'choices': [{'message': {'role': 'assistant', 'content': content}}]},
            ]
            env = {'HOME': directory, 'VERIFIER_MODEL': 'glm-5.3-flash',
                   'HEAD_SHA': HEAD, 'OPENCODE_API_KEY': 'test-only', 'GITHUB_RUN_ID': 'fixture'}
            with contextlib.chdir(root), patch.dict(os.environ, env), \
                    patch('urllib.request.urlopen', side_effect=[io.BytesIO(json.dumps(r).encode()) for r in responses]), \
                    contextlib.redirect_stdout(io.StringIO()):
                if error:
                    with self.assertRaises(error):
                        runpy.run_path(str(SCRIPT), run_name='__main__')
                    self.assertFalse((root / 'evidence/verdict.json').exists())
                    return
                runpy.run_path(str(SCRIPT), run_name='__main__')
            output = root / 'evidence'
            self.assertEqual(json.loads((output / 'verdict.json').read_text()), self.verdict())
            self.assertEqual((output / 'verdict.txt').read_bytes(), content.encode())
            self.assertIn('smoke-evidence', (output / 'commands.log').read_text())
            self.assertIn('Verifier model: opencode-go/glm-5.3-flash', (output / 'verdict.md').read_text())

    def verdict(self, head=HEAD):
        return {'verdict': 'PASS+NOTES', 'head_sha': head, 'evidence': ['smoke'],
                'break_attempts': [], 'notes': []}

    def test_json_reports_with_optional_fence_and_preamble(self):
        raw = json.dumps(self.verdict())
        for content in (raw, f'```json\n{raw}\n```', f'```JSON\n{raw}\n```',
                        f'``` json\n{raw}\n```', f'```jsonc\n{raw}\n```',
                        f'```json\n{raw}', f'```json\r\n{raw}\r\n```',
                        f'Evidence complete. Final report:\n\n```json\n{raw}\n```'):
            with self.subTest(content=content[:40]):
                self.drive(content)

    def test_preamble_does_not_bypass_head_validation(self):
        raw = json.dumps(self.verdict('b' * 40))
        self.drive(f'Final report:\n```json\n{raw}\n```', AssertionError)

    def test_ambiguous_fenced_reports_are_rejected(self):
        block = f'```json\n{json.dumps(self.verdict())}\n```'
        self.drive(block + '\n' + block, ValueError)


FAKE_PICKER = '''#!/usr/bin/env python3
import os
import sys

models = (os.environ.get("FAKE_MODELS") or os.environ["VERIFIER_MODEL"]).split()
if os.environ.get("FAKE_PICKER_NO_ALL") and "--all" in sys.argv:
    sys.exit(2)
print("\\n".join(models) if "--all" in sys.argv else models[0])
'''
OPENCODE = 'https://opencode.ai/zen/go/v1/chat/completions'
GATEWAY = 'https://ai-gateway.vercel.sh/v1/chat/completions'
PROBE = {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
    {'id': 'probe', 'type': 'function', 'function': {
        'name': 'run_command', 'arguments': json.dumps({'command': 'printf smoke-evidence'})}}]}}]}


def final(content):
    return {'choices': [{'message': {'role': 'assistant', 'content': content}}]}


def http_error(code):
    return urllib.error.HTTPError(OPENCODE, code, 'provider refused', {}, io.BytesIO(b'quota used up'))


class AdvisorLanes(unittest.TestCase):
    def provider(self, steps):
        self.seen = []

        def open_url(request, timeout=None):
            self.seen.append((request.full_url, request.get_header('Authorization'),
                              request.get_header('X-opencode-session'), json.loads(request.data)['model']))
            step = steps.pop(0)
            if isinstance(step, Exception):
                raise step
            return io.BytesIO(json.dumps(step).encode())

        return open_url

    def run_advisor(self, steps, keys=None, models='glm-5.3-flash', env_extra=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.claude/plugins/cache/cursor-plugins/pstack/0.15.43').mkdir(parents=True)
            brief = root / '.github/briefs/shared-worker-rules.md'
            brief.parent.mkdir(parents=True)
            brief.write_text('Fixture worker rules.\n')
            workspace = root / 'workspace'
            (workspace / 'picker-base/scripts').mkdir(parents=True)
            picker = workspace / 'picker-base/scripts/pick-verifier-model'
            picker.write_text(FAKE_PICKER)
            env = {k: v for k, v in os.environ.items()
                   if k not in ('OPENCODE_API_KEY', 'AI_GATEWAY_API_KEY', 'GITHUB_WORKSPACE', 'GITHUB_RUN_ID')}
            env.update({'HOME': directory, 'VERIFIER_MODEL': 'glm-5.3-flash', 'HEAD_SHA': HEAD,
                        'GITHUB_RUN_ID': 'fixture', 'GITHUB_WORKSPACE': str(workspace),
                        'FAKE_MODELS': models})
            env.update({'OPENCODE_API_KEY': 'opencode-key'} if keys is None else keys)
            env.update(env_extra or {})
            outcome = None
            with contextlib.chdir(root), patch.dict(os.environ, env, clear=True), \
                    patch('urllib.request.urlopen', side_effect=self.provider(steps)), \
                    contextlib.redirect_stdout(io.StringIO()):
                try:
                    runpy.run_path(str(SCRIPT), run_name='__main__')
                except SystemExit as stop:
                    outcome = stop.code
            written = root / 'evidence'
            returned = (outcome,
                        (written / 'verdict.md').read_text() if (written / 'verdict.md').exists() else None,
                        json.loads((written / 'verdict.json').read_text())
                        if (written / 'verdict.json').exists() else None,
                        self.seen)
        return returned

    def verdict(self):
        return {'verdict': 'PASS+NOTES', 'head_sha': HEAD, 'evidence': ['smoke'],
                'break_attempts': [], 'notes': []}

    def report(self):
        return json.dumps(self.verdict())

    def test_a_429_restarts_the_run_on_the_next_model(self):
        outcome, md, report, _ = self.run_advisor(
            [http_error(429), PROBE, final(self.report())],
            models='deepseek-v4.1-flash\nglm-5.3-flash')
        self.assertIsNone(outcome)
        self.assertEqual([model for url, auth, session, model in self.seen],
                         ['deepseek-v4.1-flash', 'glm-5.3-flash', 'glm-5.3-flash'])
        self.assertIn('Verifier model: opencode-go/glm-5.3-flash', md)
        self.assertEqual(report, self.verdict())

    def test_an_empty_reply_restarts_the_run(self):
        outcome, md, _, _ = self.run_advisor(
            [final(''), PROBE, final(self.report())],
            models='deepseek-v4.1-flash\nglm-5.3-flash')
        self.assertIsNone(outcome)
        self.assertEqual(len(self.seen), 3)
        self.assertIn('Verifier model: opencode-go/glm-5.3-flash', md)

    def test_every_opencode_model_runs_before_the_gateway(self):
        outcome, md, _, _ = self.run_advisor(
            [http_error(429), final(''), PROBE, final(self.report())],
            keys={'OPENCODE_API_KEY': 'opencode-key', 'AI_GATEWAY_API_KEY': 'gateway-key'},
            models='deepseek-v4.1-flash\nglm-5.3-flash')
        self.assertIsNone(outcome)
        self.assertEqual([(url, model) for url, auth, session, model in self.seen], [
            (OPENCODE, 'deepseek-v4.1-flash'), (OPENCODE, 'glm-5.3-flash'),
            (GATEWAY, 'deepseek/deepseek-v4.1-flash'), (GATEWAY, 'deepseek/deepseek-v4.1-flash')])
        self.assertIn('Verifier model: vercel-ai-gateway/deepseek/deepseek-v4.1-flash', md)

    def test_the_gateway_key_alone_is_enough(self):
        outcome, md, _, _ = self.run_advisor(
            [PROBE, final(self.report())],
            keys={'AI_GATEWAY_API_KEY': 'gateway-key'})
        self.assertIsNone(outcome)
        self.assertEqual([(url, auth, session, model) for url, auth, session, model in self.seen],
                         [(GATEWAY, 'Bearer gateway-key', None, 'zai/glm-5.3-flash'),
                          (GATEWAY, 'Bearer gateway-key', None, 'zai/glm-5.3-flash')])
        self.assertIn('Verifier model: vercel-ai-gateway/zai/glm-5.3-flash', md)

    def test_payment_and_server_errors_restart_too(self):
        for code in (402, 500, 503):
            with self.subTest(code=code):
                outcome, _, _, _ = self.run_advisor([http_error(code), PROBE, final(self.report())],
                                                    models='deepseek-v4.1-flash\nglm-5.3-flash')
                self.assertIsNone(outcome)
                self.assertEqual(len(self.seen), 3)

    def test_a_client_error_other_than_quota_still_stops_at_once(self):
        outcome, md, _, _ = self.run_advisor([http_error(400), PROBE, final(self.report())],
                                             models='deepseek-v4.1-flash\nglm-5.3-flash')
        self.assertEqual(outcome, 1)
        self.assertEqual(len(self.seen), 1)
        self.assertIsNone(md)

    def test_no_lane_giving_a_verdict_stops_with_the_last_reason(self):
        outcome, md, report, _ = self.run_advisor(
            [http_error(429), http_error(429)],
            models='deepseek-v4.1-flash\nglm-5.3-flash')
        self.assertIn('HTTP 429 from opencode-go/glm-5.3-flash', str(outcome))
        self.assertIsNone(md)
        self.assertIsNone(report)

    def test_an_answer_without_a_report_moves_on_when_a_lane_remains(self):
        outcome, md, _, _ = self.run_advisor([PROBE, final('I think it is fine.'),
                                             PROBE, final(self.report())],
                                            models='deepseek-v4.1-flash\nglm-5.3-flash')
        self.assertIsNone(outcome)
        self.assertIn('Verifier model: opencode-go/glm-5.3-flash', md)

    def test_the_last_answer_without_a_report_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_advisor([PROBE, final('I think it is fine.')])

    def test_an_older_picker_without_all_falls_back_to_the_verifier_model(self):
        outcome, md, _, _ = self.run_advisor([PROBE, final(self.report())],
                                             env_extra={'FAKE_PICKER_NO_ALL': '1'})
        self.assertIsNone(outcome)
        self.assertEqual({model for url, auth, session, model in self.seen}, {'glm-5.3-flash'})
        self.assertIn('Verifier model: opencode-go/glm-5.3-flash', md)
