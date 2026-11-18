import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXED_TICKET = re.compile(r'\b[A-Z]{2,6}-\d+\b')
BODY = 'Why: fixture.\nTicket: https://example.test/detail/project-1/9999\nDone when: fixture.\n'
TITLE = 'fix(x): SOFT-9999 fixture change'


def load_advisor():
    spec = importlib.util.spec_from_file_location('advisor_under_test', ROOT / 'scripts/verification/advisor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifierPrompts(unittest.TestCase):
    def test_advisor_prompt_names_only_the_prs_own_ticket(self):
        prompt = load_advisor().build_prompt(TITLE, BODY, 'a' * 40, 'main', '/p/pstack/0.0.1', 'Fixture rules.')
        self.assertEqual(sorted(set(FIXED_TICKET.findall(prompt))), ['SOFT-9999'])
        self.assertIn('https://example.test/detail/project-1/9999', prompt)

    def test_advisor_prompt_with_no_body_names_no_ticket(self):
        prompt = load_advisor().build_prompt('', '', 'a' * 40, 'main', '/p/pstack/0.0.1', 'Fixture rules.')
        self.assertEqual(FIXED_TICKET.findall(prompt), [])

    def test_column_verifier_brief_names_only_the_prs_own_ticket(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@users.noreply.github.com')
            (root / 'tracked').write_text('x')
            git('add', 'tracked')
            git('commit', '-qm', 'fixture')
            sha = git('rev-parse', 'HEAD')
            git('update-ref', 'refs/remotes/origin/main', sha)
            fake_bin = root / 'bin'
            fake_bin.mkdir()
            npx = fake_bin / 'npx'
            npx.write_text('#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\nPath("brief.txt").write_text(sys.argv[-1])\n')
            npx.chmod(0o755)
            gh = fake_bin / 'gh'
            gh.write_text('#!/bin/sh\nexit 0\n')
            gh.chmod(0o755)
            env = dict(os.environ, PATH=str(fake_bin) + ':' + os.environ['PATH'], HEAD_SHA=sha,
                       VERIFIER_MODEL='glm-5.3-flash', BASE_REF='main', RUNNER_TEMP=str(root),
                       OPENCODE_API_KEY='fixture-key', PR_NUMBER='1', GITHUB_REPOSITORY='fixture/repo',
                       GITHUB_RUN_ID='1', PR_TITLE=TITLE, PR_BODY=BODY)
            env.pop('VERIFY_COMMANDS', None)
            subprocess.run(['/usr/bin/python3', str(ROOT / 'scripts/column-verifier.py')], cwd=root, env=env,
                           capture_output=True, text=True)
            brief = (root / 'brief.txt').read_text()
        self.assertEqual(sorted(set(FIXED_TICKET.findall(brief))), ['SOFT-9999'])

    def test_workflows_hold_no_fixed_ticket_outside_names(self):
        for name in ('advisor-checks.yml', 'soft-2446-verifier.yml'):
            for number, line in enumerate((ROOT / '.github/workflows' / name).read_text().splitlines(), 1):
                if line.lstrip().startswith('name:'):
                    continue
                with self.subTest(file=name, line=number):
                    self.assertEqual(FIXED_TICKET.findall(line), [], line)


if __name__ == '__main__':
    unittest.main()
