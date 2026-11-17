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

class DrainColumnTableTests(unittest.TestCase):
    def test_merged_work_has_a_pending_proof_row_before_todo(self):
        text = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
        pending = '| Merged PR, current-head PASS or live proof missing | Verifier |'
        self.assertIn(pending, text)
        self.assertLess(text.index(pending), text.index('| No live lease, open PR, or merged PR | Todo |'))
        self.assertIn('| All ticket PRs merged, current-head PASS and live proof | Done |', text)

    def test_table_scopes_and_aliases_apply_to_each_move(self):
        text = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
        table_intro = text[text.index('  4. Sync Hypertask'):text.index('     | Current facts')]
        self.assertIn('This table applies only to board 2060.', table_intro)
        self.assertIn('Other boards use their own workflow and columns.', table_intro)
        self.assertIn('Resolve Building/Doing and Verifier/AI Review against actual columns.', table_intro)
        self.assertIn('Prefer new names when both exist.', table_intro)

    def test_recent_touch_only_delays_fallback_to_todo(self):
        text = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
        rows = [line.strip().split('|')[1:3] for line in text.splitlines()
                if line.strip().startswith('| ')][2:]
        cases = [
            ('Open PR, CI green', 'Verifier'),
            ('Live worker lease', 'Building'),
            ('Open PR, CI pending or failing', 'Checks'),
            ('Merged PR, current-head PASS or live proof missing', 'Verifier'),
            ('All ticket PRs merged, current-head PASS and live proof', 'Done'),
            ('Waiting on Valentin or unresolved BlockedBy', 'Preserve, outside finish line'),
            ('Done, Valentin Review, Not now, unknown column', 'Preserve'),
            ('No live lease, open PR, or merged PR', 'Preserve'),
        ]
        for fact, expected in cases:
            with self.subTest(fact=fact):
                actual = next(column.strip() for condition, column in rows
                              if condition.strip() in (fact, 'Touched within 2h'))
                self.assertEqual(actual, expected)

    def test_pr_stages_win_over_a_live_worker(self):
        text = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
        rows = [line.strip().split('|')[1:3] for line in text.splitlines()
                if line.strip().startswith('| ')][2:]
        cases = [
            ('Open PR, CI pending or failing', 'Checks'),
            ('Open PR, CI green', 'Verifier'),
            ('Merged PR, current-head PASS or live proof missing', 'Verifier'),
            ('All ticket PRs merged, current-head PASS and live proof', 'Done'),
        ]
        for fact, expected in cases:
            with self.subTest(fact=fact):
                actual = next(column.strip() for condition, column in rows
                              if condition.strip() in (fact, 'Live worker lease'))
                self.assertEqual(actual, expected)
