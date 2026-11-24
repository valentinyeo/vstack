import json
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/ci-key-set"
LOGIN = 'fake-plan-login-226\n{"token":"not-real-$VALUE-å"}\n\n'
FAKE_GH = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(os.environ["FAKE_GH_ROOT"])
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:3] == ["api", "--method", "GET"]:
    assert sys.stdin.buffer.read() == b"", "metadata lookup consumed the login"
    if os.environ.get("FAKE_API_FAIL"):
        print("fake metadata failure", file=sys.stderr)
        sys.exit(1)
    assert args[4] == "--jq"
    result = subprocess.run(["jq", "-r", args[5]], input=os.environ["FAKE_REPO"],
                            text=True, capture_output=True)
    print(result.stdout, end="")
    sys.exit(result.returncode)
if args[:2] == ["secret", "set"]:
    value = sys.stdin.buffer.read()
    (root / "received").write_bytes(value)
    sys.stdout.buffer.write(value)
    sys.stderr.buffer.write(value)
    sys.exit(int(os.environ.get("FAKE_SET_EXIT", "0")))
sys.exit(99)
'''


class CiKeySetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.scratch = self.root / "tmp"
        self.scratch.mkdir()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        FAKE_GH_ROOT=str(self.root), TMPDIR=str(self.scratch))
        self.env.pop("FAKE_API_FAIL", None)
        self.env.pop("FAKE_SET_EXIT", None)
        self.repo()

    def repo(self, name="valentinyeo/vstack", fork=False, parent_private=None):
        self.env["FAKE_REPO"] = json.dumps({
            "full_name": name, "fork": fork,
            "parent": {"private": parent_private},
        })

    def run_tool(self, *args, login=LOGIN, trace=False, stdin=None):
        command = ["bash", "-xv", str(TOOL)] if trace else [str(TOOL)]
        result = subprocess.run(command + list(args), env=self.env,
                                input=login if stdin is None else None,
                                stdin=stdin, text=True, capture_output=True, timeout=10)
        self.assertNotIn(LOGIN.strip(), result.stdout + result.stderr)
        self.assertNotIn("fake-plan-login-226", result.stdout + result.stderr)
        self.assertEqual(list(self.scratch.iterdir()), [])
        return result

    def calls(self):
        log = self.root / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def assert_not_set(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "received").exists())
        self.assertFalse(any(call[:2] == ["secret", "set"] for call in self.calls()))

    def test_stdin_each_allowed_name_and_owner(self):
        for owner in ("valentinyeo", "hypertask-ai"):
            for name in ("PSTACK_OPENCODE_API_KEY", "OPENCODE_API_KEY", "AI_GATEWAY_API_KEY"):
                with self.subTest(owner=owner, name=name):
                    self.repo(f"{owner}/vstack")
                    result = self.run_tool(f"{owner}/vstack", name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((self.root / "received").read_bytes(), LOGIN.encode())
                    self.assertEqual(self.calls()[-1], ["secret", "set", name, "--repo", f"{owner}/vstack"])
                    self.assertNotIn(LOGIN, json.dumps(self.calls()))

    def test_file_with_spaces_preserves_value_and_leaves_file_unchanged(self):
        path = self.root / "plan login.json"
        path.write_bytes(LOGIN.encode())
        result = self.run_tool("valentinyeo/vstack", "PSTACK_OPENCODE_API_KEY",
                               "--from-file", str(path), login="ignored stdin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "received").read_bytes(), LOGIN.encode())
        self.assertEqual(path.read_bytes(), LOGIN.encode())
        self.assertNotIn(str(path), json.dumps(self.calls()))

    def test_unknown_names_refused_before_gh_with_one_line_policy_pointer(self):
        for name in ("GH_TOKEN", "AWS_SECRET_ACCESS_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
                     "opencode_api_key", "--body", LOGIN):
            with self.subTest(name=name):
                result = self.run_tool("valentinyeo/vstack", name)
                self.assert_not_set(result)
                self.assertEqual(result.stdout, "")
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertIn("~/.claude/reference/keys.md", result.stderr)
                self.assertEqual(self.calls(), [])

    def test_bad_repo_names_refused_before_gh(self):
        for repo in ("outsider/vstack", "valentinyeo-evil/vstack", "--repo",
                     "https://github.com/valentinyeo/vstack", "valentinyeo/vstack/extra",
                     "valentinyeo/../outsider", "hypertask-ai/", LOGIN):
            with self.subTest(repo=repo):
                self.assert_not_set(self.run_tool(repo, "OPENCODE_API_KEY"))
                self.assertEqual(self.calls(), [])

    def test_public_parent_fork_is_refused(self):
        self.repo(fork=True, parent_private=False)
        self.assert_not_set(self.run_tool("valentinyeo/vstack", "OPENCODE_API_KEY"))

    def test_private_parent_fork_is_allowed(self):
        self.repo(fork=True, parent_private=True)
        self.assertEqual(self.run_tool("valentinyeo/vstack", "OPENCODE_API_KEY").returncode, 0)

    def test_missing_fork_metadata_is_refused(self):
        for metadata in ({}, {"full_name": "valentinyeo/vstack"},
                         {"full_name": "valentinyeo/vstack", "fork": True},
                         {"full_name": "valentinyeo/vstack", "fork": "false"}):
            with self.subTest(metadata=metadata):
                self.env["FAKE_REPO"] = json.dumps(metadata)
                self.assert_not_set(self.run_tool("valentinyeo/vstack", "OPENCODE_API_KEY"))

    def test_redirected_repository_is_refused(self):
        for name in ("outsider/vstack", "valentinyeo/renamed", "hypertask-ai/vstack"):
            with self.subTest(name=name):
                self.repo(name)
                self.assert_not_set(self.run_tool("valentinyeo/vstack", "OPENCODE_API_KEY"))

    def test_repository_casing_is_accepted(self):
        self.repo("ValentinYeo/VStack")
        result = self.run_tool("ValentinYeo/VStack", "OPENCODE_API_KEY")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[-1][-1], "valentinyeo/vstack")

    def test_metadata_errors_fail_closed(self):
        self.env["FAKE_API_FAIL"] = "1"
        self.assert_not_set(self.run_tool("valentinyeo/vstack", "OPENCODE_API_KEY"))

    def test_failed_upload_does_not_echo_value(self):
        self.env["FAKE_SET_EXIT"] = "1"
        result = self.run_tool("valentinyeo/vstack", "OPENCODE_API_KEY")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GitHub could not set", result.stderr)

    def test_shell_tracing_does_not_echo_value(self):
        result = self.run_tool("valentinyeo/vstack", "OPENCODE_API_KEY", trace=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bad_arguments_and_missing_file_never_call_gh(self):
        for args in ((), ("valentinyeo/vstack",),
                     ("valentinyeo/vstack", "OPENCODE_API_KEY", LOGIN),
                     ("valentinyeo/vstack", "OPENCODE_API_KEY", "--body", LOGIN),
                     ("valentinyeo/vstack", "OPENCODE_API_KEY", "--from-file", "/missing/login"),
                     ("valentinyeo/vstack", "OPENCODE_API_KEY", "--from-file", str(self.root))):
            with self.subTest(args=args):
                self.assert_not_set(self.run_tool(*args))
                self.assertEqual(self.calls(), [])

    def test_terminal_input_refused_without_prompt(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        result = self.run_tool("valentinyeo/vstack", "OPENCODE_API_KEY", stdin=slave)
        self.assert_not_set(result)
        self.assertIn("pipe the login", result.stderr)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
