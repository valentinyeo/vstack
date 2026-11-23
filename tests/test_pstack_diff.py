#!/usr/bin/env python3
"""Drive skills/pstack-diff/pstack-diff against fixture repos."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/pstack-diff/pstack-diff"


def _load_pstack_diff():
    loader = importlib.machinery.SourceFileLoader("pstack_diff", str(TOOL))
    spec = importlib.util.spec_from_loader("pstack_diff", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PSTACK_DIFF = _load_pstack_diff()
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


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def clean_files() -> dict[str, str]:
    source = FIXTURES / "clean"
    return {path.relative_to(source).as_posix(): path.read_text() for path in source.rglob("*") if path.is_file()}


def build_repo(test: unittest.TestCase, base: dict[str, str], head: dict[str, str]) -> Path:
    holder = tempfile.TemporaryDirectory(prefix="pstack-diff-base-")
    test.addCleanup(holder.cleanup)
    root = Path(holder.name)
    for name, text in base.items():
        write(root, name, text)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    for name, text in head.items():
        write(root, name, text)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "head")
    return root


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


SCORECARD = "  scorecard:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python3 scripts/scorecard.py\n"
BUDGET = "  budget:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python3 scripts/budget.py\n"


class PstackDiffBaseTest(unittest.TestCase):
    def test_new_extra_in_head_exit_one(self):
        base = clean_files()
        workflow = base[".github/workflows/ci.yml"]
        root = build_repo(self, base, {".github/workflows/ci.yml": workflow.rstrip("\n") + "\n" + SCORECARD})
        result = run_diff(root, "--base", "HEAD~1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("EXTRA workflow: .github/workflows/ci.yml job scorecard", result.stdout)

    def test_same_extra_in_base_exit_zero(self):
        base = clean_files()
        base[".github/workflows/ci.yml"] = base[".github/workflows/ci.yml"].rstrip("\n") + "\n" + SCORECARD
        head = {".github/workflows/ci.yml": base[".github/workflows/ci.yml"].replace("name: ci", "name: ci # touched")}
        root = build_repo(self, base, head)
        result = run_diff(root, "--base", "HEAD~1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BASE workflow: .github/workflows/ci.yml job scorecard", result.stdout)
        self.assertNotIn("EXTRA workflow:", result.stdout)

    def test_house_listed_new_gate_exit_zero(self):
        base = clean_files()
        workflow = base[".github/workflows/ci.yml"].rstrip("\n") + "\n" + BUDGET
        root = build_repo(
            self,
            base,
            {
                ".github/workflows/ci.yml": workflow,
                ".pstack-house.txt": ".github/workflows/ci.yml:budget the repo needs it\n",
            },
        )
        result = run_diff(root, "--base", "HEAD~1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HOUSE .github/workflows/ci.yml job budget", result.stdout)
        self.assertNotIn("EXTRA workflow:", result.stdout)

    def test_base_that_removed_an_old_extra_does_not_blame_this_branch(self):
        base = clean_files()
        workflow = base[".github/workflows/ci.yml"].rstrip("\n") + "\n" + SCORECARD
        holder = tempfile.TemporaryDirectory(prefix="pstack-diff-base-")
        self.addCleanup(holder.cleanup)
        root = Path(holder.name)
        write(root, ".github/workflows/ci.yml", workflow)
        git(root, "init", "-q")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "old extra")
        default = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        git(root, "branch", "feature")
        write(root, ".github/workflows/ci.yml", clean_files()[".github/workflows/ci.yml"])
        git(root, "add", "-A")
        git(root, "commit", "-qm", "base removed the extra")
        git(root, "checkout", "-q", "feature")
        write(root, ".github/workflows/ci.yml", workflow.replace("name: ci", "name: ci # feature"))
        git(root, "add", "-A")
        git(root, "commit", "-qm", "feature work")
        result = run_diff(root, "--base", default)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BASE workflow: .github/workflows/ci.yml job scorecard", result.stdout)

    def test_gap_alone_does_not_fail_base_mode(self):
        root = build_repo(self, {"README.md": "x\n"}, {"README.md": "y\n"})
        result = run_diff(root, "--base", "HEAD~1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GAP verify-skill", result.stdout)


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

    def test_ai_judge_matches_script_file_not_directory(self):
        is_judge = PSTACK_DIFF._is_ai_judge
        self.assertFalse(
            is_judge("node .github/scripts/pstack-verifier/coverage.cjs check"),
            "registry coverage check is not an AI judge",
        )
        self.assertTrue(is_judge("python3 scripts/column-verifier.py"))
        self.assertTrue(is_judge("scripts/run-verifier"))
        self.assertTrue(is_judge("python3 scripts/verification/advisor.py"))

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

    def test_product_security_invariant_not_rule_restatement(self):
        result = run_diff(FIXTURES / "product-invariants")
        self.assertNotIn("EXTRA rule restatement:", result.stdout, result.stdout)

    def test_verifier_needs_chain_not_double_extra(self):
        result = run_diff(FIXTURES / "verifier-stages")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ASKED verifier workflow:", result.stdout)
        extras = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("EXTRA workflow:") and "pstack-verifier" in line
        ]
        self.assertEqual(extras, [], result.stdout)

    def test_yaml_comment_budget_does_not_mark_extra(self):
        workflow = (
            "name: ci\non:\n  pull_request:\njobs:\n"
            "  checks:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: pnpm test\n"
            "        # median run used 39.13% of budget.\n"
        )
        holder = tempfile.TemporaryDirectory(prefix="pstack-diff-comment-")
        self.addCleanup(holder.cleanup)
        root = Path(holder.name)
        write(root, ".github/workflows/ci.yml", workflow)
        write(root, ".claude/skills/verify-app/SKILL.md", "# x\n")
        write(root, ".claude/skills/verify-app/features/README.md", "x\n")
        write(
            root,
            ".github/workflows/verify.yml",
            "name: v\non:\n  pull_request:\njobs:\n"
            "  verify:\n    runs-on: ubuntu-latest\n    steps:\n      - run: codex exec\n",
        )
        result = run_diff(root)
        self.assertNotIn("EXTRA workflow: .github/workflows/ci.yml job checks", result.stdout)

    def test_real_budget_gate_still_extra(self):
        base = clean_files()
        root = build_repo(
            self,
            base,
            {".github/workflows/ci.yml": base[".github/workflows/ci.yml"].rstrip("\n") + "\n" + BUDGET},
        )
        result = run_diff(root)
        self.assertIn("EXTRA workflow: .github/workflows/ci.yml job budget", result.stdout)

    def test_step_continue_on_error_does_not_drop_verifier_job(self):
        body = (
            "    runs-on: ubuntu-latest\n    needs: engine\n    steps:\n"
            "      - run: echo x\n      - name: Verify with Codex\n"
            "        continue-on-error: true\n        run: codex exec\n"
        )
        self.assertTrue(PSTACK_DIFF._job_fails_pr(body))

    def test_job_level_continue_on_error_drops_job(self):
        body = "    runs-on: ubuntu-latest\n    continue-on-error: true\n    steps:\n      - run: echo\n"
        self.assertFalse(PSTACK_DIFF._job_fails_pr(body))

    def test_astro_fixture_no_extra_checks_no_verifier_gap(self):
        result = run_diff(FIXTURES / "astro-rs")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("EXTRA workflow: .github/workflows/ci.yml job checks", result.stdout)
        self.assertNotIn("GAP verifier workflow", result.stdout)
        self.assertIn("ASKED verifier workflow:", result.stdout)

    def test_multiprompt_verdict_job_wins_over_comment_sicko(self):
        result = run_diff(FIXTURES / "multiprompt-verifier-rank")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        asked = next(
            line for line in result.stdout.splitlines() if line.startswith("ASKED verifier workflow:")
        )
        self.assertIn("pr-verifier.yml job verdict", asked)
        self.assertIn(
            "EXTRA workflow: .github/workflows/no-comments.yml job pstack-no-comments",
            result.stdout,
        )

    def test_base_mode_ignores_helper_grep_for_pstack_verifier_name(self):
        real = (
            "name: a\non:\n  pull_request:\njobs:\n"
            "  verifier:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: python3 scripts/run-verifier\n"
        )
        helper = (
            "name: z\non:\n  pull_request:\njobs:\n"
            "  helper:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: claude -p foo\n"
        )
        skill = ".claude/skills/verify-app/SKILL.md"
        features = ".claude/skills/verify-app/features/README.md"
        root = build_repo(
            self,
            {
                ".github/workflows/a.yml": real,
                ".github/workflows/z.yml": helper,
                skill: "# x\n",
                features: "x\n",
            },
            {".github/workflows/z.yml": helper.rstrip("\n") + "\n      - run: grep pstack-verifier\n"},
        )
        result = run_diff(root, "--base", "HEAD~1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ASKED verifier workflow: .github/workflows/a.yml job verifier", result.stdout)

    def test_base_mode_ignores_gh_pr_comment_on_triage(self):
        real = (
            "name: a\non:\n  pull_request:\njobs:\n"
            "  verifier:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: python3 scripts/run-verifier\n"
        )
        helper = (
            "name: z\non:\n  pull_request:\njobs:\n"
            "  triage:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: claude -p foo\n"
        )
        skill = ".claude/skills/verify-app/SKILL.md"
        features = ".claude/skills/verify-app/features/README.md"
        root = build_repo(
            self,
            {
                ".github/workflows/a.yml": real,
                ".github/workflows/z.yml": helper,
                skill: "# x\n",
                features: "x\n",
            },
            {
                ".github/workflows/z.yml": helper.rstrip("\n")
                + "\n      - run: gh pr comment 1 --body-file verdict.md\n"
            },
        )
        result = run_diff(root, "--base", "HEAD~1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ASKED verifier workflow: .github/workflows/a.yml job verifier", result.stdout)

    def test_base_mode_ignores_yaml_comment_naming_pstack_verifier(self):
        real = (
            "name: a\non:\n  pull_request:\njobs:\n"
            "  verifier:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: python3 scripts/run-verifier\n"
        )
        helper = (
            "name: z\non:\n  pull_request:\njobs:\n"
            "  helper:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: claude -p foo\n"
        )
        skill = ".claude/skills/verify-app/SKILL.md"
        features = ".claude/skills/verify-app/features/README.md"
        root = build_repo(
            self,
            {
                ".github/workflows/a.yml": real,
                ".github/workflows/z.yml": helper,
                skill: "# x\n",
                features: "x\n",
            },
            {
                ".github/workflows/z.yml": helper.rstrip("\n")
                + "\n        # pstack-verifier posts the real verdict elsewhere\n"
            },
        )
        result = run_diff(root, "--base", "HEAD~1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ASKED verifier workflow: .github/workflows/a.yml job verifier", result.stdout)

    def test_stale_checkout_warning_does_not_change_exit(self):
        holder = tempfile.TemporaryDirectory(prefix="pstack-diff-behind-")
        self.addCleanup(holder.cleanup)
        root = Path(holder.name)
        for name, text in clean_files().items():
            write(root, name, text)
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "one")
        git(root, "commit", "-qm", "two", "--allow-empty")
        origin_tip = git(root, "rev-parse", "HEAD")
        git(root, "reset", "--hard", "HEAD~1")
        git(root, "update-ref", "refs/remotes/origin/main", origin_tip)
        git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        result = run_diff(root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            any(line.startswith("WARN checkout is") and "behind origin/main" in line for line in result.stdout.splitlines()),
            result.stdout,
        )


SELECTION_VERIFIER = (
    "name: PR verifier\non:\n  pull_request:\njobs:\n"
    "  verdict:\n    runs-on: ubuntu-latest\n    steps:\n"
    "      - run: node tools/pr-verifier.cjs finalize verifier-out/selection.json\n"
    "      - run: claude -p \"judge the evidence\"\n"
)


def selection_repo(test: unittest.TestCase, finalize: str) -> Path:
    holder = tempfile.TemporaryDirectory(prefix="pstack-diff-selection-")
    test.addCleanup(holder.cleanup)
    root = Path(holder.name)
    write(root, ".github/workflows/pr-verifier.yml", SELECTION_VERIFIER)
    write(root, "tools/pr-verifier.cjs", finalize)
    write(root, ".claude/skills/verify-app/SKILL.md", "# x\n")
    write(root, ".claude/skills/verify-app/features/README.md", "x\n")
    return root


class UncoveredPassGateTest(unittest.TestCase):
    """multiprompt PR 1205 passed with its changed product files listed as unmapped."""

    def test_selection_verifier_that_can_pass_uncovered_files_is_a_gap(self):
        root = selection_repo(
            self,
            "if (selection.uncovered && final === 'PASS') final = 'PASS+NOTES';\n",
        )
        result = run_diff(root)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        gap = next(line for line in result.stdout.splitlines() if line.startswith("GAP uncovered pass gate:"))
        self.assertIn(".github/workflows/pr-verifier.yml", gap)
        self.assertIn("tools/pr-verifier.cjs", gap)
        self.assertIn("uncovered_gate", gap)

    def test_selection_verifier_routed_through_the_gate_is_asked(self):
        root = selection_repo(
            self,
            "const gate = require('./uncovered_gate.cjs');\n"
            "final = gate.demote(selection, final);\n",
        )
        result = run_diff(root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ASKED uncovered pass gate: tools/pr-verifier.cjs", result.stdout)
        self.assertNotIn("GAP uncovered pass gate", result.stdout)

    def test_verifier_without_a_changed_file_selection_says_nothing(self):
        base = clean_files()
        root = build_repo(self, base, {"README.md": "y\n"})
        result = run_diff(root)
        self.assertNotIn("uncovered pass gate", result.stdout)

    def test_real_multiprompt_verifier_fixture_reports_the_gap(self):
        result = run_diff(FIXTURES / "multiprompt-verifier-rank")
        self.assertIn("GAP uncovered pass gate: .github/workflows/pr-verifier.yml", result.stdout)


if __name__ == "__main__":
    unittest.main()