from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def text(skill):
    return (ROOT / 'skills' / skill / 'SKILL.md').read_text()


class BoardInstructionsTests(unittest.TestCase):
    def test_hypertask_work_teaches_the_transitions(self):
        body = text('hypertask-work')
        for instruction in ('worker starts -> Doing or Building', 'PR opened -> Checks',
                            'checks green -> AI Review or Verifier',
                            'merged -> AI Review or Verifier, live proof pending',
                            'live proof -> Done'):
            self.assertIn(instruction, body)

    def test_pr_stage_outranks_a_live_worker(self):
        body = text('hypertask-work')
        self.assertIn('pr outranks a live worker', body.lower())
        self.assertIn('- PR opened -> Checks', body)

    def test_valentin_mode_points_at_the_skill(self):
        body = text('valentin-mode')
        self.assertGreaterEqual(body.count('hypertask-work'), 2,
                                'valentin-mode must name the hypertask-work skill twice')
        self.assertIn('hypertask feedback', body)
        self.assertIn('/board-identity', body)
        reconcile = [line for line in body.splitlines()
                     if 'reconcile' in line and '--label' in line]
        self.assertTrue(reconcile, 'valentin-mode must show a reconcile call with --label')
        self.assertNotIn('Board sync for orchestrators', body)
        self.assertNotIn('/house-rules', body)

    def test_hypertask_work_names_the_real_columns(self):
        body = text('hypertask-work')
        for column in ('Todo', 'Doing', 'Building', 'Checks', 'AI Review', 'Verifier',
                       'Valentin Review', 'Done'):
            self.assertIn(column, body)
        pending = 'merged -> AI Review or Verifier, live proof pending'
        proof = 'live proof -> Done'
        self.assertLess(body.index(pending), body.index(proof))
        self.assertIn('Never move a ticket into Valentin Review.', body)
        self.assertIn('Reconcile never touches Valentin Review and never moves work to Done.', body)

    def test_board_scope_and_aliases_stay_stated(self):
        body = text('hypertask-work')
        for rule in ('Other boards keep their own columns.',
                     'Use the name the board shows.',
                     'Doing or Building',
                     'AI Review or Verifier'):
            self.assertIn(rule, body)


if __name__ == '__main__':
    unittest.main()
