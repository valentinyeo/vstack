import pathlib
import re
import unittest

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / '.github/workflows/skill-lint.yml'


class SkillLintPin(unittest.TestCase):
    def test_the_lint_source_is_pinned_to_a_full_commit(self):
        # A stale lint source ran PR 134 with the wrong helpers (SOFT-2802).
        refs = re.findall(r'repository:\s*valentinyeo/house-rules\s*\n\s*ref:\s*(\S+)', WORKFLOW.read_text())
        self.assertEqual(len(refs), 1)
        self.assertRegex(refs[0], r'^[0-9a-f]{40}$')

    def test_the_workflow_runs_the_shared_lint_script_and_no_ai_step(self):
        text = WORKFLOW.read_text()
        self.assertIn('python3 ../lint-source/scripts/skill-lint', text)
        self.assertIn('--base "$BASE"', text)
        self.assertIn('fetch-depth: 0', text)
        for tell in ('pi --', 'pick-verifier-model', 'run-verifier', 'gh pr comment', 'verdict'):
            self.assertNotIn(tell, text)


if __name__ == '__main__':
    unittest.main()
