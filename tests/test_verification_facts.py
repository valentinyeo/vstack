import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


FACTS = Path(__file__).resolve().parents[1] / 'skills/verification-check/facts.sh'


class VerificationFacts(unittest.TestCase):
    def test_reports_plain_and_prefixed_verdicts_from_current_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            subprocess.run(['git', '-C', tmp, '-c', 'user.name=Test', '-c',
                            'user.email=test@example.invalid', 'commit', '--allow-empty',
                            '-qm', 'fixture'], check=True)
            prs = [
                {'number': 1, 'title': 'plain', 'comments': [
                    {'body': 'PASS+NOTES\nProof'}, {'body': 'Ordinary discussion'}]},
                {'number': 2, 'title': 'prefixed', 'comments': [
                    {'body': 'pstack-verifier: PASS @ abc'}]},
                {'number': 3, 'title': 'failed', 'comments': [
                    {'body': 'PASS\nOld proof'}, {'body': 'FAIL\nCurrent proof'}]},
                {'number': 4, 'title': 'discussion', 'comments': [
                    {'body': 'Discuss pstack-verifier: configuration'},
                    {'body': 'PASSING is not a verdict'}]},
            ]
            (root / 'prs.json').write_text(json.dumps(prs))
            gh = root / 'gh'
            gh.write_text('''#!/usr/bin/env bash
if [ "$1 $2" = "pr list" ]; then
  jq -r "${!#}" "$FIXTURE_PRS"
elif [ "$1 $2" = "repo view" ]; then
  echo PRIVATE
fi
''')
            gh.chmod(0o755)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       FIXTURE_PRS=str(root / 'prs.json'))
            for args in ([], [tmp]):
                with self.subTest(args=args):
                    result = subprocess.run(['bash', str(FACTS), *args], cwd=tmp,
                                            env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('#1 plain | PASS+NOTES', result.stdout)
                    self.assertIn('#2 prefixed | pstack-verifier: PASS', result.stdout)
                    self.assertIn('#3 failed | FAIL', result.stdout)
                    self.assertIn('#4 discussion | no verifier comment', result.stdout)
