from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PstackSources(unittest.TestCase):
    def test_verifier_prompt_uses_the_scoped_stage_contract(self):
        text = (ROOT / '.github/workflows/pstack-sources.yml').read_text()
        self.assertIn('Board 2060 merged work with a pre-merge PASS is Done.', text)
        self.assertIn('Only board 15 retains the scoped post-merge proof exception.', text)
        self.assertNotIn('Board 2060 merged work awaits live proof.', text)

    def test_skills_do_not_route_to_removed_playbook(self):
        for path in sorted((ROOT / 'skills').rglob('SKILL.md')):
            with self.subTest(skill=str(path.relative_to(ROOT))):
                self.assertIsNone(re.search(r'\borchestrate\b', path.read_text(), re.I),
                                  f'{path}: use autonomous-run and figure-it-out')


if __name__ == '__main__':
    unittest.main()
