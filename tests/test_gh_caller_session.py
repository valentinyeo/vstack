#!/usr/bin/env python3
"""tools/gh-wrapper/gh: script session fallbacks and gh api path logging."""
import importlib.machinery
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools/gh-wrapper" / "gh"


def load_wrapper(name="gh_caller_session"):
    loader = importlib.machinery.SourceFileLoader(name, str(WRAPPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class ApiPathTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_wrapper("gh_api_path_" + str(id(self)))

    def test_graphql_endpoint_is_logged(self):
        argv = ["gh", "api", "graphql", "-f", "query={viewer{login}}"]
        method, path, _jq, _flags, _fields = self.mod._api_path(argv)
        self.assertEqual(method, "GET")
        self.assertEqual(path, "graphql")

    def test_graphql_with_leading_flags(self):
        argv = ["gh", "api", "-H", "Accept: application/json", "graphql", "-f", "query={a}"]
        _method, path, _jq, _flags, _fields = self.mod._api_path(argv)
        self.assertEqual(path, "graphql")

    def test_http_verb_before_path(self):
        argv = ["gh", "api", "GET", "repos/o/r"]
        method, path, _jq, _flags, _fields = self.mod._api_path(argv)
        self.assertEqual(method, "GET")
        self.assertEqual(path, "repos/o/r")

    def test_paginate_path_from_live_log_shape(self):
        argv = ["gh", "api", "--paginate",
                "search/issues?q=repo:o/r+is:open&per_page=100"]
        method, path, _jq, flags, _fields = self.mod._api_path(argv)
        self.assertEqual(method, "GET")
        self.assertTrue(path.startswith("search/"))
        self.assertIn("--paginate", flags)


class ScriptSessionTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_wrapper("gh_script_session_" + str(id(self)))

    def test_fallback_uses_known_caller(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(self.mod, "_classify_caller_proc", return_value=("agent-feed", 99)):
                with mock.patch.object(self.mod, "script_ancestor_name", return_value=""):
                    self.assertEqual(self.mod.log_session(), "script:agent-feed")

    def test_fallback_uses_proc_ancestor(self):
        chain = {
            100: ["/usr/sbin/CRON"],
            200: ["/bin/bash", "-c", "ht-morning-report"],
            300: ["/bin/bash", "/home/me/.local/bin/ht-morning-report"],
        }

        def fake_cmdline(pid):
            return chain.get(pid, [])

        def fake_ppid(pid):
            return {100: 1, 200: 100, 300: 200}.get(pid, 0)

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(self.mod, "classify_caller", return_value="other"):
                with mock.patch.object(self.mod, "_proc_cmdline", side_effect=fake_cmdline):
                    with mock.patch.object(self.mod, "_proc_ppid", side_effect=fake_ppid):
                        with mock.patch.object(self.mod.os, "getppid", return_value=300):
                            self.assertEqual(self.mod.script_ancestor_name(), "cron:ht-morning-report")
                            self.assertEqual(self.mod.log_session(), "script:cron:ht-morning-report")

    def test_chat_session_wins_over_script(self):
        with mock.patch.dict(os.environ, {"HT_SESSION_NAME": "my-chat"}, clear=True):
            with mock.patch.object(self.mod, "classify_caller", return_value="agent-feed"):
                self.assertEqual(self.mod.log_session(), "my-chat")

    def test_dash_only_when_nothing_known(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(self.mod, "_classify_caller_proc", return_value=("other", 0)):
                with mock.patch.object(self.mod, "script_ancestor_name", return_value=""):
                    self.assertEqual(self.mod.log_session(), "-")

    def test_script_sessions_are_budgeted(self):
        with mock.patch.object(self.mod, "log_session", return_value="script:agent-feed"):
            with mock.patch.object(self.mod, "budget_count", return_value=600):
                verdict, count = self.mod.budget_verdict(["pr", "list"], now=0)
        self.assertEqual(verdict, "refuse")
        self.assertEqual(count, 600)

    def _cursor_agent_chain(self, agent_pid):
        chain = {
            agent_pid: ["/home/me/.local/bin/cursor-agent", "worker"],
            agent_pid - 1: ["/bin/bash", "-c", "gh pr list"],
        }
        ppid = {agent_pid: agent_pid - 2, agent_pid - 1: agent_pid, agent_pid - 2: 1}

        def fake_cmdline(pid):
            return chain.get(pid, [])

        def fake_ppid(pid):
            return ppid.get(pid, 0)

        return fake_cmdline, fake_ppid

    def test_agent_fallback_splits_by_match_pid(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(self.mod.os, "getppid", return_value=4101):
                with mock.patch.object(self.mod, "_proc_cmdline",
                                       side_effect=self._cursor_agent_chain(4102)[0]):
                    with mock.patch.object(self.mod, "_proc_ppid",
                                           side_effect=self._cursor_agent_chain(4102)[1]):
                        one = self.mod.log_session()
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(self.mod.os, "getppid", return_value=5101):
                    with mock.patch.object(self.mod, "_proc_cmdline",
                                           side_effect=self._cursor_agent_chain(5102)[0]):
                        with mock.patch.object(self.mod, "_proc_ppid",
                                               side_effect=self._cursor_agent_chain(5102)[1]):
                            two = self.mod.log_session()
        self.assertEqual(one, "agent:cursor-agent:4102")
        self.assertEqual(two, "agent:cursor-agent:5102")
        self.assertNotEqual(one, two)

    def test_agent_fallback_no_pid_stays_unbudgeted(self):
        with mock.patch.dict(os.environ, {"GH_CALLER": "cursor-agent"}, clear=True):
            self.assertEqual(self.mod.log_session(), "-")

    def test_agent_feed_stays_script_session(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(self.mod, "_classify_caller_proc", return_value=("agent-feed", 88)):
                with mock.patch.object(self.mod, "script_ancestor_name", return_value=""):
                    self.assertEqual(self.mod.log_session(), "script:agent-feed")


class GraphqlPassthroughTests(unittest.TestCase):
    def test_graphql_reaches_upstream_unchanged(self):
        tmp = Path(__file__).resolve().parents[1] / "tools" / "gh-wrapper" / "gh"
        import subprocess
        import tempfile
        from pathlib import Path as P
        root = P(tempfile.mkdtemp())
        real = root / "gh.real"
        log = root / "upstream.log"
        real.write_text(
            '#!/usr/bin/env python3\n'
            'import os, sys\n'
            'open(os.environ["FAKE_GH_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")\n',
            encoding="utf-8",
        )
        real.chmod(0o755)
        env = {
            "GH_REAL": str(real),
            "GH_CALL_LOG": str(root / "calls.tsv"),
            "FAKE_GH_LOG": str(log),
            "HT_GH_CACHE_DIR": str(root / "cache"),
            "HOME": str(root / "home"),
        }
        (root / "home").mkdir()
        argv = [sys.executable, str(tmp), "api", "graphql", "-f", "query={a}"]
        result = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(lines, ["api graphql -f query={a}"])
        rows = (root / "calls.tsv").read_text(encoding="utf-8").strip().split("\t")
        self.assertEqual(rows[3], "graphql")


if __name__ == "__main__":
    unittest.main()