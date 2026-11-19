import pathlib
import re
import unittest

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / '.github/workflows/skill-lint.yml'


class SkillLintPin(unittest.TestCase):
    def test_lint_ref_matches_the_pinned_workflow(self):
        # The verifier helpers come from lint-ref. A stale lint-ref ran PR 134 with no
        # fallback verifier while the workflow pin was current (SOFT-2802).
        text = WORKFLOW.read_text()
        uses = re.search(r'skill-lint\.yml@([0-9a-f]{40})', text)[1]
        ref = re.search(r'lint-ref:\s*([0-9a-f]{40})', text)[1]
        self.assertEqual(ref, uses)


if __name__ == '__main__':
    unittest.main()
