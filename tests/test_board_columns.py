from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ('valentin-mode', 'do')


def text(skill):
    return (ROOT / 'skills' / skill / 'SKILL.md').read_text()


class BoardInstructionsTests(unittest.TestCase):
    def test_every_entrypoint_teaches_the_same_transitions(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                for instruction in ('PR opened -> Checks', 'checks green -> Verifier',
                                    'merged -> Verifier pending live proof',
                                    'current-head PASS, merged, and live proof -> Done',
                                    'Building accepts Doing', 'Verifier accepts AI Review'):
                    self.assertIn(instruction, text(skill))
                self.assertIn('Never rename the columns during caller migration.', text(skill))

    def test_pr_stage_outranks_a_live_worker(self):
        for skill in SKILLS:
            body = text(skill)
            with self.subTest(skill=skill):
                self.assertIn('Earlier lines win: an open PR outranks a live worker.', body)
                self.assertLess(body.index('- PR opened -> Checks.'),
                                body.index('- Starting work -> Building.'))

    def test_board_scope_and_aliases_stay_stated(self):
        for skill in SKILLS:
            body = text(skill)
            with self.subTest(skill=skill):
                for rule in ('Other boards retain their own column names.',
                             'Prefer the new name when both exist.',
                             'Read actual columns before choosing a move.'):
                    self.assertIn(rule, body)


if __name__ == '__main__':
    unittest.main()
