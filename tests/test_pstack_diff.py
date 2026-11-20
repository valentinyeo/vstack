#!/usr/bin/env python3
"""Drive skills/pstack-diff/pstack-diff against fixture repos."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/pstack-diff/pstack-diff"
FIXTURES = Path(__file__).resolve().parent / "fixtures/pstack-diff"
CLONES = FIXTURES / "clones"
PSTACK = FIXTURES / "pstack"


def run_diff(
    repo: Path,
    *extra: str,
    clones: Path | None = None,
    pstack: Path | None = PSTACK,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = os.environ.get("HOME", str(Path.home()))
    if clones is not None:
        env["PSTACK_DIFF_CLONES"] = str(clones)
    if pstack is None:
        env.pop("PSTACK_DIFF_PSTACK", None)
    else:
        env["PSTACK_DIFF_PSTACK"] = str(pstack)
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
        self.assertIn("ASKED verify-skill: verify-app", result.stdout)
        self.assertNotIn("EXTRA ", result.stdout)
        self.assertNotIn("GAP ", result.stdout)

    def test_second_verifier_extra_exit_one(self):
        result = run_diff(FIXTURES / "extra-verifier")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("ASKED verifier workflow:", result.stdout)
        self.assertIn("EXTRA workflow:", result.stdout)
        self.assertIn("job verify", result.stdout.split("ASKED verifier workflow:")[1].split("\n")[0])

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

    def test_reusable_workflow_resolves_ai_judge(self):
        result = run_diff(FIXTURES / "reusable-verifier", clones=CLONES)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ASKED verifier workflow:", result.stdout)
        self.assertIn("via valentinyeo/house-rules", result.stdout)
        self.assertIn("job pstack-verifier", result.stdout)

    def test_house_listed_gate_not_extra(self):
        result = run_diff(FIXTURES / "house-pacer", clones=CLONES)
        self.assertIn("HOUSE ", result.stdout)
        self.assertIn("pacer-check", result.stdout)
        self.assertNotIn("EXTRA workflow: .github/workflows/checks.yml job pacer-check", result.stdout)

    def test_multi_verify_skills_asked(self):
        result = run_diff(FIXTURES / "multi-verify", clones=CLONES)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ASKED verify-skill: verify-app, verify-other", result.stdout)
        self.assertNotIn("EXTRA verify-skill", result.stdout)

    def test_pstack_flag_wins_over_env(self):
        result = run_diff(
            FIXTURES / "clean",
            "--pstack",
            str(PSTACK),
            pstack=FIXTURES / "no-such-pstack",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ASKED pstack recipe: 0.15.43", result.stdout)

    def test_missing_pstack_dir_names_the_gap(self):
        result = run_diff(FIXTURES / "clean", pstack=FIXTURES / "no-such-pstack")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("GAP pstack: no install under", result.stderr)


if __name__ == "__main__":
    unittest.main()