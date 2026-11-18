import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


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
            self.assertIn('Verifier model: glm-5.3-flash', (output / 'verdict.md').read_text())

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
