"""The board stage model follows pstack 1:1, and every stage says where it comes from.

VSTA-186: board columns had grown a post-merge "live proof pending" stage pstack does
not have, and no rule stopped the next invented stage. The tests here pin the pstack
model itself (merged with PASS is Done, an idle red PR goes back to Todo) on the MUBO
shapes measured on board 13734, and fail when a stage or plan reason has no pstack
quote and no house.txt id.
"""
import ast
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'skills/hypertask-work/reconcile'
HOUSE = ROOT / 'skills/pstack-diff/house.txt'

# The columns board 13734 shows: a runtime board, so the reconcile maps them itself.
MUBO_COLUMNS = frozenset({'Todo', 'Doing', 'Checks', 'AI Review', 'Verification Backlog',
                          'Valentin Review', 'Done', 'Not now'})


def load_reconcile():
    loader = importlib.machinery.SourceFileLoader('fleet_reconcile', str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


r = load_reconcile()


def mubo_board():
    stage_column, column_stage = r.dynamic_stage_maps(MUBO_COLUMNS, r.stage_names(sections=MUBO_COLUMNS))
    managed = MUBO_COLUMNS & r.MANAGED
    return r.make_board(13734, 'MUBO', managed, MUBO_COLUMNS - managed,
                        stage_column, column_stage, columns=MUBO_COLUMNS)


def pull(state='OPEN', checks='green', passed=False, merged_at=None, activity=None):
    return r.Pull('https://github.com/valentinyeo/vstack/pull/1', state, checks, passed,
                  merged_at, None, activity)


class MuboShapes(unittest.TestCase):
    """The card shapes measured on board 13734, planned onto the pstack model."""

    def setUp(self):
        self.board = mubo_board()

    def target(self, column, age=8000, alive=False, pulls=(), pr_idle=False, **extra):
        return r.target(r.Facts(column, age, alive, pulls, pr_idle=pr_idle, **extra),
                        board=self.board)

    def test_a_merged_pr_with_pass_is_done(self):
        """The 48 cards AI Review held as "merged with PASS; live proof pending"."""
        self.assertEqual(self.target('AI Review', pulls=(pull('MERGED', passed=True),)),
                         ('Done', 'merged with PASS'))
        self.assertEqual(self.target('Checks', pulls=(pull('MERGED', passed=True),)),
                         ('Done', 'merged with PASS'))

    def test_a_merged_pr_without_pass_goes_back_to_todo(self):
        """The 14 cards AI Review held as "merged missing PASS" are a rule break."""
        self.assertEqual(self.target('AI Review', pulls=(pull('MERGED'),)),
                         ('Todo', 'merged without PASS: rule break; owner must verify'))

    def test_an_idle_red_pr_goes_back_to_todo_and_stays(self):
        """The 68 red cards in Checks: idle over 24h and no live worker."""
        red = (pull(checks='red', activity=1000.0),)
        self.assertEqual(self.target('Checks', pulls=red, pr_idle=True),
                         ('Todo', 'red PR idle 24h; owner must fix or close'))
        # Moved back once, it plans nowhere while the PR is still idle, so no bounce.
        self.assertEqual(self.target('Todo', pulls=red, pr_idle=True),
                         ('Todo', 'red PR idle 24h; owner must fix or close'))
        # The PR moves: the card follows it again.
        self.assertEqual(self.target('Todo', pulls=(pull(checks='red'),), pr_idle=False)[0],
                         'Checks')

    def test_a_live_worker_keeps_a_red_pr_in_checks(self):
        red = (pull(checks='red', activity=1000.0),)
        self.assertEqual(self.target('Checks', alive=True, pulls=red, pr_idle=True)[0], 'Checks')

    def test_an_open_green_pr_waits_in_ai_review(self):
        """The 9 open green PRs in AI Review stay there for a verifier or a merge."""
        self.assertEqual(self.target('AI Review', pulls=(pull(),)),
                         ('AI Review', 'open PR checks green; verifier or merge pending'))
        self.assertEqual(self.target('Todo', pulls=(pull(),))[0], 'AI Review')

    def test_board_15_keeps_its_own_live_proof_stage(self):
        board = r.BOARDS[15]
        self.assertEqual(r.target(r.Facts('In Progress', 8000, False, (pull('MERGED', passed=True),)),
                                  board=board),
                         ('AI Review', 'merged PR; live proof pending'))

    def test_the_idle_window_is_one_named_constant(self):
        self.assertEqual(r.RED_PR_IDLE_SECONDS, 24 * 3600)


class PullActivity(unittest.TestCase):
    def test_the_newest_push_check_or_comment_is_the_activity(self):
        node = {'updatedAt': '2026-01-03T00:00:00Z',
                'commits': {'nodes': [{'commit': {'committedDate': '2026-01-02T00:00:00Z'}}]},
                'statusCheckRollup': {'contexts': {'nodes': [
                    {'__typename': 'CheckRun', 'completedAt': '2026-01-01T00:00:00Z'},
                    {'__typename': 'StatusContext', 'state': 'SUCCESS'}]}}}
        self.assertEqual(r.pull_activity(node), r.stamp('2026-01-03T00:00:00Z'))
        node['updatedAt'] = None
        self.assertEqual(r.pull_activity(node), r.stamp('2026-01-02T00:00:00Z'))
        node['commits'] = {'nodes': []}
        self.assertEqual(r.pull_activity(node), r.stamp('2026-01-01T00:00:00Z'))

    def test_a_read_without_a_time_is_never_an_idle_pr(self):
        self.assertIsNone(r.pull_activity({}))
        self.assertFalse(r.pr_idle((pull(checks='red'),), 10 * 24 * 3600))
        self.assertTrue(r.pr_idle((pull(checks='red', activity=0.0),), 2 * 24 * 3600))

    def test_a_saved_fact_without_activity_is_read_again(self):
        entry = {'pulls': [], 'facts': {'o/r#1': {'state': 'OPEN', 'checks': 'red'}}}
        self.assertFalse(r.saved_facts_usable({'at': 1, 'tickets': {'MUBO-1': entry}}))
        entry['facts']['o/r#1']['activity'] = 1.0
        self.assertTrue(r.saved_facts_usable({'at': 1, 'tickets': {'MUBO-1': entry}}))


class EveryStageHasASource(unittest.TestCase):
    """The lint that stops the next drift: a stage or reason must say where it came from."""

    def setUp(self):
        self.rows = r.PLAN_SOURCES
        try:
            from test_house_list import PSTACK_DIFF, resolve_pstack_root
        except ImportError:  # `python3 -m unittest tests.test_board_stages`
            from tests.test_house_list import PSTACK_DIFF, resolve_pstack_root
        self.pstack_root = resolve_pstack_root()
        self.house_ids = {row.get('id') for row in
                          PSTACK_DIFF.parse_house_stanzas(HOUSE.read_text())}
        self.reasons = {row['reason'] for row in self.rows}

    def test_every_stage_in_the_model_has_a_row(self):
        self.assertEqual({stage for stage in r.Stage if stage not in r.PLAN_STAGES}, set(),
                         'a Stage has no pstack citation and no house id')

    def test_every_reason_plan_stage_can_say_has_a_row(self):
        found, prose = set(), set()
        for node in ast.parse(SOURCE.read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name in {
                    'plan_stage', 'target', '_open_pr_reason', '_worker_reason'}:
                prose.add(ast.get_docstring(node))
                found |= {sub.value for sub in ast.walk(node)
                          if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                          and ' ' in sub.value}
        self.assertEqual(found - prose - self.reasons, set(),
                         'a plan reason has no pstack citation and no house id')
        self.assertIn(r.NOTHING_RAN, self.reasons)

    def test_each_row_cites_a_verbatim_pstack_line_or_a_real_house_id(self):
        for row in self.rows:
            with self.subTest(reason=row['reason']):
                has_pstack = 'pstack' in row or 'quote' in row
                has_house = 'house' in row
                self.assertTrue(has_pstack != has_house,
                                'exactly one of a pstack quote or a house id')
                if has_house:
                    self.assertIn(row['house'], self.house_ids)
                    continue
                target = self.pstack_root / row['pstack']
                self.assertTrue(target.is_file(), f"pstack file missing: {row['pstack']}")
                self.assertIn(row['quote'], target.read_text(encoding='utf-8', errors='replace'))


if __name__ == '__main__':
    unittest.main()
