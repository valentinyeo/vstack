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


if __name__ == '__main__':
    unittest.main()
