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


def reason_template(node):
    """One f-string reason as its TEMPLATE text, with each filled-in part as `{}`."""
    return ''.join('{}' if isinstance(part, ast.FormattedValue) else part.value
                   for part in node.values)


def mubo_board():
    stage_column, column_stage = r.dynamic_stage_maps(MUBO_COLUMNS, r.stage_names(sections=MUBO_COLUMNS))
    managed = MUBO_COLUMNS & r.MANAGED
    return r.make_board(13734, 'MUBO', managed, MUBO_COLUMNS - managed,
                        stage_column, column_stage, columns=MUBO_COLUMNS)


def pull(state='OPEN', checks='green', passed=False, merged_at=None, activity=None,
         created=None, number=1):
    return r.Pull(f'https://github.com/valentinyeo/vstack/pull/{number}', state, checks, passed,
                  merged_at, None, activity, created)


def merged(number, title, body='', commit='a' * 40, repo='valentinyeo/multiprompt'):
    """One merged PR row, the shape the search and the open sweep both return."""
    return {'url': f'https://github.com/{repo}/pull/{number}', 'number': number,
            'title': title, 'body': body, 'state': 'MERGED',
            'mergeCommit': {'oid': commit}, 'repository': {'nameWithOwner': repo}}


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
        """The red cards in Checks: idle past the hour and no live worker."""
        red = (pull(checks='red', activity=1000.0),)
        self.assertEqual(self.target('Checks', pulls=red, pr_idle=True),
                         ('Todo', 'red PR idle 1h; owner must fix or close'))
        # Moved back once, it plans nowhere while the PR is still idle, so no bounce.
        self.assertEqual(self.target('Todo', pulls=red, pr_idle=True),
                         ('Todo', 'red PR idle 1h; owner must fix or close'))
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

    def test_board_15_follows_default_stage_rules_including_qa(self):
        board = r.BOARDS[15]
        merged_at = r.stamp('2026-11-24T21:02:00Z')
        merged_pass = r.Pull('https://github.com/hypertask-ai/hypertask/pull/3835',
                             'MERGED', 'green', True, merged_at)
        merged_no_pass = r.Pull('https://github.com/hypertask-ai/hypertask/pull/3836',
                                'MERGED', 'green', False, merged_at)
        # VSTA-267: board 15 has no Done column, so a finished card lands in No Flag.
        self.assertEqual(r.target(r.Facts('QA', 8000, False, (merged_pass,)), board=board),
                         ('No Flag', 'merged with PASS'))
        self.assertEqual(r.target(r.Facts('QA', 8000, False, (merged_no_pass,)), board=board),
                         ('Backlog', 'merged without PASS: rule break; owner must verify'))
        self.assertEqual(r.target(r.Facts('In Progress', 8000, False, (merged_pass,)), board=board),
                         ('No Flag', 'merged with PASS'))
        for column in ('Flag: Only Me + QA', 'Flag: Everyone', 'Flag: Off', 'No Flag',
                       'Valentin Review', 'Done'):
            with self.subTest(column=column):
                self.assertEqual(r.target(r.Facts(column, 8000, False, (merged_pass,)), board=board),
                                 (column, 'protected column'))

    def test_the_idle_window_is_one_hour(self):
        # VSTA-208: the audit runs every hour, so an owner with nothing new by the
        # first tick is stuck (pstack autopilot-full step 6).
        self.assertEqual(r.RED_PR_IDLE_SECONDS, 3600)


class HourlyStuckWindow(unittest.TestCase):
    """VSTA-208: pstack autopilot-full step 6 replaces a stuck agent at once.

    The root audits every hour, so a red PR an owner has not touched for the hour is
    stuck: the card goes back to Todo on the first tick past it, stays while it is
    still idle, and never moves while a live worker holds it.
    """

    NOW = 100000.0

    def setUp(self):
        self.board = mubo_board()

    def target(self, column, pulls, alive=False):
        facts = r.Facts(column, 8000, alive, pulls, pr_idle=r.pr_idle(pulls, self.NOW))
        return r.target(facts, board=self.board)

    def test_a_red_pr_idle_61_minutes_with_no_live_worker_goes_to_todo(self):
        red = (pull(checks='red', activity=self.NOW - 61 * 60),)
        self.assertEqual(self.target('Checks', red),
                         ('Todo', 'red PR idle 1h; owner must fix or close'))

    def test_a_red_pr_idle_59_minutes_stays_in_checks(self):
        red = (pull(checks='red', activity=self.NOW - 59 * 60),)
        self.assertEqual(self.target('Checks', red),
                         ('Checks', 'open PR checks running, red, or missing'))

    def test_a_live_worker_keeps_an_idle_red_pr_in_checks(self):
        red = (pull(checks='red', activity=self.NOW - 61 * 60),)
        self.assertEqual(self.target('Checks', red, alive=True),
                         ('Checks', 'open PR checks running, red, or missing'))


