from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def text(*parts):
    return (ROOT / 'skills' / Path(*parts)).read_text()


class BoardInstructionsTests(unittest.TestCase):
    def test_the_hypertask_skill_teaches_the_transitions(self):
        body = text('hypertask', 'references', 'board.md')
        for instruction in ('worker starts -> Doing or Building', 'PR opened -> Checks',
                            'checks green -> AI Review or Verifier',
                            'merged -> AI Review or Verifier, live proof pending',
                            'live proof -> Done'):
            self.assertIn(instruction, body)

    def test_pr_stage_outranks_a_live_worker(self):
        body = text('hypertask', 'references', 'board.md')
        self.assertIn('pr outranks a live worker', body.lower())
        self.assertIn('- PR opened -> Checks', body)

    def test_valentin_mode_points_at_the_one_skill(self):
        body = text('valentin-mode', 'SKILL.md')
        self.assertGreaterEqual(body.count('/hypertask'), 2,
                                'valentin-mode must point board work at the hypertask skill')
        self.assertIn('hypertask feedback', body)
        self.assertIn('checkup', body)
        self.assertNotIn('Board sync for orchestrators', body)
        self.assertNotIn('/house-rules', body)

    def test_the_hypertask_skill_names_the_real_columns(self):
        body = text('hypertask', 'references', 'board.md')
        for column in ('Todo', 'Doing', 'Building', 'Checks', 'AI Review', 'Verifier',
                       'Valentin Review', 'Done'):
            self.assertIn(column, body)
        pending = 'merged -> AI Review or Verifier, live proof pending'
        proof = 'live proof -> Done'
        self.assertLess(body.index(pending), body.index(proof))
        self.assertIn('Never move a ticket into Valentin Review.', body)

    def test_board_scope_and_aliases_stay_stated(self):
        body = text('hypertask', 'references', 'board.md')
        for rule in ('Other boards keep their own columns',
                     'Use the name the board shows',
                     'Doing (or Building)',
                     'AI Review (or Verifier)'):
            self.assertIn(rule, body)


if __name__ == '__main__':
    unittest.main()
