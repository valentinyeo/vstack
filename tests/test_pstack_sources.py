"""Keep installed skills on the current pstack workflow."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PstackSources(unittest.TestCase):
    def test_skills_do_not_route_to_removed_playbook(self):
        for path in sorted((ROOT / 'skills').rglob('SKILL.md')):
            with self.subTest(skill=str(path.relative_to(ROOT))):
                self.assertIsNone(re.search(r'\borchestrate\b', path.read_text(), re.I),
                                  f'{path}: use autonomous-run and figure-it-out')

    def test_responsive_mode_names_current_workflow(self):
        text = (ROOT / 'skills/responsive-mode/SKILL.md').read_text()
        self.assertIn('autonomous-run', text)
        self.assertIn('figure-it-out', text)


if __name__ == '__main__':
    unittest.main()
