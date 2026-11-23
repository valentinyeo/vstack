"""A verifier pass cannot stand while changed product files went unexercised.

The real mistake is multiprompt pull request 1205: the verifier posted
`pstack-verifier: PASS+NOTES @ 644279e` while its own selection listed
src/mp_sessions.py, src/mp_send.py and src/mp_helper.py as unmapped. The change merged and
broke about 20 chats on restart. tests/fixtures/uncovered/ holds the run's own artifacts.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / 'scripts/uncovered_gate.py'
VERDICT = ROOT / 'scripts/verdict.py'
FIXTURES = Path(__file__).resolve().parent / 'fixtures/uncovered'
REAL = FIXTURES / 'pr-1205'
COVERED = FIXTURES / 'covered'
PRODUCT = ['src/mp_helper.py', 'src/mp_send.py', 'src/mp_sessions.py']


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    sys.modules[loader.name] = module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def gate():
    """The shared gate, loaded on use, so a missing module reads as the failure it is."""
    return load('shared_uncovered_gate', GATE)


def selection(folder):
    return json.loads((folder / 'selection.json').read_text())


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=cwd)


class ProductFiles(unittest.TestCase):
    def setUp(self):
        self.gate = gate()

    def test_real_selection_names_only_the_three_product_files(self):
        self.assertEqual(self.gate.product_files(selection(REAL)), PRODUCT)

    def test_docs_changelog_ticket_titles_and_tests_are_not_product(self):
        paths = ['README.md', 'docs/thing.html', 'changelog.d/x.md', 'tools/ticket-titles/IGSH-1.txt',
                 'tests/test_x.py', 'src/test_mp.py', 'src/mp_sessions.test.js', '.github/workflows/ci.yml']
        for path in paths:
            with self.subTest(path=path):
                self.assertIsNotNone(self.gate.not_product(path), f'{path} must not count as product code')

    def test_prose_only_selection_still_names_the_files(self):
        prose = {'uncovered': 'Unmapped files: src/a.py, changelog.d/b.md'}
        self.assertEqual(self.gate.product_files(prose), ['src/a.py'])


class Gate(unittest.TestCase):
    def setUp(self):
        self.gate = gate()

    def test_real_pass_with_uncovered_product_files_fails(self):
        standing, why = self.gate.gate(selection(REAL), 'PASS+NOTES')
        self.assertEqual(standing, 'FAIL')
        for path in PRODUCT:
            self.assertIn(path, why)
        self.assertNotIn('changelog.d', why)
        self.assertIn('Add or select a journey that exercises them', why)

    def test_real_pass_also_fails(self):
        self.assertEqual(self.gate.gate(selection(REAL), 'PASS')[0], 'FAIL')

    def test_covered_selection_keeps_the_pass(self):
        self.assertEqual(self.gate.gate(selection(COVERED), 'PASS'), ('PASS', ''))
        self.assertEqual(self.gate.gate(selection(COVERED), 'PASS+NOTES'), ('PASS+NOTES', ''))

    def test_fail_and_blocked_stand(self):
        for token in ('FAIL', 'BLOCKED'):
            self.assertEqual(self.gate.gate(selection(REAL), token), (token, ''))

    def test_empty_selection_keeps_the_pass(self):
        self.assertEqual(self.gate.gate({}, 'PASS'), ('PASS', ''))


class CommandLine(unittest.TestCase):
    def test_real_selection_demotes_and_names_the_fix(self):
        result = run(str(GATE), '--selection', str(REAL / 'selection.json'), '--verdict', 'PASS+NOTES')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'FAIL')
        self.assertIn('src/mp_sessions.py', result.stderr)

    def test_covered_selection_exits_zero(self):
        result = run(str(GATE), '--selection', str(COVERED / 'selection.json'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'PASS')

    def test_list_names_the_uncovered_product_files(self):
        result = run(str(GATE), '--selection', str(REAL / 'selection.json'), '--list')
        self.assertEqual(result.stdout.split(), PRODUCT)


class SharedVerdictReader(unittest.TestCase):
    """scripts/verdict.py is the one place a vstack verifier's pass is read."""

    def test_real_answer_beside_its_selection_demotes(self):
        result = run(str(VERDICT), str(REAL / 'answer.md'))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'FAIL')
        self.assertIn('src/mp_sessions.py', result.stderr)

    def test_real_answer_without_a_selection_still_reads_pass(self):
        # No selection means no changed-file plan to miss. The gate only judges what it can see.
        with tempfile.TemporaryDirectory() as folder:
            answer = Path(folder, 'answer.md')
            answer.write_text((REAL / 'answer.md').read_text())
            result = run(str(VERDICT), str(answer))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'PASS+NOTES')

    def test_covered_answer_stands(self):
        result = run(str(VERDICT), str(COVERED / 'answer.md'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'PASS')

    def test_selection_flag_beats_the_beside_the_answer_default(self):
        with tempfile.TemporaryDirectory() as folder:
            answer = Path(folder, 'answer.md')
            answer.write_text((COVERED / 'answer.md').read_text())
            result = run(str(VERDICT), str(answer), '--selection', str(REAL / 'selection.json'))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'FAIL')


if __name__ == '__main__':
    unittest.main()
