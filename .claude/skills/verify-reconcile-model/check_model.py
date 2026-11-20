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


def pull(state='OPEN', checks='green', passed=False):
    return r.Pull('https://github.com/example/x/pull/1', state, checks, passed)


PR_STATES = (
    (),
    (pull(checks='red'),),
    (pull(),),
    (pull('MERGED', passed=True),),
    (pull('MERGED'),),
)


def board_names(board):
    return {} if r.product_board(board) else r.stage_names(sections=board.managed | board.protected)


def target_stage(board, facts):
    col, _ = r.target(facts, board, board_names(board))
    if col in board.protected or col.startswith('Flag:'):
        return r.Stage.PROTECTED
    stage = r.column_stage_map(board).get(col)
    return stage if stage is not None else r.Stage.UNMANAGED


def in_progress_column(board):
    return r.stage_column_map(board)[r.Stage.IN_PROGRESS]


class VerifyReconcileModel(unittest.TestCase):
    def test_exhaustive_model(self):
        count = 0
        for board_id in (15, 2060, 13556):
            board = r.board_config(board_id)
            names = board_names(board)
            backlog = r.stage_column_map(board)[r.Stage.BACKLOG]
            work = in_progress_column(board)
            for column in sorted(board.managed):
                for age, alive, pulls, waiting, blocked, verification in itertools.product(
                        (100.0, 8000.0), (False, True), PR_STATES, (False,), (False,), (False, True)):
                    facts = r.Facts(column, age, alive, pulls, waiting, blocked, verification)
                    count += 1
                    here = r.column_stage_of(board, column)
                    col, _ = r.target(facts, board, names)
                    if here in (r.Stage.PROTECTED, r.Stage.UNMANAGED):
                        continue
                    if col == column:
                        continue
                    if here == r.Stage.VERIFICATION and not verification:
                        continue
                    reset = r.Facts(col, 0, alive, pulls, waiting, blocked, verification)
                    self.assertEqual(r.target(reset, board, names)[0], col,
                                     f'board {board_id} flip {column}->{col}')
                    aged = r.Facts(col, r.GRACE_SECONDS + 1, alive, pulls, waiting, blocked, verification)
                    self.assertEqual(r.target(aged, board, names)[0], col)
            for pulls in ((pull(),), (pull('MERGED'),)):
                facts = r.Facts(work, 100, False, pulls)
                col, _ = r.target(facts, board, names)
                self.assertNotEqual(col, work)
                count += 1
            facts = r.Facts(work, 100, True)
            self.assertEqual(r.target(facts, board, names)[0],
                             r.resolve_column(r.Stage.IN_PROGRESS, board, names))
            count += 1
            for column in sorted(board.protected | {'Mystery column'}):
                facts = r.Facts(column, 100, True, (pull(),))
                self.assertEqual(r.target(facts, board, names)[0], column)
                count += 1
            for alive in (False, True):
                for pulls in ((), (pull(),)):
                    stages = [target_stage(board, r.Facts(backlog, 100, alive, pulls))]
                    stages.append(target_stage(board, r.Facts(work, 100, alive, pulls)))
                    self.assertEqual(len(set(stages)), 1)
                    count += 1
        print(f'verify-reconcile-model: combinations={count}')
        self.assertGreater(count, 500)


if __name__ == '__main__':
    unittest.main()