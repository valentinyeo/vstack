"""Tests for skills/repo-tidy and its proof skill.

Every test builds the throwaway world from
.claude/skills/verify-vstack/tools/repo-tidy/sandbox.py: a bare origin, one clone, worktrees
in every state repo-tidy must tell apart, and a fake gh that serves fixture
PR data and records every write.

Run: python3 -m unittest discover -s tests -p 'test_*.py'
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIDY = ROOT / "skills/repo-tidy/repo-tidy"
VERIFY = ROOT / ".claude/skills/verify-vstack/tools/repo-tidy"
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
        self.assertIn("remote deleted 5", line[0], output)  # copy-merged is the slices fixture's
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


class TestSlices(SandboxCase):
    """A project's other folders: its old clones and left behind worktree folders.

    A chat's copy belongs to the project, not to the chat that left it, so a chat
    starting on the project clears what earlier chats missed.
    """

    @classmethod
    def build(cls):
        world, expect = super().build()
        cls.dry = tidy(world, "--all")
        cls.apply = tidy(world, "--all", "--apply")
        return world, expect

    def names(self):
        return set(sandbox.snapshot(self.world.root)["dirs"])

    def test_shipped_clones_are_removed(self):
        self.assertEqual(self.apply.returncode, 0, self.apply.stderr)
        names = self.names()
        self.assertNotIn("sandbox-main-copy", names, self.apply.stdout)
        self.assertNotIn("sandbox-merged-copy", names, self.apply.stdout)

    def test_dirty_unpushed_leased_and_grouped_clones_stay(self):
        names = self.names()
        for name in ("sandbox-dirty-copy", "sandbox-unpushed-copy",
                     "sandbox-leased-copy", "sandbox-trees"):
            self.assertIn(name, names, self.apply.stdout)

    def test_another_projects_copy_is_untouched(self):
        self.assertIn("sandbox-neighbour-copy", self.names(), self.apply.stdout)

    def test_a_worktree_folder_git_no_longer_registers_stays(self):
        self.assertIn("sandbox-orphan-tree", self.names(), self.apply.stdout)

    def test_the_main_checkout_is_never_a_slice(self):
        main = str((self.world.projects / "sandbox").resolve())
        self.assertTrue((self.world.projects / "sandbox").is_dir(), self.apply.stdout)
        removed = [line for line in self.apply.stdout.splitlines()
                   if line.startswith("REMOVE slice ") and (main + " (") in line]
        self.assertEqual(removed, [], self.apply.stdout)

    def test_each_held_folder_gives_its_reason(self):
        self.assertIn("HOLD slice", self.apply.stdout)
        # Two shipped clones go; the dirty, unpushed, leased, orphaned and grouped
        # ones stay. The neighbour copy is another project's, so it is not counted.
        self.assertIn("sibling folders removed 2 held 5", self.apply.stdout)

    def test_dry_run_names_the_same_folders_and_removes_none(self):
        self.assertEqual(self.dry.returncode, 0, self.dry.stderr)
        for name in ("sandbox-main-copy", "sandbox-merged-copy"):
            line = [row for row in self.dry.stdout.splitlines()
                    if row.startswith("REMOVE slice ") and name in row]
            self.assertTrue(line, self.dry.stdout)
        started = set(re.findall(r"^REMOVE slice (\S+)", self.dry.stdout, re.M))
        applied = set(re.findall(r"^REMOVE slice (\S+)", self.apply.stdout, re.M))
        self.assertEqual(started, applied, self.dry.stdout)
        self.assertTrue(started, self.dry.stdout)

    def test_mine_never_reaches_a_sibling_folder(self):
        result = tidy(self.world, "--apply", "--mine", str(self.world.repo),
                      "--branch", "clean-merged")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("slice", result.stdout)


class TestProjectScope(SandboxCase):
    """An agent starting on a project cleans that project, never another one."""

    neighbour = True

    def test_project_cleans_only_its_own_folders(self):
        result = tidy(self.world, "--apply", "--project", str(self.world.repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sandbox:", result.stdout)
        self.assertNotIn("other:", result.stdout)
        self.assertTrue((self.world.projects / "other-done").exists(), result.stdout)
        self.assertFalse((self.world.projects / "sandbox-main-copy").exists(), result.stdout)

    def test_project_refuses_a_path_outside_a_repo(self):
        outside = self.world.root / "not-a-repo"
        outside.mkdir(exist_ok=True)
        result = tidy(self.world, "--project", str(outside))
        self.assertEqual(result.returncode, 2)
        self.assertIn("not in a git repo", result.stderr)

    def test_project_cannot_be_combined_with_all(self):
        result = tidy(self.world, "--project", str(self.world.repo), "--all")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--project", result.stderr)


class TestQuick(SandboxCase):
    """drain-check's own read: local git only, no gh, no fetch, one line per item."""

    def test_owed_folder_is_one_line_and_gh_is_never_called(self):
        before = sandbox.snapshot(self.world.root)["gh_calls"]
        result = tidy(self.world, "--quick", "--project", str(self.world.repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TIDY ", result.stdout)
        self.assertIn("sandbox-merged-clean", result.stdout)
        self.assertEqual(before, sandbox.snapshot(self.world.root)["gh_calls"])

    def test_quick_removes_nothing(self):
        before = sandbox.snapshot(self.world.root)
        result = tidy(self.world, "--quick", "--project", str(self.world.repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        after = sandbox.snapshot(self.world.root)
        self.assertEqual(before["worktrees"], after["worktrees"])
        self.assertEqual(before["dirs"], after["dirs"])

    def test_quick_never_removes_anything(self):
        result = tidy(self.world, "--quick", "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--quick", result.stderr)


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

    def test_dry_run_prints_the_setting_it_would_change(self):
        """features/github-setting.md: on a dry run it prints SET, writes nothing.

        The fitting item are the notes, but the SET line is the user-visible part.
        """
        result = tidy(self.world, "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SET setting valentinyeo/sandbox (delete_branch_on_merge=true)",
                      result.stdout)
        calls = sandbox.snapshot(self.world.root)["gh_calls"]
        self.assertFalse([c for c in calls if c.startswith("PATCH ")], calls)


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

    def test_mine_mode_requires_a_branch(self):
        result = tidy(self.world, "--apply", "--mine", str(self.world.repo))
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("--branch", result.stderr)

    def test_mine_mode_touches_only_named_branch(self):
        result = tidy(self.world, "--apply", "--mine", str(self.world.repo),
                      "--branch", "clean-merged")
        self.assertFalse(self.world.wt_path("merged-clean").exists(), result.stdout)
        self.assertTrue(self.world.wt_path("squash-clean").exists(), result.stdout)
        after = sandbox.snapshot(self.world.root)
        self.assertIn("squash-merged", after["branches"])
        self.assertIn("squash-merged", after["remote"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("other-done", str(list((self.world.projects).glob("other-done"))))
        self.assertTrue((self.world.projects / "other-done").exists(), result.stdout)
        self.assertIn("sandbox:", result.stdout)
        self.assertNotIn("other:", result.stdout)

    def test_mine_keeps_dirty_worktree_and_its_local_branch(self):
        result = tidy(self.world, "--apply", "--mine", str(self.world.repo),
                      "--branch", "wip-edit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.world.wt_path("wip").exists())
        self.assertIn("wip", result.stdout)
        self.assertIn("wip-edit", sandbox.snapshot(self.world.root)["branches"])

    def test_mine_removes_only_its_missing_registration(self):
        own = self.world.projects / "mine-missing"
        sibling = self.world.projects / "sibling-missing"
        for path in (own, sibling):
            self.world.git(["worktree", "add", "-q", "-b", path.name, str(path), "main"], cwd=self.world.repo)
            shutil.rmtree(path)
        result = tidy(self.world, "--apply", "--mine", str(self.world.repo),
                      "--branch", own.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        registered = self.world.git(["worktree", "list", "--porcelain"], cwd=self.world.repo).stdout
        self.assertNotIn(str(own), registered)
        self.assertIn(str(sibling), registered)
        self.assertNotIn(own.name, sandbox.snapshot(self.world.root)["branches"])
        self.assertIn(sibling.name, sandbox.snapshot(self.world.root)["branches"])

    def test_mine_does_not_override_a_locked_missing_registration(self):
        own = self.world.projects / "mine-locked-missing"
        self.world.git(["worktree", "add", "-q", "-b", own.name, str(own), "main"], cwd=self.world.repo)
        self.world.git(["worktree", "lock", str(own)], cwd=self.world.repo)
        shutil.rmtree(own)
        result = tidy(self.world, "--apply", "--mine", str(self.world.repo),
                      "--branch", own.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(own), self.world.git(["worktree", "list", "--porcelain"], cwd=self.world.repo).stdout)
        self.assertIn(own.name, sandbox.snapshot(self.world.root)["branches"])

    def test_branch_without_mine_is_rejected(self):
        result = tidy(self.world, "--apply", "--all", "--branch", "clean-merged")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("--mine", result.stderr)

    def test_a_worktree_path_is_a_repo(self):
        result = tidy(self.world, str(self.world.wt_path("wip")))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("not a repo", result.stdout)
        self.assertIn("sandbox:", result.stdout)

    def test_mine_outside_a_repo_does_nothing(self):
        outside = self.world.root / "not-a-repo"
        outside.mkdir()
        result = tidy(self.world, "--apply", "--mine", str(outside), "--branch", "mine")
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


class TestGhPrListOnce(SandboxCase):
    def test_one_pr_list_call_per_repo(self):
        result = tidy(self.world, "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = sandbox.snapshot(self.world.root)["gh_calls"]
        lists = [c for c in calls if c.startswith("PR_LIST")]
        self.assertEqual(lists, ["PR_LIST -R valentinyeo/sandbox --state all"], lists)


class TestRepoTimeout(SandboxCase):
    def test_per_repo_cap_skips_hung_repo(self):
        result = tidy(self.world, "--all", "--repo-timeout", "1",
                      extra_env={"GH_PR_DELAY": "5"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("exceeded 1s per-repo cap", result.stdout)


def newest_log(result):
    """The run log repo-tidy names on stdout, parsed."""
    match = re.search(r"^log: (.+)$", result.stdout, re.M)
    assert match, result.stdout
    return json.loads(Path(match.group(1)).read_text())


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


VPS_STATE_STUB = """#!/bin/sh
echo "$*" >> "{log}"
exit "${{VPS_STATE_EXIT:-0}}"
"""


class TestJobs(SandboxCase):
    """Twelve repos at once is what overloaded this shared server."""

    # Two repos, so the sweep size is the number under test, not the repo count.
    neighbour = True

    @classmethod
    def build(cls):
        world, expect = super().build()
        cls.write_stub(world)
        return world, expect

    @staticmethod
    def write_stub(world):
        stub = world.home / ".local/bin/vps-state"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(VPS_STATE_STUB.format(log=world.root / "vps-state-calls.log"))
        stub.chmod(0o755)

    def probe_calls(self):
        log = self.world.root / "vps-state-calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def run_and_log(self, *args, probe_exit=None):
        (self.world.root / "vps-state-calls.log").write_text("")
        env = {} if probe_exit is None else {"VPS_STATE_EXIT": str(probe_exit)}
        result = tidy(self.world, *args, extra_env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result, newest_log(result)

    def test_default_is_four_jobs_and_the_probe_runs_once(self):
        result, payload = self.run_and_log("--all")
        self.assertEqual(payload["jobs"], 4, result.stdout)
        self.assertEqual(self.probe_calls(), ["--can-launch worker --no-write"])

    def test_hold_drops_to_one_job(self):
        result, payload = self.run_and_log("--all", probe_exit=2)
        self.assertEqual(payload["jobs"], 1, result.stdout)
        self.assertIn("jobs: 1", result.stdout)

    def test_careful_drops_to_two_jobs(self):
        result, payload = self.run_and_log("--all", probe_exit=1)
        self.assertEqual(payload["jobs"], 2, result.stdout)

    def test_missing_probe_means_one_job(self):
        stub = self.world.home / ".local/bin/vps-state"
        stub.unlink()
        self.addCleanup(self.write_stub, self.world)
        result, payload = self.run_and_log("--all")
        self.assertEqual(payload["jobs"], 1, result.stdout)

    def test_jobs_flag_sets_the_number(self):
        result, payload = self.run_and_log("--all", "--jobs", "3")
        self.assertEqual(payload["jobs"], 3, result.stdout)

    def test_jobs_flag_refuses_out_of_range(self):
        for value in ("0", "9", "-1"):
            result = tidy(self.world, "--all", "--jobs", value)
            self.assertNotEqual(result.returncode, 0, value)
            self.assertIn("--jobs", result.stderr)


class TestChildProcesses(unittest.TestCase):
    """A hung git must die at the cap, and every child must run niced."""

    GIT_SHIM = """#!/bin/sh
echo "pid $$" >> "$FAKE_GIT_LOG"
echo "nice $(ps -o ni= -p $$ | tr -d ' ')" >> "$FAKE_GIT_LOG"
sleep 300 &
echo "pid $!" >> "$FAKE_GIT_LOG"
wait
"""

    def build(self):
        root = Path(tempfile.mkdtemp(prefix="repo-tidy-child-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        home = root / "home"
        repo = home / "projects/hung"
        repo.mkdir(parents=True)
        (home / ".gitconfig").write_text(
            "[user]\n\tname = t\n\temail = t@example.com\n[init]\n\tdefaultBranch = main\n")
        env = dict(os.environ, HOME=str(home), GIT_CONFIG_NOSYSTEM="1",
                   GIT_CONFIG_GLOBAL=str(home / ".gitconfig"))
        for args in (["init", "-q", str(repo)],
                     ["-C", str(repo), "add", "f"],
                     ["-C", str(repo), "commit", "-qm", "init"]):
            if args[0] == "init":
                (repo / "f").write_text("x\n")
            subprocess.run(["git"] + args, check=True, env=env)
        fake = root / "fakebin"
        fake.mkdir()
        (fake / "git").write_text(self.GIT_SHIM)
        (fake / "git").chmod(0o755)
        log = root / "fake-git.log"
        env.update({"PATH": str(fake) + os.pathsep + env["PATH"],
                    "FAKE_GIT_LOG": str(log)})
        return root, env, log

    def test_hung_git_dies_at_the_repo_cap_and_runs_niced(self):
        root, env, log = self.build()
        started = time.time()
        result = subprocess.run([sys.executable, str(TIDY), "--all", "--repo-timeout", "2"],
                                capture_output=True, text=True, env=env, timeout=120)
        elapsed = time.time() - started
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("exceeded 2s per-repo cap", result.stdout)
        self.assertLess(elapsed, 30, "the run waited %.1fs on a child that sleeps 300s" % elapsed)
        rows = [line.split(" ", 1) for line in log.read_text().splitlines() if line.strip()]
        self.assertTrue(rows, "the fake git never ran")
        niceness = [int(value) for key, value in rows if key == "nice"]
        self.assertTrue(niceness)
        self.assertGreaterEqual(min(niceness), 10, "children of repo-tidy are not niced")
        pids = [int(value) for key, value in rows if key == "pid"]
        self.assertTrue(pids)
        for _ in range(200):
            if not any(pid_alive(pid) for pid in pids):
                break
            time.sleep(0.05)
        self.assertEqual([pid for pid in pids if pid_alive(pid)], [],
                         "a child of the capped repo outlived the run")


class TestStreamingManyRepos(unittest.TestCase):
    """A multi-repo dry run prints a summary before the sweep finishes."""

    def test_first_summary_while_still_running(self):
        root = Path(tempfile.mkdtemp(prefix="repo-tidy-stream-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        home = root / "home"
        projects = home / "projects"
        projects.mkdir(parents=True)
        for index in range(20):
            repo = projects / ("stream-%02d" % index)
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"],
                           check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
            (repo / "f").write_text("x\n")
            subprocess.run(["git", "-C", str(repo), "add", "f"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
        env = dict(os.environ, HOME=str(home))
        proc = subprocess.Popen(
            [sys.executable, "-u", str(TIDY), "--all", "--projects-root", str(projects)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, bufsize=1)
        self.addCleanup(proc.kill)
        saw = False
        for line in proc.stdout:
            if re.search(r": worktrees ", line):
                saw = True
                self.assertIsNone(proc.poll(),
                                  "sweep ended before the first summary (no streaming)")
                break
        self.assertTrue(saw, "never saw a per-repo summary line")
        proc.wait(timeout=120)


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
