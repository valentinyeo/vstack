from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BoardInstructionsTests(unittest.TestCase):
    def test_every_entrypoint_teaches_the_same_transitions(self):
        for skill in ('valentin-mode', 'do'):
            text = (ROOT / 'skills' / skill / 'SKILL.md').read_text()
            with self.subTest(skill=skill):
                for instruction in ('PR opened -> Checks', 'checks green -> Verifier',
                                    'merged -> Verifier pending live proof',
                                    'current-head PASS, merged, and live proof -> Done',
                                    'Building accepts Doing', 'Verifier accepts AI Review'):
                    self.assertIn(instruction, text)
                self.assertIn('Never rename the columns during caller migration.', text)


if __name__ == '__main__':
    unittest.main()
