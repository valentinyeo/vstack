"""Exhaustive reconcile stage model: one evidence order, no flip-flop.

The cases live in tests/test_verify_reconcile_model.py, which CI runs. This entry
point runs that same file from the skill folder, so the two cannot drift.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests'))

from test_verify_reconcile_model import VerifyReconcileModel  # noqa: E402


if __name__ == '__main__':
    unittest.main()
