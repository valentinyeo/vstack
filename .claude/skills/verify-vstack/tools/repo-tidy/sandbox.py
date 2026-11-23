#!/usr/bin/env python3
"""Build and grade a throwaway git world for repo-tidy.

One temp dir holds a bare origin, one clone, worktrees in every state repo-tidy
must tell apart, and a fake gh that serves PR data from fixture.json and records
every write in gh-calls.log.

Used by .claude/skills/verify-vstack/tools/repo-tidy/run and by tests/test_repo_tidy.py, so
both prove the same thing.

Usage:
  sandbox.py build <root> [--scale N]
  sandbox.py grade <root> <run-dir>
  sandbox.py snapshot <root>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GITHUB_ORIGIN = "https://github.com/valentinyeo/sandbox.git"
SLUG = "valentinyeo/sandbox"
NOW = time.time()

GITCONFIG = """[user]
\tname = Sandbox
\temail = sandbox@example.com
[init]
\tdefaultBranch = main
[core]
\thooksPath = /dev/null
[advice]
\tdetachedHead = false
[safe]
\tdirectory = *
[url "{origin}"]
\tinsteadOf = {url}
"""

GH_SHIM = r'''#!/usr/bin/env python3
"""Fake gh for the repo-tidy sandbox. Serves fixture.json, logs every write."""
import json
import os
import sys

argv = sys.argv[1:]
fixture = json.load(open(os.environ["GH_FIXTURE"]))
log = os.environ["GH_CALL_LOG"]

if os.environ.get("GH_FAIL") == "1":
    sys.stderr.write("gh: HTTP 401: Bad credentials\n")
    sys.exit(1)


def die():
    sys.stderr.write("fake gh: unhandled call: %s\n" % " ".join(argv))
    sys.exit(2)


def value(flag):
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError):
        die()


if argv[:2] == ["pr", "list"]:
    slug = value("-R")
    state = value("--state")
    data = fixture.get(slug)
    if data is None:
        die()
    with open(log, "a") as handle:
        handle.write("PR_LIST -R %s --state %s\n" % (slug, state))
    delay = float(os.environ.get("GH_PR_DELAY", "0") or "0")
    if delay > 0:
        import time as _time
        _time.sleep(delay)
    if state == "all":
        rows = []
        for key in ("merged", "open", "closed"):
            rows.extend(data["prs"].get(key, []))
        print(json.dumps(rows))
    else:
        print(json.dumps(data["prs"].get(state, [])))
    sys.exit(0)

if argv and argv[0] == "api":
    patch = "-X" in argv
    words = []
    skip = False
    for word in argv[1:]:
        if skip:
            skip = False
            continue
        if word in ("-X", "-F", "--jq", "-f", "--method", "--input"):
            skip = True
            continue
        if word == "PATCH" or word.startswith("delete_branch_on_merge="):
            continue
        words.append(word)
    endpoint = words[0].strip('"') if words else ""
    parts = [part for part in endpoint.split("?")[0].split("/") if part]
    if parts and parts[0] == "repos":
        parts = parts[1:]
    slug = "/".join(parts[:2])
    data = fixture.get(slug)
    if data is None:
        die()
    if patch:
        with open(log, "a") as handle:
            handle.write("PATCH repos/%s delete_branch_on_merge=true\n" % slug)
        print("{}")
        sys.exit(0)
    if "branches" in parts:
        for name in data.get("protected", []):
            print(name)
        sys.exit(0)
    print("true" if data.get("delete_branch_on_merge", True) else "false")
    sys.exit(0)

die()
'''


def iso(days_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - days_ago * 86400))


def _run(cmd, cwd=None, env=None, check=True):
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env,
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError("%s failed: %s%s" % (" ".join(str(c) for c in cmd),
                                               proc.stdout, proc.stderr))
    return proc


class Sandbox:
    def __init__(self, root, scale=0, neighbour=False):
        self.root = Path(root).resolve()
        self.home = self.root / "home"
        self.projects = self.home / "projects"
        self.bin = self.root / "bin"
        self.origin = self.root / "origin.git"
        self.repo = self.projects / "sandbox"
        self.fixture_path = self.root / "fixture.json"
        self.call_log = self.root / "gh-calls.log"
        self.expect_path = self.root / "expect.json"
        self.scale = scale
        self.neighbour = neighbour

    # -- environment ---------------------------------------------------
    @property
    def env(self):
        env = dict(os.environ)
        env.update({
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GH_FIXTURE": str(self.fixture_path),
            "GH_CALL_LOG": str(self.call_log),
        })
        return env

    def drive_env(self, extra=None):
        env = self.env
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        if extra:
            env.update(extra)
        return env

    def git(self, args, cwd=None, check=True, date=None, extra=None):
        env = self.env
        if date:
            env = dict(env)
            env["GIT_AUTHOR_DATE"] = date
            env["GIT_COMMITTER_DATE"] = date
        if extra:
            env.update(extra)
        return _run(["git"] + list(args), cwd=cwd, env=env, check=check)

    # -- build ---------------------------------------------------------
    def build(self):
        for path in (self.home, self.projects, self.bin):
            path.mkdir(parents=True, exist_ok=True)
        (self.home / ".local/state").mkdir(parents=True, exist_ok=True)
        (self.home / ".gitconfig").write_text(
            GITCONFIG.format(origin=self.origin, url=GITHUB_ORIGIN))
        self.call_log.write_text("")
        self._write_shim()

        self.git(["init", "--bare", "-q", str(self.origin)])
        self.git(["--git-dir", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/main"])
        self.git(["clone", "-q", GITHUB_ORIGIN, str(self.repo)])
        self.git(["config", "user.name", "Sandbox"], cwd=self.repo)
        self.git(["config", "user.email", "sandbox@example.com"], cwd=self.repo)

        (self.repo / ".gitignore").write_text("dist/\n")
        (self.repo / "app.py").write_text("print('one')\n")
        self.git(["add", "-A"], cwd=self.repo)
        self.git(["commit", "-qm", "main one"], cwd=self.repo)
        (self.repo / "README.md").write_text("sandbox\n")
        self.git(["add", "-A"], cwd=self.repo)
        self.git(["commit", "-qm", "main two"], cwd=self.repo)
        self.git(["push", "-q", "origin", "HEAD:main"], cwd=self.repo)

        fixture = {SLUG: {"prs": {"merged": [], "open": [], "closed": []},
                          "delete_branch_on_merge": False,
                          "protected": ["main", "remote-protected"]}}
        prs = fixture[SLUG]["prs"]

        # Shipped and idle: every one of these must go.
        self.wt("merged-clean", "clean-merged", base="main")
        tip = self.commit_in("squash-clean", "squash-merged", "squash.txt", "squashed\n")
        self.git(["push", "-q", "origin", "squash-merged"], cwd=self.wt_path("squash-clean"))
        prs["merged"].append({"headRefName": "squash-merged", "headRefOid": tip,
                              "number": 11, "mergedAt": iso(1)})
        self.wt("ignored-clean", "ignored-merged", base="main")
        (self.wt_path("ignored-clean") / "dist").mkdir()
        (self.wt_path("ignored-clean") / "dist/app.js").write_text("build output\n")
        tip = self.commit_in("closed-stale", "closed-stale", "stale.txt", "stale\n")
        self.git(["push", "-q", "origin", "closed-stale"], cwd=self.wt_path("closed-stale"))
        prs["closed"].append({"headRefName": "closed-stale", "headRefOid": tip,
                              "number": 12, "mergedAt": None, "closedAt": iso(20)})

        # Held: each one trips a different gate.
        path = self.wt("wip", "wip-edit", base="main")
        (path / "app.py").write_text("print('edited, never committed')\n")
        path = self.wt("scratch", "scratch-branch", base="main")
        (path / "notes.txt").write_text("scratch note\n")
        self.wt("unpushed", "unpushed-branch", base="main")
        self.commit_in("unpushed", "unpushed-branch", "local.txt", "local only\n", push=False)
        tip = self.commit_in("open-pr", "open-pr-branch", "open.txt", "open\n")
        self.git(["push", "-q", "origin", "open-pr-branch"], cwd=self.wt_path("open-pr"))
        prs["open"].append({"headRefName": "open-pr-branch", "headRefOid": tip,
                            "number": 13, "mergedAt": None})
        tip = self.commit_in("squash-stale", "squash-stale", "stale-pr.txt", "second\n")
        self.git(["push", "-q", "origin", "squash-stale"], cwd=self.wt_path("squash-stale"))
        prs["merged"].append({"headRefName": "squash-stale", "headRefOid": self.rev("main"),
                              "number": 14, "mergedAt": iso(2)})
        tip = self.commit_in("closed-recent", "closed-recent", "recent.txt", "recent\n")
        self.git(["push", "-q", "origin", "closed-recent"], cwd=self.wt_path("closed-recent"))
        prs["closed"].append({"headRefName": "closed-recent", "headRefOid": tip,
                              "number": 15, "mergedAt": None, "closedAt": iso(3)})
        self.wt("in-use", "in-use-branch", base="main")
        self.wt("recent", "recent-branch", base="main")
        self.wt("lease", "lease-branch", base="main")
        (self.home / ".local/state/agent-lease.json").write_text(
            json.dumps({"holder": "other-session", "worktree": str(self.wt_path("lease"))}) + "\n")
        # Detached at a commit that lives on no remote ref.
        self.git(["-C", str(self.repo), "branch", "temp-detached", "main"])
        self.git(["-C", str(self.repo), "checkout", "-q", "temp-detached"])
        (self.repo / "detached.txt").write_text("detached\n")
        self.git(["add", "-A"], cwd=self.repo)
        self.git(["commit", "-qm", "detached only"], cwd=self.repo)
        detached_sha = self.rev("temp-detached")
        self.git(["-C", str(self.repo), "checkout", "-q", "main"])
        self.git(["-C", str(self.repo), "worktree", "add", "-q", "--detach",
                  str(self.wt_path("detached")), detached_sha])
        self.git(["-C", str(self.repo), "branch", "-q", "-D", "temp-detached"])
        # Outside the projects root: reported, never removed.
        (self.root / "outside").mkdir(exist_ok=True)
        self.git(["-C", str(self.repo), "worktree", "add", "-q", "-b", "outside-branch",
                  str(self.root / "outside/outside-tree"), "main"])

        # Local branches with no worktree.
        self.git(["-C", str(self.repo), "branch", "local-merged", "main"])
        tip = self.commit_in("local-squash-tmp", "local-squash", "squash-local.txt", "x\n")
        self.git(["push", "-q", "origin", "local-squash"], cwd=self.wt_path("local-squash-tmp"))
        self.drop("local-squash-tmp")
        prs["merged"].append({"headRefName": "local-squash", "headRefOid": tip,
                              "number": 16, "mergedAt": iso(1)})
        self.commit_in("local-unpushed-tmp", "local-unpushed", "u.txt", "u\n", push=False)
        self.drop("local-unpushed-tmp")
        tip = self.commit_in("local-closed-tmp", "local-closed-old", "c.txt", "c\n")
        self.git(["push", "-q", "origin", "local-closed-old"], cwd=self.wt_path("local-closed-tmp"))
        self.drop("local-closed-tmp")
        prs["closed"].append({"headRefName": "local-closed-old", "headRefOid": tip,
                              "number": 17, "mergedAt": None, "closedAt": iso(40)})
        tip = self.commit_in("local-open-tmp", "local-open-pr", "o.txt", "o\n")
        self.git(["push", "-q", "origin", "local-open-pr"], cwd=self.wt_path("local-open-tmp"))
        self.drop("local-open-tmp")
        prs["open"].append({"headRefName": "local-open-pr", "headRefOid": tip,
                            "number": 18, "mergedAt": None})

        # Remote branches with no local worktree.
        tip = self.commit_in("remote-merged-tmp", "remote-merged", "rm.txt", "rm\n")
        self.git(["push", "-q", "origin", "remote-merged"], cwd=self.wt_path("remote-merged-tmp"))
        self.drop("remote-merged-tmp")
        prs["merged"].append({"headRefName": "remote-merged", "headRefOid": tip,
                              "number": 19, "mergedAt": iso(1)})
        self.git(["-C", str(self.repo), "push", "-q", "origin", "main:remote-ancestor"])
        self.git(["-C", str(self.repo), "push", "-q", "origin", "main:remote-open"])
        prs["open"].append({"headRefName": "remote-open", "headRefOid": self.rev("main"),
                            "number": 20, "mergedAt": None})
        self.git(["-C", str(self.repo), "checkout", "-q", "-b", "remote-stale", "main"])
        (self.repo / "old.txt").write_text("old\n")
        self.git(["add", "-A"], cwd=self.repo)
        self.git(["commit", "-qm", "old"], cwd=self.repo, date=iso(100))
        self.git(["push", "-q", "origin", "remote-stale"], cwd=self.repo)
        self.git(["-C", str(self.repo), "checkout", "-q", "main"])
        self.git(["-C", str(self.repo), "branch", "-q", "-D", "remote-stale"])
        tip = self.commit_in("remote-protected-tmp", "remote-protected", "rp.txt", "rp\n")
        self.git(["push", "-q", "origin", "remote-protected"],
                 cwd=self.wt_path("remote-protected-tmp"))
        self.drop("remote-protected-tmp")
        prs["merged"].append({"headRefName": "remote-protected", "headRefOid": tip,
                              "number": 21, "mergedAt": iso(1)})

        if self.neighbour:
            self._build_neighbour()
        if self.scale:
            self._build_scale(self.scale)
        self.age_worktrees()
        os.utime(self.wt_path("recent") / "app.py", None)

        self.fixture_path.write_text(json.dumps(fixture, indent=2) + "\n")
        expect = self._expect()
        self.expect_path.write_text(json.dumps(expect, indent=2) + "\n")
        if self.scale:
            expect = self._expect(scale=True)
        return expect

    def age_worktrees(self, hours=3):
        """Backdate worktree files, so only the `recent` case looks freshly used."""
        old = time.time() - hours * 3600
        for path in self.worktree_dirs():
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
                for name in filenames:
                    try:
                        os.utime(os.path.join(dirpath, name), (old, old))
                    except OSError:
                        pass
            marker = Path(path) / ".git"
            if marker.is_file():
                os.utime(marker, (old, old))

    def worktree_dirs(self):
        out = self.git(["-C", str(self.repo), "worktree", "list", "--porcelain"]).stdout
        return [line[len("worktree "):] for line in out.splitlines()
                if line.startswith("worktree ")][1:]

    def _write_shim(self):
        shim = self.bin / "gh"
        shim.write_text(GH_SHIM)
        shim.chmod(0o755)

    def _build_neighbour(self):
        """A second repo under the projects root, with one shipped worktree."""
        origin = self.root / "origin2.git"
        neighbour = self.projects / "other"
        self.git(["init", "--bare", "-q", str(origin)])
        self.git(["--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"])
        self.git(["clone", "-q", str(origin), str(neighbour)])
        self.git(["config", "user.name", "Sandbox"], cwd=neighbour)
        self.git(["config", "user.email", "sandbox@example.com"], cwd=neighbour)
        (neighbour / "f.txt").write_text("other\n")
        self.git(["add", "-A"], cwd=neighbour)
        self.git(["commit", "-qm", "one"], cwd=neighbour)
        self.git(["push", "-q", "origin", "HEAD:main"], cwd=neighbour)
        self.git(["-C", str(neighbour), "worktree", "add", "-q", "-b", "other-done",
                  str(self.projects / "other-done"), "main"])

    def _build_scale(self, count):
        """Many worktrees and branches, for the speed floor."""
        sha = self.rev("main")
        paths = [self.projects / ("bulk-%04d" % i) for i in range(count)]

        def add(path):
            subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q",
                            "--detach", "--no-checkout", str(path), sha],
                           env=self.env, capture_output=True, text=True)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add, paths))
        branches = max(count, 1300)
        lines = "".join("create refs/heads/bulk-%04d %s\n" % (i, sha) for i in range(branches))
        subprocess.run(["git", "-C", str(self.repo), "update-ref", "--stdin"],
                       input=lines, env=self.env, capture_output=True, text=True, check=True)

    # -- small helpers -------------------------------------------------
    def rev(self, ref):
        return self.git(["-C", str(self.repo), "rev-parse", ref]).stdout.strip()

    def wt_path(self, name):
        return self.projects / ("sandbox-" + name)

    def wt(self, name, branch, base="main"):
        path = self.wt_path(name)
        self.git(["-C", str(self.repo), "worktree", "add", "-q", "-b", branch, str(path), base])
        return path

    def commit_in(self, name, branch, filename, content, push=True):
        path = self.wt_path(name)
        if not path.exists():
            self.wt(name, branch)
        (path / filename).write_text(content)
        self.git(["add", "-A"], cwd=path)
        self.git(["commit", "-qm", "work on %s" % branch], cwd=path)
        tip = self.git(["rev-parse", "HEAD"], cwd=path).stdout.strip()
        if push:
            self.git(["push", "-q", "origin", branch], cwd=path)
        return tip

    def drop(self, name):
        self.git(["-C", str(self.repo), "worktree", "remove", "--force", str(self.wt_path(name))])

    # -- expectations --------------------------------------------------
    def _expect(self, scale=False):
        expect = {
            "slug": SLUG,
            "gone_worktrees": ["merged-clean", "squash-clean", "ignored-clean", "closed-stale"],
            "kept_worktrees": ["wip", "scratch", "unpushed", "open-pr", "squash-stale",
                               "closed-recent", "in-use", "recent", "lease", "detached"],
            "outside_worktrees": ["outside/outside-tree"],
            "deleted_branches": ["clean-merged", "squash-merged", "ignored-merged",
                                 "local-merged", "local-squash", "local-closed-old",
                                 "remote-merged", "remote-protected"],
            "kept_branches": ["main", "closed-stale", "wip-edit", "scratch-branch",
                              "unpushed-branch", "open-pr-branch", "squash-stale",
                              "closed-recent", "in-use-branch", "recent-branch",
                              "lease-branch", "outside-branch", "local-unpushed",
                              "local-open-pr"],
            "deleted_remote": ["remote-merged", "remote-ancestor", "squash-merged",
                               "local-squash"],
            "kept_remote": ["main", "closed-stale", "open-pr-branch", "squash-stale",
                            "closed-recent", "local-closed-old", "local-open-pr",
                            "remote-open", "remote-stale", "remote-protected"],
            "stale_remote": ["remote-stale"],
            "setting_change": True,
            "commits": [],
        }
        if scale:
            expect["gone_worktrees"] = []
            expect["kept_worktrees"] = []
            expect["deleted_branches"] = []
            expect["kept_branches"] = []
            expect["deleted_remote"] = []
            expect["kept_remote"] = []
            expect["stale_remote"] = []
            expect["setting_change"] = False
        commits = set()
        for ref in self._refs(self.repo) | self._refs(self.origin, bare=True):
            commits.add(ref)
        for entry in self.worktree_heads():
            commits.add(entry)
        expect["commits"] = sorted(commits)
        held = set()
        for name in expect["kept_worktrees"]:
            head = self.git(["rev-parse", "HEAD"], cwd=self.wt_path(name),
                            check=False).stdout.strip()
            if head:
                held.add(head)
        for name in expect["kept_branches"]:
            sha = self.git(["-C", str(self.repo), "rev-parse", "refs/heads/" + name],
                           check=False).stdout.strip()
            if sha:
                held.add(sha)
        for name in expect["kept_remote"]:
            sha = self.git(["-C", str(self.repo), "rev-parse", "origin/" + name],
                           check=False).stdout.strip()
            if sha:
                held.add(sha)
        expect["held_commits"] = sorted(held)
        return expect

    def _refs(self, repo, bare=False):
        args = ["--git-dir", str(repo)] if bare else ["-C", str(repo)]
        out = self.git(args + ["for-each-ref", "--format=%(objectname)"]).stdout
        return set(out.split())

    def worktree_heads(self):
        out = self.git(["-C", str(self.repo), "worktree", "list", "--porcelain"]).stdout
        return [line[5:] for line in out.splitlines() if line.startswith("HEAD ")]


# -- snapshot and grading ------------------------------------------------

def snapshot(root) -> dict:
    sb = type("Paths", (), {})()
    root = Path(root).resolve()
    sb.home = root / "home"
    sb.projects = sb.home / "projects"
    sb.repo = sb.projects / "sandbox"
    sb.origin = root / "origin.git"
    sb.call_log = root / "gh-calls.log"

    def git(args):
        return _run(["git"] + args, env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1"),
                    check=False)

    out = git(["-C", str(sb.repo), "worktree", "list", "--porcelain"]).stdout
    worktrees = {}
    current = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            current = line[9:]
            worktrees[current] = None
        elif line.startswith("branch ") and current:
            worktrees[current] = line[7:].replace("refs/heads/", "", 1)
        elif line == "detached" and current:
            worktrees[current] = None
    branches = set(git(["-C", str(sb.repo), "for-each-ref", "--format=%(refname:short)",
                        "refs/heads"]).stdout.split())
    remote = set(git(["--git-dir", str(sb.origin), "for-each-ref",
                      "--format=%(refname:short)", "refs/heads"]).stdout.split())
    alive = set(git(["-C", str(sb.repo), "rev-list", "--all"]).stdout.split())
    calls = sb.call_log.read_text().splitlines() if sb.call_log.exists() else []
    projects = sb.home / "projects"
    names = {}
    for path in worktrees:
        resolved = Path(path).resolve()
        try:
            key = resolved.relative_to(projects.resolve()).as_posix()
        except ValueError:
            try:
                key = resolved.relative_to(root).as_posix()
            except ValueError:
                key = str(resolved)
        if key.startswith("sandbox-"):
            key = key[len("sandbox-"):]
        names[key] = worktrees[path]
    return {
        "worktrees": {str(Path(p).resolve()): b for p, b in worktrees.items()},
        "names": names,
        "branches": sorted(branches),
        "remote": sorted(remote),
        "alive_commits": sorted(alive),
        "gh_calls": calls,
        "dirs": sorted(str(p.name) for p in sb.projects.glob("sandbox-*") if p.is_dir()),
    }


def grade(root, run_dir=None) -> tuple:
    root = Path(root).resolve()
    expect = json.loads((root / "expect.json").read_text())
    state = snapshot(root)
    lines = []
    ok = True

    def record(name, passed, detail):
        nonlocal ok
        lines.append(("PASS " if passed else "FAIL ") + name + ": " + detail)
        if not passed:
            ok = False

    paths = {str(Path(p).resolve()): b for p, b in state["worktrees"].items()}
    names = state["names"]
    main = str((root / "home/projects/sandbox").resolve())

    leaked = [n for n in expect["gone_worktrees"] if n in names]
    still = [n for n in expect["kept_worktrees"] if n not in names]
    leftovers = [n for n in expect["gone_worktrees"]
                 if (root / "home/projects" / ("sandbox-" + n)).exists()]
    record("worktrees", not leaked and not still and not leftovers,
           "%d shipped removed, %d held%s%s" % (
               len(expect["gone_worktrees"]) - len(leaked),
               len(expect["kept_worktrees"]) - len(still),
               "" if not leaked else ", leaked: " + ", ".join(leaked),
               "" if not still else ", lost held: " + ", ".join(still)))
    record("outside", all(str((root / n).resolve()) in paths
                          for n in expect["outside_worktrees"]),
           "worktree outside the projects root untouched")

    branches = set(state["branches"])
    lost = [b for b in expect["deleted_branches"] if b in branches]
    gone = [b for b in expect["kept_branches"] if b not in branches]
    record("branches", not lost and not gone,
           "%d deleted, %d kept%s%s" % (
               len(expect["deleted_branches"]) - len(lost),
               len(expect["kept_branches"]) - len(gone),
               "" if not lost else ", not deleted: " + ", ".join(lost),
               "" if not gone else ", lost: " + ", ".join(gone)))

    remote = set(state["remote"])
    lost_remote = [b for b in expect["deleted_remote"] if b in remote]
    gone_remote = [b for b in expect["kept_remote"] if b not in remote]
    record("remote-branches", not lost_remote and not gone_remote,
           "%d deleted, %d kept, %d stale left alone%s%s" % (
               len(expect["deleted_remote"]) - len(lost_remote),
               len(expect["kept_remote"]) - len(gone_remote),
               len(expect["stale_remote"]),
               "" if not lost_remote else ", not deleted: " + ", ".join(lost_remote),
               "" if not gone_remote else ", lost: " + ", ".join(gone_remote)))

    alive = set(state["alive_commits"])
    missing = [c for c in expect.get("held_commits", []) if c not in alive]
    unreadable = [c for c in expect["commits"]
                  if _run(["git", "-C", str(root / "home/projects/sandbox"), "cat-file",
                           "-e", c + "^{commit}"], env=os.environ, check=False).returncode != 0]
    record("commits", not missing and not unreadable,
           "%d held commits still reachable, every commit still in the object db"
           % len(expect.get("held_commits", []))
           if not missing and not unreadable
           else "lost: %s missing objects: %s" % (
               ", ".join(missing[:3]), ", ".join(unreadable[:3])))

    patches = [c for c in state["gh_calls"] if c.startswith("PATCH ")]
    if expect["setting_change"]:
        record("github-setting", len(patches) == 1,
               "one PATCH for delete_branch_on_merge" if len(patches) == 1
               else "expected 1 PATCH, saw %d" % len(patches))
    else:
        record("github-setting", not patches, "no setting write expected")

    record("main-worktree", main in paths, "main checkout untouched")

    if run_dir:
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(p.name for p in run_dir.iterdir())
        record("evidence", "apply.json" in files and "dry.out" in files,
               "run dir holds %s" % ", ".join(files[:8]))
        run_dir.joinpath("verdict.txt").write_text("\n".join(lines) + "\n")
        verdict = {"verdict": "PASS" if ok else "FAIL",
                   "checks": [{"line": line} for line in lines],
                   "snapshot": state}
        run_dir.joinpath("after.json").write_text(json.dumps(state, indent=2) + "\n")
        run_dir.joinpath("verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print("\n".join(lines))
    print("VERDICT " + ("PASS" if ok else "FAIL"))
    return (0 if ok else 1), lines


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    command = argv[1]
    if command == "build":
        scale = 0
        args = argv[2:]
        if "--scale" in args:
            index = args.index("--scale")
            scale = int(args[index + 1])
            del args[index:index + 2]
        root = Path(args[0])
        root.mkdir(parents=True, exist_ok=True)
        expect = Sandbox(root, scale=scale, neighbour="--neighbour" in args).build()
        print(json.dumps(expect, indent=2))
        return 0
    if command == "snapshot":
        print(json.dumps(snapshot(argv[2]), indent=2))
        return 0
    if command == "grade":
        return grade(argv[2], argv[3] if len(argv) > 3 else None)[0]
    sys.stderr.write("sandbox.py: unknown command %s\n" % command)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
