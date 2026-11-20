#!/usr/bin/env python3
"""Drive skills/pstack-diff/pstack-diff against fixture repos."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/pstack-diff/pstack-diff"
FIXTURES = Path(__file__).resolve().parent / "fixtures/pstack-diff"


def run_diff(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = os.environ.get("HOME", str(Path.home()))
    return subprocess.run(
        [sys.executable, str(TOOL), *extra, str(repo)],
        capture_output=True,
        text=True,
        env=env,
    )


class PstackDiffTest(unittest.TestCase):
    def test_clean_repo_exit_zero(self):
        result = run_diff(FIXTURES / "clean")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ASKED verify-skill:", result.stdout)
        self.assertNotIn("EXTRA ", result.stdout)
        self.assertNotIn("GAP ", result.stdout)

    def test_second_verifier_extra_exit_one(self):
        result = run_diff(FIXTURES / "extra-verifier")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("EXTRA workflow:", result.stdout)

    def test_rule_restatement_extra_with_line(self):
        result = run_diff(FIXTURES / "extra-rules")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("EXTRA rule restatement: CLAUDE.md:", result.stdout)

    def test_missing_verify_skill_gap(self):
        result = run_diff(FIXTURES / "gap-no-verify")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("GAP verify-skill:", result.stdout)

    def test_json_flag(self):
        result = run_diff(FIXTURES / "clean", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["exit"], 0)
        self.assertTrue(payload["asked"])


if __name__ == "__main__":
    unittest.main()