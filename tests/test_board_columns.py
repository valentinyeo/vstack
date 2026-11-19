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
        for skill in ('hypertask-work', 'do'):
            with self.subTest(skill=skill):
                self.assertIn('pr outranks a live worker', text(skill).lower())
        body = text('do')
        self.assertIn('Earlier lines win: an open PR outranks a live worker.', body)
        self.assertLess(body.index('- PR opened -> Checks.'),
                        body.index('- Starting work -> Building.'))

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
        body = text('do')
        for rule in ('Other boards retain their own column names.',
                     'Prefer the new name when both exist.',
                     'Read actual columns before choosing a move.'):
            self.assertIn(rule, body)


if __name__ == '__main__':
    unittest.main()