class BlockedByWorkInFlight(unittest.TestCase):
    """VSTA-208: a card BlockedBy work in flight is waiting, not idle.

    The real shape on board 13734: MUBO-221 and MUBO-258 sit in Checks on a red PR,
    BlockedBy MUBO-267, whose own PR carries a live worker. Their red PR is not a
    stuck owner, so they keep their column instead of going back to Todo.
    """

    NOW = 100000.0

    def setUp(self):
        self.board = mubo_board()
        self.red = (pull(checks='red', activity=self.NOW - 61 * 60),)

    def target(self, **extra):
        facts = r.Facts('Checks', 8000, False, self.red,
                        pr_idle=r.pr_idle(self.red, self.NOW), **extra)
        return r.target(facts, board=self.board)

    def test_an_idle_red_pr_blocked_by_a_live_card_keeps_its_column(self):
        self.assertEqual(self.target(blocked=True, blocker='MUBO-267 (live worker)'),
                         ('Checks', 'blocked by MUBO-267 (live worker); kept'))

    def test_an_idle_red_pr_blocked_by_an_open_pr_keeps_its_column(self):
        self.assertEqual(self.target(blocked=True, blocker='MUBO-267 (open PR)'),
                         ('Checks', 'blocked by MUBO-267 (open PR); kept'))

    def test_the_blocker_is_named_in_the_reason_and_never_generic(self):
        column, reason = self.target(blocked=True, blocker='MUBO-300 (open PR)')
        self.assertIn('MUBO-300', reason)
        self.assertNotEqual(reason, 'waiting or blocked; kept')

    def test_a_card_with_no_live_blocker_follows_the_idle_rule(self):
        # Blocked by a card that is Done or idle: nothing is in flight, so the red PR
        # is a stuck owner like any other.
        self.assertEqual(self.target(blocked=False),
                         ('Todo', 'red PR idle 1h; owner must fix or close'))


class NewestPullWins(unittest.TestCase):
    """VSTA-205: the newest PR linked to a card decides its stage, not its merge.

    The real shape on board 13734: MUBO-289's PR #574 merged with a PASS, was
    reverted, and a redo PR #584 was opened after it. The merge that was taken back
    ships nothing, so the card follows the redo and never reads Done.
    """

    def setUp(self):
        self.board = mubo_board()
        self.merge = pull('MERGED', passed=True, created=1000.0, number=574)

    def target(self, column, pulls, **extra):
        return r.target(r.Facts(column, 8000, False, pulls, **extra), board=self.board)

    def test_a_redo_opened_after_the_merged_pass_keeps_the_card_off_done(self):
        redo = pull('OPEN', checks='red', created=2000.0, number=584)
        column, reason = self.target('Doing', (self.merge, redo))
        self.assertEqual(column, 'Checks')
        self.assertIn('/pull/584', reason)
        green = pull('OPEN', created=2000.0, number=584)
        column, reason = self.target('Doing', (self.merge, green))
        self.assertEqual(column, 'AI Review')
        self.assertIn('/pull/584', reason)

    def test_a_single_merged_pass_is_still_done(self):
        self.assertEqual(self.target('AI Review', (self.merge,)), ('Done', 'merged with PASS'))

    def test_a_redo_with_no_opening_date_keeps_the_old_reading(self):
        """An unknown date is never newer, so the open PR reads as every open PR did."""
        redo = pull('OPEN', checks='red', number=584)
        self.assertEqual(self.target('Doing', (self.merge, redo))[0], 'Checks')

    def test_a_merged_revert_by_title_takes_the_merged_pass_back(self):
        revert = merged(588, 'Revert "MUBO-289: redo the browser switch"', commit='b' * 40)
        left = r.undone({'MUBO-289': [merged(574, 'MUBO-289: redo the browser switch')]}, [revert])
        self.assertEqual(left['MUBO-289'], [])
        self.assertNotEqual(self.target('Doing', ())[0], 'Done')

    def test_a_reverts_line_takes_the_merged_pass_back(self):
        ship = merged(574, 'Redo the browser switch')
        revert = merged(588, 'Back out the browser switch',
                        body='Reverts valentinyeo/multiprompt#574')
        left = r.undone({'MUBO-289': [ship]}, [revert])
        self.assertEqual(left['MUBO-289'], [])
        self.assertNotEqual(self.target('Doing', ())[0], 'Done')

    def test_the_search_and_the_read_ask_for_the_opening_date(self):
        for fields in (r.SEARCH_FIELDS, r.PULL_FIELDS, r.OPEN_PULL_FIELDS):
            self.assertIn('createdAt', fields)

    def test_a_saved_pass_without_an_opening_date_is_read_again(self):
        entry = {'pulls': [], 'facts': {'o/r#1': {'state': 'MERGED', 'passed': True,
                                                  'merged_at': 1.0}}}
        saved = {'at': 1, 'tickets': {'MUBO-1': entry}}
        self.assertFalse(r.saved_facts_usable(saved))
        entry['facts']['o/r#1']['created_at'] = 1.0
        self.assertTrue(r.saved_facts_usable(saved))


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
                    'plan_stage', 'target', '_open_pr_reason', '_worker_reason',
                    'newer_open_reason'}:
                prose.add(ast.get_docstring(node))
                filled = set()
                for sub in ast.walk(node):
                    # A reason that names its PR is an f-string: read it as the
                    # template its row carries, not as the pieces around the value.
                    if isinstance(sub, ast.JoinedStr):
                        found.add(reason_template(sub))
                        filled |= {id(part) for part in sub.values}
                found |= {sub.value for sub in ast.walk(node)
                          if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                          and ' ' in sub.value and id(sub) not in filled}
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
