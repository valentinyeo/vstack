import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/verdict.py'
PR129 = ROOT / 'tests/fixtures/verdict/pr-129-verifier-comment.md'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


verdict = load('shared_verdict', SCRIPT)


class VerdictForms(unittest.TestCase):
    def read(self, text):
        return verdict.find_verdict(text)[0]

    def test_bare_line(self):
        for token in ('PASS', 'PASS+NOTES', 'FAIL'):
            with self.subTest(token=token):
                self.assertEqual(self.read(f'Checked everything.\n\n{token}\n'), token)
                self.assertEqual(self.read(f'  {token}  \n'), token)

    def test_verdict_prefix_anywhere_in_the_answer(self):
        # PR 129: the text started with prose and ended with the prefixed line.
        text = 'Verifier model: deepseek.\n\n## What I ran\n\n- tests\n\nVERDICT: PASS+NOTES\n'
        self.assertEqual(self.read(text), 'PASS+NOTES')
        self.assertEqual(self.read('VERDICT: FAIL'), 'FAIL')
        self.assertEqual(self.read('verdict: pass'), None)

    def test_json_field(self):
        self.assertEqual(self.read('{"verdict": "PASS+NOTES"}'), 'PASS+NOTES')
        self.assertEqual(self.read('```json\n{"verdict": "PASS", "evidence": []}\n```'), 'PASS')
        self.assertEqual(self.read('{"status": "PASS"}'), None)

    def test_last_verdict_wins(self):
        self.assertEqual(self.read('VERDICT: FAIL\n\nThen I re-ran the suite.\n\nPASS+NOTES\n'), 'PASS+NOTES')
        self.assertEqual(self.read('PASS\n\nsome later text\n\nVERDICT: FAIL\n'), 'FAIL')
        self.assertEqual(self.read('{"verdict": "PASS"}\n\nVERDICT: FAIL\n'), 'FAIL')
        self.assertEqual(self.read('FAIL\n\n{"verdict": "PASS"}\n'), 'PASS')

    def test_no_verdict_fails_with_a_message(self):
        for text in ('', 'Looks good to me.', 'PASSING', 'PASS+NOTES-invalid', 'PASS+UNKNOWN',
                     'VERDICT: PASS+NOTESX', '**PASS**', 'The verdict: PASS'):
            with self.subTest(text=text):
                self.assertEqual(verdict.find_verdict(text),
                                 (None, verdict.MISSING), text)

    def test_bare_lines_inside_fenced_evidence_are_not_the_answer(self):
        text = 'Quoted log:\n\n```\nFAIL\n```\n\nEverything green.\n\nPASS\n'
        self.assertEqual(self.read(text), 'PASS')
        self.assertEqual(self.read('Checked.\n\n```text\nPASS\n```\n'), None)
        # A prefixed or JSON verdict inside a fence is still the answer, not evidence.
        self.assertEqual(self.read('```\nVERDICT: FAIL\n```\n'), 'FAIL')

    def test_pr_129_comment_reads_pass_notes(self):
        self.assertEqual(self.read(PR129.read_text()), 'PASS+NOTES')


class VerdictCommand(unittest.TestCase):
    def run_verdict(self, path, *args, **kwargs):
        return subprocess.run([sys.executable, str(SCRIPT), path, *args], capture_output=True,
                              text=True, cwd=ROOT, **kwargs)

    def test_pass_exits_zero_and_prints_the_token(self):
        with tempfile.TemporaryDirectory() as directory:
            answer = Path(directory) / 'answer.md'
            answer.write_text('Work done.\n\nVERDICT: PASS+NOTES\n')
            result = self.run_verdict(str(answer))
        self.assertEqual((result.returncode, result.stdout), (0, 'PASS+NOTES\n'))

    def test_fail_and_no_verdict_exit_one(self):
        with tempfile.TemporaryDirectory() as directory:
            answer = Path(directory) / 'answer.md'
            answer.write_text('VERDICT: FAIL\n')
            failed = self.run_verdict(str(answer))
            answer.write_text('I think it is fine.\n')
            silent = self.run_verdict(str(answer))
        self.assertEqual((failed.returncode, failed.stdout), (1, 'FAIL\n'))
        self.assertEqual(silent.returncode, 1)
        self.assertIn('no verdict found', silent.stderr)

    def test_stdin(self):
        result = self.run_verdict('-', input='VERDICT: PASS\n')
        self.assertEqual((result.returncode, result.stdout), (0, 'PASS\n'))




class SharedByEveryVerifier(unittest.TestCase):
    def test_every_verifier_reads_its_verdict_through_the_shared_parser(self):
        workflows = ROOT / '.github/workflows'
        self.assertIn('python3 scripts/verdict.py evidence/verdict.json',
                      (workflows / 'advisor-checks.yml').read_text())
        sources = (workflows / 'pstack-sources.yml').read_text()
        self.assertIn('from verdict import find_verdict', sources)
        self.assertIn('python3 scripts/verdict.py verdict.value', sources)
        self.assertIn('from verdict import PASSING, find_verdict',
                      (ROOT / 'scripts/column-verifier.py').read_text())
        self.assertIn('sys.path.insert(0, str(Path(__file__).resolve().parents[1]))',
                      (ROOT / 'scripts/verification/advisor.py').read_text())


if __name__ == '__main__':
    unittest.main()
