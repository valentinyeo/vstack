"""A change must not pick its own checker (SOFT-2729).

Every verifier workflow runs scripts/pick-verifier-model from a checkout of the PR's base sha, never from the PR head.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
PICKER = ROOT / "scripts/pick-verifier-model"
DEEPSEEK_AUTHOR = "## Why\nx\n\nAuthor model: deepseek/deepseek-v4.1-flash\n"


def checkout_blocks(text):
    """(ref line, path line) of every actions/checkout step."""
    blocks = re.split(r"(?m)^\s*- uses: actions/checkout@", text)[1:]
    for block in blocks:
        step = re.split(r"(?m)^\s*- ", block)[0]
        ref = re.search(r"(?m)^\s*ref: (.*)$", step)
        path = re.search(r"(?m)^\s*path: (\S+)", step)
        yield (ref.group(1) if ref else "", path.group(1) if path else "")


def git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@users.noreply.github.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@users.noreply.github.com"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


class PickerComesFromBaseTests(unittest.TestCase):
    def test_every_workflow_runs_the_picker_from_a_base_checkout(self):
        seen = 0
        for workflow in WORKFLOWS:
            text = workflow.read_text()
            lines = [line for line in text.splitlines() if "pick-verifier-model" in line and not line.strip().startswith("#")]
            if not lines:
                continue
            base_paths = {path for ref, path in checkout_blocks(text) if "pull_request.base.sha" in ref and path}
            for line in lines:
                seen += 1
                match = re.search(r'"\$GITHUB_WORKSPACE/([\w.-]+)/scripts/pick-verifier-model"', line)
                self.assertTrue(match, f"{workflow.name}: picker not run from a checkout path: {line.strip()}")
                self.assertIn(match.group(1), base_paths, f"{workflow.name}: {match.group(1)} is not a base.sha checkout")
                self.assertNotIn("change", match.group(1).split("/"), f"{workflow.name}: picker taken from the PR head")
        self.assertGreater(seen, 0)

    def test_picker_edited_by_the_pr_still_gets_the_base_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "scripts").mkdir(parents=True)
            git(repo, "init", "-q", "-b", "main")
            picker = repo / "scripts/pick-verifier-model"
            picker.write_text(PICKER.read_text())
            picker.chmod(0o755)
            git(repo, "add", ".")
            git(repo, "commit", "-q", "-m", "base")
            base = git(repo, "rev-parse", "HEAD")
            git(repo, "checkout", "-q", "-b", "pr")
            picker.write_text('#!/usr/bin/env python3\nprint("deepseek-v4.1-flash")\n')
            git(repo, "commit", "-qam", "pr edits its own checker")
            head = git(repo, "rev-parse", "HEAD")
            event = Path(tmp) / "event.json"
            event.write_text(json.dumps({"pull_request": {"body": DEEPSEEK_AUTHOR}}))
            env = {k: v for k, v in os.environ.items() if k != "GITHUB_EVENT_PATH"}
            env["GITHUB_EVENT_PATH"] = str(event)

            def run_at(sha, path):
                git(repo, "worktree", "add", "-q", "--detach", str(path), sha)
                return subprocess.run(["python3", "-I", str(path / "scripts/pick-verifier-model")],
                                      capture_output=True, text=True, env=env, cwd=repo)

            from_head = run_at(head, Path(tmp) / "change")
            self.assertEqual(from_head.stdout, "deepseek-v4.1-flash\n", "the edited picker is the attack")
            from_base = run_at(base, Path(tmp) / "picker-base")
            self.assertEqual((from_base.returncode, from_base.stdout), (0, "glm-5.3-flash\n"), from_base.stderr)


if __name__ == "__main__":
    unittest.main()
