#!/usr/bin/env python3
"""PreToolUse guard: `gh pr create` cannot add a verification gate pstack does not ask for.

The branch must not add an EXTRA line to pstack-diff. It reads only the extras that
are new against the PR base, so old extras do not block an unrelated pull request.
It runs only when the branch diff touches .github/workflows or a verify skill.

pstack-new-gates.py --self-test
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CREATE = re.compile(r"(?:^|[\s;&|(])(?:\S*/)?gh\s+pr\s+create\b")
WATCHED = re.compile(r"^(?:\.github/workflows/|\.claude/skills/verify-|\.cursor/skills/verify-)")
TOOL = Path("skills/pstack-diff/pstack-diff")
INSTALLED = Path.home() / ".claude/skills/pstack-diff/pstack-diff"
BASE_ENV = "PSTACK_GATE_BASE"
BASE_FLAG = re.compile(r"(?:^|\s)(?:--base|-B)(?:=|\s+)(\S+)")
MESSAGE = (
    "pstack-diff: this PR adds a verification gate pstack does not ask for.\n"
    "{lines}\n"
    "Remove it, or list it in the repo's house file with the pstack sentence it follows."
)


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def commit(root, message):
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=test",
         "-c", "user.email=test@example.invalid", "commit", "-qm", message],
        check=True,
        capture_output=True,
    )


def repo_root(cwd):
    try:
        return Path(git(cwd, "rev-parse", "--show-toplevel"))
    except (subprocess.CalledProcessError, OSError):
        return None


def base_ref(root, cmd):
    override = os.environ.get(BASE_ENV)
    if override:
        return override
    candidates = []
    flag = BASE_FLAG.search(cmd)
    if flag:
        named = flag.group(1).strip("'\"")
        candidates.append(named if named.startswith(("origin/", "refs/")) else f"origin/{named}")
        candidates.append(named)
    try:
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    except (subprocess.CalledProcessError, OSError):
        branch, upstream = "", ""
    if upstream and upstream.rsplit("/", 1)[-1] != branch:
        candidates.append(upstream)
    try:
        head = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    except (subprocess.CalledProcessError, OSError):
        head = ""
    if head:
        candidates.append(head)
    candidates += ["origin/main", "main", "origin/master", "master"]
    for candidate in candidates:
        try:
            return git(root, "merge-base", "HEAD", candidate)
        except (subprocess.CalledProcessError, OSError):
            continue
    return None


def changed_files(root, base):
    try:
        output = git(root, "diff", "--name-only", f"{base}...HEAD")
    except (subprocess.CalledProcessError, OSError):
        return []
    return [line for line in output.splitlines() if line.strip()]


def diff_tool(root):
    here = Path(__file__).resolve().parents[1] / TOOL
    for candidate in (root / TOOL, here, INSTALLED):
        if candidate.is_file():
            return candidate
    return None


def verdict(cmd, cwd):
    """Return the block message, or None to let the command run."""
    if not CREATE.search(cmd):
        return None
    root = repo_root(cwd)
    if root is None:
        return None
    base = base_ref(root, cmd)
    if base is None:
        return None
    if not any(WATCHED.match(path) for path in changed_files(root, base)):
        return None
    tool = diff_tool(root)
    if tool is None:
        return None
    result = subprocess.run(
        [sys.executable, str(tool), "--base", base, str(root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 1:
        return None
    extras = [line for line in result.stdout.splitlines() if line.startswith("EXTRA ")]
    if not extras:
        return None
    return MESSAGE.format(lines="\n".join(extras))


def self_test():
    repo = Path(__file__).resolve().parents[1]
    fixture = repo / "tests/fixtures/pstack-diff"
    os.environ.setdefault("PSTACK_DIFF_PSTACK", str(fixture / "pstack"))
    os.environ["PSTACK_GATE_BASE"] = "HEAD~1"
    clean = fixture / "clean"

    def make(commit_changes):
        holder = tempfile.TemporaryDirectory(prefix="pstack-new-gates-")
        root = Path(holder.name)
        subprocess.run(["cp", "-R", f"{clean}/.", str(root)], check=True)
        git(root, "init", "-q")
        git(root, "add", "-A")
        commit(root, "base")
        for path, text in commit_changes:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        git(root, "add", "-A")
        commit(root, "head")
        return holder, root

    def append_workflow(job):
        text = (clean / ".github/workflows/ci.yml").read_text()
        return text.rstrip("\n") + "\n" + job

    planted = append_workflow(
        "  scorecard:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python3 scripts/scorecard.py\n"
    )
    holder, root = make([(".github/workflows/ci.yml", planted)])
    try:
        why = verdict("gh pr create --title t --body b", root)
        assert why and "EXTRA workflow" in why, "a new scorecard gate is blocked"
    finally:
        holder.cleanup()

    # The same gate already in the base does not block a later workflow edit.
    holder = tempfile.TemporaryDirectory(prefix="pstack-new-gates-")
    root = Path(holder.name)
    try:
        subprocess.run(["cp", "-R", f"{clean}/.", str(root)], check=True)
        (root / ".github/workflows/ci.yml").write_text(planted)
        git(root, "init", "-q")
        git(root, "add", "-A")
        commit(root, "base")
        workflow = root / ".github/workflows/ci.yml"
        workflow.write_text(workflow.read_text().replace("name: ci", "name: ci # touched"))
        git(root, "add", "-A")
        commit(root, "head")
        assert verdict("gh pr create --title t --body b", root) is None, "an old gate does not block"
    finally:
        holder.cleanup()

    # A repo house file may allow its own gate.
    budget = append_workflow(
        "  budget:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python3 scripts/budget.py\n"
    )
    holder, root = make([
        (".github/workflows/ci.yml", budget),
        (".pstack-house.txt", ".github/workflows/ci.yml:budget the repo needs it\n"),
    ])
    try:
        assert verdict("gh pr create --title t --body b", root) is None, "a house gate is allowed"
    finally:
        holder.cleanup()

    assert verdict("git status", repo) is None, "other commands pass"
    assert verdict("gh pr view 1", repo) is None, "other gh commands pass"
    print("pstack-new-gates self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    cwd = data.get("cwd") or os.getcwd()
    why = verdict((data.get("tool_input") or {}).get("command") or "", cwd)
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
