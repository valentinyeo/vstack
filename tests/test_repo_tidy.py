"""Tests for skills/repo-tidy and its proof skill.

Every test builds the throwaway world from
.claude/skills/verify-repo-tidy/sandbox.py: a bare origin, one clone, worktrees
in every state repo-tidy must tell apart, and a fake gh that serves fixture
PR data and records every write.

Run: python3 -m unittest discover -s tests -p 'test_*.py'
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIDY = ROOT / "skills/repo-tidy/repo-tidy"
VERIFY = ROOT / ".claude/skills/verify-repo-tidy"
SANDBOX_PY = VERIFY / "sandbox.py"
RUN = VERIFY / "run"


def load_sandbox():
    spec = importlib.util.spec_from_file_location("repo_tidy_sandbox", SANDBOX_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sandbox = load_sandbox()


def tidy(world, *args, extra_env=None, timeout=600):
    env = world.drive_env(extra_env)
    return subprocess.run([sys.executable, str(TIDY)] + list(args),
                          capture_output=True, text=True, env=env, timeout=timeout)


class SandboxCase(unittest.TestCase):
    """Builds one sandbox per test class unless a test needs its own."""

    neighbour = False

    @classmethod
    def build(cls):
        root = Path(tempfile.mkdtemp(prefix="repo-tidy-test-"))
        world = sandbox.Sandbox(root, neighbour=cls.neighbour)
        expect = world.build()
        return world, expect

    def setUp(self):
        if not hasattr(type(self), "_world"):
            type(self)._world, type(self)._expect = type(self).build()
            type(self).addClassCleanup(shutil.rmtree, type(self)._world.root, ignore_errors=True)
        self.world = type(self)._world
        self.expect = type(self)._expect


class TestGates(SandboxCase):
    """One apply run on a sandbox with every state, then grade every gate."""

    @classmethod
    def build(cls):
        world, expect = super().build()
        # A live process with its cwd inside one worktree: the in-use gate.
        cls.sleeper = subprocess.Popen(["sleep", "600"], cwd=str(world.wt_path("in-use")))
        cls.addClassCleanup(cls.sleeper.kill)
        cls.initial = sandbox.snapshot(world.root)
        cls.dry = tidy(world, "--all")
        cls.dry_snapshot = sandbox.snapshot(world.root)
        cls.apply = tidy(world, "--all", "--apply")
        cls.after = sandbox.snapshot(world.root)
        return world, expect

    def test_dry_run_removes_nothing(self):
        self.assertEqual(self.dry.returncode, 0, self.dry.stderr)
        for key in ("worktrees", "branches", "remote"):
            self.assertEqual(self.initial[key], self.dry_snapshot[key],
                             "dry run changed " + key)

    def test_exact_set_of_survivors(self):
        run_dir = self.world.root / "run"
        run_dir.mkdir(exist_ok=True)
        (run_dir / "dry.out").write_text(self.dry.stdout)
        (run_dir / "apply.json").write_text(self.apply.stdout)
        code, lines = sandbox.grade(self.world.root, run_dir)
        self.assertEqual(code, 0, "\n".join(lines))
        self.assertIn("PASS worktrees:", "\n".join(lines))
        self.assertIn("PASS commits:", "\n".join(lines))

    def test_apply_removed_shipped_and_kept_the_rest(self):
        self.assertEqual(self.apply.returncode, 0, self.apply.stderr)
        output = self.apply.stdout
        names = set(self.after["names"])
        for name in ("merged-clean", "squash-clean", "ignored-clean", "closed-stale"):
            self.assertNotIn(name, names, output)
        for name in ("wip", "unpushed", "in-use", "recent", "lease", "detached",
                     "open-pr", "squash-stale", "closed-recent", "scratch"):
            self.assertIn(name, names, output)

    def test_held_table_gives_a_reason(self):
        output = self.apply.stdout
        self.assertIn("wip", output)
        self.assertIn("scratch", output)
        self.assertIn("unshipped", output)
        self.assertIn("in use", output)
        self.assertIn("outside", output)

    def test_summary_line_per_repo(self):
        output = self.apply.stdout
        line = [l for l in output.splitlines() if l.startswith("sandbox:")]
        self.assertTrue(line, output)
        self.assertIn("worktrees removed 4", line[0], output)
        self.assertIn("local branches deleted 8", line[0], output)
        self.assertIn("remote deleted 4", line[0], output)
        self.assertIn("stale-unPR'd 1", line[0], output)

    def test_run_log_written(self):
        logs = list((self.world.home / ".local/state/repo-tidy").glob("*.json"))
        self.assertTrue(logs, "no run log under ~/.local/state/repo-tidy")
        data = json.loads(sorted(logs)[-1].read_text())
        self.assertTrue(data["apply"])
        self.assertEqual(data["repos"][0]["repo"], str(self.world.repo))

    def test_github_setting_patched_once(self):
        patches = [c for c in self.after["gh_calls"] if c.startswith("PATCH ")]
        self.assertEqual(patches,
                         ["PATCH repos/valentinyeo/sandbox delete_branch_on_merge=true"])

    def test_every_held_commit_survived(self):
        alive = set(self.after["alive_commits"])
        missing = [c for c in self.expect["held_commits"] if c not in alive]
        self.assertEqual(missing, [])
        self.assertTrue(self.expect["held_commits"])

    def test_default_branch_never_deleted(self):
        self.assertIn("main", self.after["remote"])
        self.assertIn("main", self.after["branches"])
        self.assertIn("remote-protected", self.after["remote"])


class TestDryRunOnly(SandboxCase):
    def test_dry_run_leaves_every_worktree_and_branch(self):
        before = sandbox.snapshot(self.world.root)
        result = tidy(self.world, "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = sandbox.snapshot(self.world.root)
        self.assertEqual(before["worktrees"], after["worktrees"])
        self.assertEqual(before["branches"], after["branches"])
        self.assertEqual(before["remote"], after["remote"])
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("REMOVE worktree", result.stdout)


class TestCap(SandboxCase):
    def test_max_remove_caps_and_reports_deferred(self):
        result = tidy(self.world, "--all", "--apply", "--max-remove", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = sandbox.snapshot(self.world.root)
        removed = [n for n in self.expect["gone_worktrees"]
                   if n not in set(after["names"])]
        self.assertEqual(len(removed), 1, result.stdout)
        self.assertIn("DEFERRED", result.stdout)


class TestBrokenGh(SandboxCase):
    def test_gh_failure_fails_closed(self):
        before = sandbox.snapshot(self.world.root)
        result = tidy(self.world, "--all", "--apply", extra_env={"GH_FAIL": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        after = sandbox.snapshot(self.world.root)
        self.assertEqual(before["remote"], after["remote"], result.stdout)
        names = set(after["names"])
        # Squash merges need the PR data, so it must stay.
        self.assertIn("squash-clean", names, result.stdout)
        # Ancestry is local, so an already-merged branch can still go.
        self.assertNotIn("merged-clean", names, result.stdout)
        self.assertIn("remote decisions skipped", result.stdout)
        self.assertFalse([c for c in after["gh_calls"] if c.startswith("PATCH ")])


class TestRebaseInProgress(SandboxCase):
    def test_repo_mid_rebase_is_skipped(self):
        (self.world.repo / ".git/rebase-merge").mkdir()
        result = tidy(self.world, "--all", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = sandbox.snapshot(self.world.root)
        names = set(after["names"])
        for name in self.expect["gone_worktrees"]:
            self.assertIn(name, names, result.stdout)
        self.assertIn("mid-rebase", result.stdout)


class TestMine(SandboxCase):
    neighbour = True

    def test_mine_mode_touches_one_repo(self):
        result = tidy(self.world, "--apply", "--mine", str(self.world.repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("other-done", str(list((self.world.projects).glob("other-done"))))
        self.assertTrue((self.world.projects / "other-done").exists(), result.stdout)
        self.assertIn("sandbox:", result.stdout)
        self.assertNotIn("other:", result.stdout)

    def test_a_worktree_path_is_a_repo(self):
        result = tidy(self.world, str(self.world.wt_path("wip")))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("not a repo", result.stdout)
        self.assertIn("sandbox:", result.stdout)

    def test_mine_outside_a_repo_does_nothing(self):
        outside = self.world.root / "not-a-repo"
        outside.mkdir()
        result = tidy(self.world, "--apply", "--mine", str(outside))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class TestScale(unittest.TestCase):
    """A real-size dry run must finish well inside a minute."""

    def test_800_worktrees_1300_branches_dry_run_under_60s(self):
        root = Path(tempfile.mkdtemp(prefix="repo-tidy-scale-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        world = sandbox.Sandbox(root, scale=800)
        world.build()
        started = time.time()
        result = tidy(world, "--all", timeout=300)
        elapsed = time.time() - started
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 60, "dry run took %.1fs" % elapsed)
        self.assertIn("worktrees", result.stdout)
        self.assertGreaterEqual(len(sandbox.snapshot(root)["worktrees"]), 801)
        self.assertGreaterEqual(len(sandbox.snapshot(root)["branches"]), 1300)


class TestStopHook(unittest.TestCase):
    """The Stop hook finds the script beside itself, so a chat needs no install.

    Without that, a chat that follows SKILL.md and adds the hook to its own
    settings gets a hook that silently does nothing.
    """

    def test_hook_runs_the_script_beside_it(self):
        workspace = Path(tempfile.mkdtemp(prefix="repo-tidy-hook-"))
        self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
        root = workspace / "vstack"
        (root / "hooks").mkdir(parents=True)
        (root / "skills/repo-tidy").mkdir(parents=True)
        shutil.copy(str(ROOT / "hooks/repo-tidy-stop"), str(root / "hooks/repo-tidy-stop"))
        marker = workspace / "called.txt"
        stub = root / "skills/repo-tidy/repo-tidy"
        stub.write_text('#!/usr/bin/env bash\nprintf "%%s\\n" "$*" > "%s"\n' % marker)
        stub.chmod(0o755)

        home = workspace / "home"
        home.mkdir()
        repo = workspace / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        binary = workspace / "bin"
        binary.mkdir()
        # A stripped PATH: no repo-tidy on it, and no ~/.local/bin fallback.
        for tool in ("bash", "git", "cksum", "date", "mkdir", "cat", "cut",
                     "setsid", "readlink", "nohup"):
            found = shutil.which(tool)
            if found:
                (binary / tool).symlink_to(found)

        env = {"HOME": str(home), "PATH": str(binary), "CLAUDE_PROJECT_DIR": str(repo)}
        result = subprocess.run([str(root / "hooks/repo-tidy-stop")],
                                capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        for _ in range(200):
            if marker.exists():
                break
            time.sleep(0.05)
        self.assertTrue(marker.exists(), "the hook never ran the script beside it")
        self.assertIn("--apply", marker.read_text())
        self.assertIn("--mine %s" % repo, marker.read_text())


class TestVerifySkill(unittest.TestCase):
    """The proof skill drives its own sandbox and grades itself."""

    def test_verify_run_passes(self):
        home = Path(tempfile.mkdtemp(prefix="repo-tidy-verify-home-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        env = dict(os.environ, HOME=str(home))
        result = subprocess.run([str(RUN)], capture_output=True, text=True, env=env, timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VERDICT PASS", result.stdout)
        self.assertTrue(list((home / ".local/state/verify-repo-tidy").iterdir()))


if __name__ == "__main__":
    unittest.main()
