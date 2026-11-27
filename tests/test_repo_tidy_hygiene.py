"""Tests for repo-tidy's fast hygiene pass: idle build caches and a project's own /tmp.

Every test builds a throwaway world under its own temp directory: one git project with
its own worktrees beside it, and a /tmp-shaped directory named after the project. The
pass is graded on what survives, never on what it says about itself.

Run one module at a time: python3 -m unittest tests.test_repo_tidy_hygiene
"""

import importlib.machinery
import importlib.util
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
DAY = 86400


def load_tidy():
    loader = importlib.machinery.SourceFileLoader("repo_tidy_script", str(TIDY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def age(path, seconds):
    """Backdate a path, and everything under it, by whole seconds."""
    when = time.time() - seconds
    for dirpath, dirnames, filenames in os.walk(str(path), topdown=False):
        for name in filenames:
            try:
                os.utime(os.path.join(dirpath, name), (when, when), follow_symlinks=False)
            except OSError:
                pass
        try:
            os.utime(dirpath, (when, when))
        except OSError:
            pass
    try:
        os.utime(str(path), (when, when))
    except OSError:
        pass


class World:
    """One project with its own worktrees, and a /tmp-shaped directory for it."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.home = self.root / "home"
        self.projects = self.home / "projects"
        self.tmproot = self.root / "tmp"
        self.repo = self.projects / "demo"
        self.env = dict(os.environ)
        self.env.update({
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Sandbox",
            "GIT_AUTHOR_EMAIL": "sandbox@example.com",
            "GIT_COMMITTER_NAME": "Sandbox",
            "GIT_COMMITTER_EMAIL": "sandbox@example.com",
        })

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(["git"] + [str(a) for a in args], cwd=str(cwd or self.repo),
                              env=self.env, capture_output=True, text=True, check=check)

    def build(self):
        self.projects.mkdir(parents=True)
        self.tmproot.mkdir(parents=True)
        (self.home / ".local/state").mkdir(parents=True)
        self.git("init", "-q", str(self.repo), cwd=self.root)
        (self.repo / ".gitignore").write_text("node_modules/\ntarget/\ndist/\n.next/\n.turbo/\n")
        (self.repo / "app.py").write_text("print('demo')\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        return self

    def worktree(self, name, branch):
        path = self.projects / ("demo-" + name)
        self.git("worktree", "add", "-q", "-b", branch, str(path), "HEAD")
        return path

    def build_output(self, folder):
        """Every known output directory, with one file each, inside a worktree."""
        for name in ("node_modules", "target", "dist", ".next", ".turbo"):
            path = folder / name
            path.mkdir(parents=True, exist_ok=True)
            (path / "out.txt").write_text("rebuilt by the next build\n")

    def tmp_entry(self, name, age_seconds=None, kind="dir"):
        path = self.tmproot / name
        if kind == "dir":
            path.mkdir(parents=True)
            (path / "scratch.txt").write_text("scratch\n")
        elif kind == "file":
            path.write_text("scratch\n")
        elif kind == "symlink":
            path.symlink_to("/etc")
        if age_seconds:
            age(path, age_seconds)
        return path

    def tidy(self, *args, timeout=120):
        return subprocess.run([sys.executable, str(TIDY), "--project", str(self.repo),
                               "--projects-root", str(self.projects),
                               "--tmp-root", str(self.tmproot)] + list(args),
                              capture_output=True, text=True, env=self.env, timeout=timeout)


class HygieneCase(unittest.TestCase):
    def world(self):
        root = Path(tempfile.mkdtemp(prefix="repo-tidy-hygiene-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return World(root).build()


class TestIdleBuildCaches(HygieneCase):
    """Only an idle worktree's rebuildable output goes, and only with --apply."""

    def setUp(self):
        self.w = self.world()
        self.idle = self.w.worktree("wt-idle", "idle-branch")
        self.w.build_output(self.idle)
        age(self.idle, 3 * DAY)
        self.recent = self.w.worktree("wt-recent", "recent-branch")
        self.w.build_output(self.recent)
        (self.recent / "src").mkdir()
        (self.recent / "src/new.py").write_text("fresh work\n")

    def test_dry_run_names_the_output_and_removes_nothing(self):
        result = self.w.tidy("--prune-caches")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WOULD-PRUNE cache", result.stdout)
        self.assertIn(str(self.idle / "node_modules"), result.stdout)
        self.assertTrue((self.idle / "node_modules").exists())
        self.assertTrue((self.idle / "target").exists())

    def test_apply_removes_only_rebuildable_output_of_the_idle_worktree(self):
        result = self.w.tidy("--prune-caches", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("node_modules", "target", "dist", ".next", ".turbo"):
            with self.subTest(output=name):
                self.assertFalse((self.idle / name).exists())
        # The worktree itself, and every tracked file in it, stays.
        self.assertTrue((self.idle / "app.py").is_file())
        self.assertTrue((self.idle / ".gitignore").is_file())
        self.assertTrue((self.idle / ".git").exists())
        self.assertIn("idle-branch", self.w.git("worktree", "list").stdout)

    def test_recent_worktree_keeps_its_build_output(self):
        result = self.w.tidy("--prune-caches", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("node_modules", "target", "dist", ".next", ".turbo"):
            with self.subTest(output=name):
                self.assertTrue((self.recent / name).exists())
        self.assertIn("wt-recent", result.stdout)

    def test_main_checkout_is_never_a_candidate(self):
        self.w.build_output(self.w.repo)
        age(self.w.repo, 3 * DAY)
        result = self.w.tidy("--prune-caches", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.w.repo / "node_modules").exists())
        self.assertNotIn(str(self.w.repo / "node_modules"), result.stdout)

    def test_live_process_in_the_worktree_holds_every_output(self):
        self.w.build_output(self.idle)
        age(self.idle, 3 * DAY)
        sleeper = subprocess.Popen(["/usr/bin/sleep", "60"], cwd=str(self.idle),
                                   env=self.w.env)
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        time.sleep(0.2)
        result = self.w.tidy("--prune-caches", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("node_modules", "target"):
            with self.subTest(output=name):
                self.assertTrue((self.idle / name).exists())
        self.assertIn("in use", result.stdout)

    def test_output_holding_a_tracked_file_is_held(self):
        self.w.build_output(self.idle)
        (self.idle / "dist/kept.txt").write_text("committed on purpose\n")
        self.w.git("add", "-f", "dist/kept.txt", cwd=self.idle)
        self.w.git("commit", "-qm", "keep one artifact", cwd=self.idle)
        age(self.idle, 3 * DAY)
        result = self.w.tidy("--prune-caches", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.idle / "dist/kept.txt").is_file())
        self.assertIn("tracked", result.stdout)
        self.assertFalse((self.idle / "node_modules").exists())

    def test_max_remove_caps_the_pass(self):
        result = self.w.tidy("--prune-caches", "--apply", "--max-remove", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        left = [name for name in ("node_modules", "target", "dist", ".next", ".turbo")
                if (self.idle / name).exists()]
        self.assertEqual(len(left), 4, result.stdout)
        self.assertIn("over --max-remove", result.stdout)


class TestProjectTmp(HygieneCase):
    """A project cleans its own /tmp entries, never a recent one and never another's."""

    def setUp(self):
        self.w = self.world()
        self.old_dir = self.w.tmp_entry("demo-old-scratch", age_seconds=3 * DAY)
        self.old_file = self.w.tmp_entry("demo-old-run.log", age_seconds=3 * DAY, kind="file")
        self.dotted = self.w.tmp_entry("demo.build-cache", age_seconds=3 * DAY)
        self.recent = self.w.tmp_entry("demo-recent")
        self.other = self.w.tmp_entry("otherproj-old", age_seconds=3 * DAY)
        self.bare = self.w.tmp_entry("demo", age_seconds=3 * DAY)
        self.link = self.w.tmp_entry("demo-link", age_seconds=3 * DAY, kind="symlink")

    def test_dry_run_removes_nothing(self):
        result = self.w.tidy("--clean-tmp")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WOULD-CLEAN tmp", result.stdout)
        self.assertTrue(self.old_dir.exists())

    def test_apply_removes_only_this_projects_old_entries(self):
        result = self.w.tidy("--clean-tmp", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.old_dir.exists())
        self.assertFalse(self.old_file.exists())
        self.assertFalse(self.dotted.exists())
        # Recent, another project's, a bare name and a symlink all stay.
        self.assertTrue(self.recent.exists())
        self.assertTrue(self.other.exists())
        self.assertTrue(self.bare.exists())
        self.assertTrue(self.link.exists())
        self.assertIn("own-prefix", result.stdout)

    def test_live_process_holding_an_entry_keeps_it(self):
        holder = subprocess.Popen(["/usr/bin/sleep", "60"], cwd=str(self.old_dir),
                                  env=self.w.env)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        time.sleep(0.2)
        result = self.w.tidy("--clean-tmp", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.old_dir.exists())
        self.assertIn("in use", result.stdout)

    def test_a_project_never_cleans_another_projects_tmp(self):
        other_repo = self.w.projects / "other"
        self.w.git("init", "-q", str(other_repo), cwd=self.w.root)
        (other_repo / "x").write_text("x\n")
        self.w.git("add", "-A", cwd=other_repo)
        self.w.git("commit", "-qm", "other", cwd=other_repo)
        result = subprocess.run(
            [sys.executable, str(TIDY), "--project", str(other_repo),
             "--projects-root", str(self.w.projects), "--tmp-root", str(self.w.tmproot),
             "--clean-tmp", "--apply"],
            capture_output=True, text=True, env=self.w.env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.old_dir.exists())


class TestFastPath(HygieneCase):
    """The pass is a bounded, project-scoped read that cannot reach the whole host."""

    def test_all_is_refused(self):
        w = self.world()
        result = subprocess.run([sys.executable, str(TIDY), "--all", "--prune-caches"],
                                capture_output=True, text=True, env=w.env, timeout=120)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--all", result.stderr)

    def test_quick_and_hygiene_cannot_be_combined(self):
        w = self.world()
        result = subprocess.run([sys.executable, str(TIDY), "--quick", "--clean-tmp"],
                                capture_output=True, text=True, env=w.env, timeout=120)
        self.assertEqual(result.returncode, 2)

    def test_time_budget_must_be_at_least_one_second(self):
        w = self.world()
        result = subprocess.run([sys.executable, str(TIDY), "--prune-caches",
                                 "--time-budget", "0"],
                                capture_output=True, text=True, env=w.env, timeout=120)
        self.assertEqual(result.returncode, 2)

    def test_spent_budget_reports_instead_of_walking_on(self):
        module = load_tidy()
        budget = module.TimeBudget(1)
        time.sleep(1.1)
        self.assertTrue(budget.spent())
        self.assertIsNone(module.newest_shallow("/usr", depth=1, budget=budget)[0])

    def test_repeated_runs_remove_nothing_the_second_time(self):
        w = self.world()
        idle = w.worktree("wt-idle", "idle")
        w.build_output(idle)
        age(idle, 3 * DAY)
        first = w.tidy("--prune-caches", "--apply")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = w.tidy("--prune-caches", "--apply")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("PRUNE cache", second.stdout)
        self.assertIn("pruned 0", second.stdout)


if __name__ == "__main__":
    unittest.main()
