"""Exhaustive reconcile stage model: one evidence order, no flip-flop."""
import importlib.machinery
import importlib.util
import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_reconcile():
    loader = importlib.machinery.SourceFileLoader('fleet_reconcile', str(ROOT / 'skills/hypertask-work/reconcile'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


r = load_reconcile()


def pull(state='OPEN', checks='green', passed=False, merged_at=None):
    return r.Pull('https://github.com/example/x/pull/1', state, checks, passed, merged_at)


# These cards entered their column at ENTRY. A merge at NEWER came after that, a
# merge at OLDER is history. LATER is the card's entry time after a move this run.
ENTRY = 1_000_000.0
NEWER = ENTRY + 60
OLDER = ENTRY - 86400
LATER = NEWER + 3600


PR_STATES = (
    (),
    (pull(checks='red'),),
    (pull(),),
    (pull('MERGED', passed=True, merged_at=NEWER),),
    (pull('MERGED', merged_at=NEWER),),
    (pull('MERGED', passed=True, merged_at=OLDER),),
    (pull('MERGED', merged_at=OLDER),),
    (pull('MERGED', passed=True),),
    (pull('MERGED'),),
)
STALE_MERGE = 'merged PR older than column entry; kept'


def board_names(board):
    return {} if r.product_board(board) else r.stage_names(sections=board.managed | board.protected)


def target_stage(board, facts):
    col, _ = r.target(facts, board, board_names(board))
    if col in board.protected or col.startswith('Flag:'):
        return r.Stage.PROTECTED
    stage = r.column_stage_map(board).get(col)
    return stage if stage is not None else r.Stage.UNMANAGED


class VerifyReconcileModel(unittest.TestCase):
    def test_exhaustive_model(self):
        count = 0
        stages_by_board = {}
        for board_id in (15, 2060, 13556):
            board = r.board_config(board_id)
            names = board_names(board)
            backlog = r.stage_column_map(board)[r.Stage.BACKLOG]
            work = r.resolve_column(r.Stage.IN_PROGRESS, board, names)
            for column in sorted(board.managed):
                for age, alive, pulls, waiting, blocked, verification in itertools.product(
                        (100.0, 8000.0), (False, True), PR_STATES, (False, True), (False, True), (False, True)):
                    facts = r.Facts(column, age, alive, pulls, waiting, blocked, verification, ENTRY)
                    count += 1
                    here = r.column_stage_of(board, column)
                    col, _ = r.target(facts, board, names)
                    if here in (r.Stage.PROTECTED, r.Stage.UNMANAGED):
                        continue
                    if col == column:
                        continue
                    if here == r.Stage.VERIFICATION and not verification:
                        continue
                    vb = r.stage_column_map(board).get(r.Stage.VERIFICATION)
                    if vb and verification and col == backlog:
                        continue
                    if col == vb and not verification:
                        continue
                    # The card now sits in col, so that column's entry time is later
                    # than any merge that put it there. A second plan must keep it,
                    # inside the grace window and after it.
                    for age_now in (0, r.GRACE_SECONDS + 1):
                        again = r.Facts(col, age_now, alive, pulls, waiting, blocked,
                                        verification, LATER)
                        planned = r.target(again, board, names)[0]
                        if not alive:
                            self.assertEqual(planned, col,
                                             f'board {board_id} flip {column}->{col}')
                            continue
                        # A live worker outranks an old merge, so the only column a
                        # second plan may reach is the one work sits in.
                        review = r.resolve_column(r.Stage.REVIEW, board, names)
                        self.assertIn(planned, (col, r.resolve_column(r.Stage.IN_PROGRESS, board, names),
                                                review),
                                      f'board {board_id} flip {column}->{col}')
            for pulls in ((pull(),), (pull('MERGED', merged_at=NEWER),)):
                facts = r.Facts(work, 100, False, pulls, column_entered=ENTRY)
                col, _ = r.target(facts, board, names)
                self.assertNotEqual(col, work)
                count += 1
            # An old merge is no reason to stay in the work column once it is idle.
            idle = r.Facts(work, r.GRACE_SECONDS + 1, False,
                           (pull('MERGED', merged_at=OLDER),), column_entered=ENTRY)
            self.assertNotEqual(r.target(idle, board, names)[0], work)
            count += 1
            facts = r.Facts(work, 100, True, column_entered=ENTRY)
            self.assertEqual(r.target(facts, board, names)[0],
                             r.resolve_column(r.Stage.IN_PROGRESS, board, names))
            count += 1
            for column in sorted(board.protected | {'Mystery column'}):
                facts = r.Facts(column, 100, True, (pull(),), column_entered=ENTRY)
                self.assertEqual(r.target(facts, board, names)[0], column)
                count += 1
            for here in (r.Stage.BACKLOG, r.Stage.IN_PROGRESS):
                column = r.stage_column_map(board)[here]
                for alive in (False, True):
                    for pulls in ((), (pull(),)):
                        stage = target_stage(board, r.Facts(column, 100, alive, pulls, column_entered=ENTRY))
                        stages_by_board.setdefault((here, alive, pulls), []).append(stage)
                        count += 1
        for key, stages in stages_by_board.items():
            self.assertEqual(len(set(stages)), 1, f'ranking split on {key}: {stages}')
        print(f'verify-reconcile-formal: combinations={count}')
        self.assertGreater(count, 500)

    def test_main_column_rule_rows(self):
        rows = (
            (r.Facts('Todo', 8000, True), 'Doing'),
            (r.Facts('Doing', 8000, True), 'Doing'),
            (r.Facts('Doing', 100, True, (pull(checks='red'),)), 'Checks'),
            (r.Facts('Doing', 100, True, (pull(),)), 'AI Review'),
            (r.Facts('Doing', 8000, pulls=(pull(checks='running'),)), 'Checks'),
            (r.Facts('Doing', 8000, pulls=(pull(checks='missing'),)), 'Checks'),
            (r.Facts('Checks', 8000, pulls=(pull(passed=True),)), 'AI Review'),
            (r.Facts('Doing', 7199, pulls=(pull('MERGED', passed=True),)), 'AI Review'),
            (r.Facts('Doing', 8000, pulls=(pull('MERGED'),)), 'AI Review'),
            (r.Facts('Doing', 8000, pulls=(pull('MERGED'), pull(checks='red'))), 'Checks'),
            (r.Facts('Doing', 7199), 'Doing'),
            (r.Facts('Doing', 7200), 'Todo'),
            (r.Facts('Doing', 8000, True, waiting=True), 'Doing'),
            (r.Facts('Doing', 8000, True, blocked=True), 'Doing'),
            (r.Facts('Valentin Review', 8000, True), 'Valentin Review'),
            (r.Facts('Done', 8000, True), 'Done'),
            (r.Facts('Todo', 60, verification=True), 'Verification Backlog'),
            (r.Facts('Verification Backlog', 60), 'Todo'),
            (r.Facts('Verification Backlog', 8000, pulls=(pull(),), verification=True), 'AI Review'),
            (r.Facts('Verification Backlog', 8000, pulls=(pull('MERGED'),), verification=True), 'AI Review'),
            (r.Facts('Verification Backlog', 8000, True, verification=True), 'Doing'),
            (r.Facts('Verification Backlog', 8000, verification=True), 'Verification Backlog'),
        )
        count = 0
        for board_id in (2060, 13556):
            for facts, expected in rows:
                with self.subTest(board=board_id, facts=facts):
                    self.assertEqual(r.target(facts, r.BOARDS[board_id])[0], expected)
                    count += 1
        for column, expected in (('Backlog', 'Backlog'), ('In Progress', 'Backlog'),
                                 ('AI Review', 'AI Review'), ('UX needed', 'UX needed')):
            with self.subTest(board=15, column=column):
                self.assertEqual(r.target(r.Facts(column, 8000), r.BOARDS[15])[0], expected)
                count += 1
        print(f'verify-reconcile-formal: main-rule-rows={count}')

    def test_a_merge_older_than_the_column_never_promotes(self):
        """The owner's rule, on every board: an old merge is history, not evidence.

        Reopened and parked cards carry the PR that once shipped them. That merge
        happened before the card entered its column, so it must not pull the card
        out of Backlog, and it must not demote a card already in review either.
        """
        for board_id in (15, 2060, 13556):
            board = r.board_config(board_id)
            names = board_names(board)
            backlog = r.stage_column_map(board)[r.Stage.BACKLOG]
            review = r.resolve_column(r.Stage.REVIEW, board, names)
            work = r.resolve_column(r.Stage.IN_PROGRESS, board, names)
            for passed in (False, True):
                for age in (100.0, r.GRACE_SECONDS + 1):
                    with self.subTest(board=board_id, passed=passed, age=age):
                        stale = (pull('MERGED', passed=passed, merged_at=OLDER),)
                        col, reason = r.target(r.Facts(backlog, age, False, stale, column_entered=ENTRY),
                                               board, names)
                        self.assertEqual((col, reason), (backlog, STALE_MERGE))
                        # The same PR merged after the entry still promotes, so the
                        # merge time is what decides, not the merge itself.
                        fresh = (pull('MERGED', passed=passed, merged_at=NEWER),)
                        self.assertEqual(r.target(r.Facts(backlog, age, False, fresh, column_entered=ENTRY),
                                                  board, names)[0], review)
                        # A live worker and an open PR are unaffected by the merge time.
                        self.assertEqual(r.target(r.Facts(backlog, age, True, stale, column_entered=ENTRY),
                                                  board, names)[0], work)
                        self.assertEqual(r.target(r.Facts(work, age, False, (pull(),), column_entered=ENTRY),
                                                  board, names)[0], review)
                        # Review holds: the merge is now older than the column, and an
                        # old merge never demotes the card it once moved.
                        held = r.Facts(review, r.GRACE_SECONDS + 1, False, stale, column_entered=LATER)
                        self.assertEqual(r.target(held, board, names)[0], review)
                        # An unknown merge time keeps the old reading: evidence.
                        unknown = (pull('MERGED', merged_at=None),)
                        self.assertEqual(r.target(r.Facts(backlog, age, False, unknown, column_entered=ENTRY),
                                                  board, names)[0], review)


if __name__ == '__main__':
    unittest.main()
