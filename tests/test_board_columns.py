from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def text(skill):
    return (ROOT / 'skills' / skill / 'SKILL.md').read_text()


class BoardInstructionsTests(unittest.TestCase):
    def test_do_teaches_the_same_transitions(self):
        body = text('do')
        for instruction in ('PR opened -> Checks', 'checks green -> Verifier',
                            'merged -> Verifier pending live proof',
                            'current-head PASS, merged, and live proof -> Done',
                            'Building accepts Doing', 'Verifier accepts AI Review'):
            self.assertIn(instruction, body)
        self.assertIn('Never rename the columns during caller migration.', body)

    def test_pr_stage_outranks_a_live_worker(self):
        for skill in ('valentin-mode', 'do'):
            with self.subTest(skill=skill):
                self.assertIn('open pr outranks a live worker', text(skill).lower())
        body = text('do')
        self.assertIn('Earlier lines win: an open PR outranks a live worker.', body)
        self.assertLess(body.index('- PR opened -> Checks.'),
                        body.index('- Starting work -> Building.'))

    def test_valentin_mode_points_at_the_house_rules(self):
        body = text('valentin-mode')
        self.assertIn('Board sync for orchestrators', body)
        self.assertIn('docs/fleet-reconcile.md', body)
        self.assertIn('Building accepts Doing; Verifier accepts AI Review.', body)
        self.assertIn('Other boards keep their own columns.', body)

    def test_board_scope_and_aliases_stay_stated(self):
        body = text('do')
        for rule in ('Other boards retain their own column names.',
                     'Prefer the new name when both exist.',
                     'Read actual columns before choosing a move.'):
            self.assertIn(rule, body)


if __name__ == '__main__':
    unittest.main()
