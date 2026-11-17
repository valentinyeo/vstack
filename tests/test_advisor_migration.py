"""Public checks must run without the private advisor checkout."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ('book-check', 'said-started', 'pstack-source', 'pstack-reply',
         'out-of-bounds', 'billing-quiet')


class PublicAdvisorChecks(unittest.TestCase):
    def test_public_checkout_contains_all_hooks(self):
        for hook in HOOKS:
            with self.subTest(hook=hook):
                self.assertTrue((ROOT / 'hooks' / f'{hook}.py').is_file())

    def test_book_check_rejects_incomplete_pr(self):
        hook = ROOT / 'hooks/book-check.py'
        self.assertTrue(hook.is_file(), 'public book-check is missing')
        run = subprocess.run(['python3', str(hook)], input=json.dumps({
            'tool_name': 'Bash', 'tool_input': {'command': 'gh pr create --body incomplete'}
        }), text=True, capture_output=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn('Check seen failing', run.stderr)
        self.assertNotIn('poteto-2-advisor', run.stderr)

    def test_checks_route_to_public_repo(self):
        text = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
        self.assertNotIn('A check for either goes in the private home repo', text)
        self.assertIn('A check for either goes in vstack', text)

    def test_book_and_rule_table_resolve(self):
        self.assertTrue((ROOT / 'book/CHECKLIST.md').is_file())
        rules = ROOT / 'CLAUDE.md'
        self.assertTrue(rules.is_file(), 'public rules table is missing')
        for hook in HOOKS:
            self.assertIn(f'hooks/{hook}.py', rules.read_text())


if __name__ == '__main__':
    unittest.main()
