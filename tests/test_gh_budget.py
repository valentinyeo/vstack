#!/usr/bin/env python3
"""tools/gh-wrapper/gh keeps one GitHub budget per chat: warn at 300 calls an hour, refuse reads at 600.

One token serves every chat, so a single polling loop can spend the whole 5000 an hour pool. The
wrapper counts the calls that reach GitHub (a cache hit is free) in a small counter file per session
per hour, warns once above 300, and refuses reads with exit 75 above 600. Writes are never refused,
and a call with no session id is never refused. These tests drive the real wrapper against a fake
gh.real that records every upstream call it gets.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools/gh-wrapper" / "gh"
RULES = "~/.local/share/vstack/tools/gh-wrapper/USING-GITHUB.md"

FAKE = '''#!/usr/bin/env python3
import os, sys
line = " ".join(sys.argv[1:])
fd = os.open(os.environ["FAKE_GH_LOG"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.write(fd, (line + "\\n").encode())
os.close(fd)
if "rate_limit" in line:
    sys.stdout.write(os.environ.get("FAKE_RATE_LIMIT", ""))
    sys.exit(0)
sys.stdout.write(os.environ.get("FAKE_GH_STDOUT", "fake " + line + "\\n"))
sys.exit(int(os.environ.get("FAKE_GH_CODE", "0")))
'''

RATE = {
    "resources": {
        "core": {"limit": 5000, "remaining": 4832, "reset": 1795196000},
        "graphql": {"limit": 5000, "remaining": 4991, "reset": 1795196000},
    }
}
RATE_BODY = "HTTP/2.0 200 OK\n\n" + json.dumps(RATE)


def load_wrapper():
    loader = importlib.machinery.SourceFileLoader("gh_wrapper_budget", str(WRAPPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class BudgetCase(unittest.TestCase):
    session = "budgettest"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gh-budget-test."))
        self.real = self.tmp / "gh.real"
        self.real.write_text(FAKE, encoding="utf-8")
        self.real.chmod(0o755)
        self.call_log = self.tmp / "calls.tsv"
        self.upstream_log = self.tmp / "upstream.log"
        self.base = {
            "GH_REAL": str(self.real),
            "HT_GH_CACHE_DIR": str(self.tmp / "cache"),
            "GH_CALL_LOG": str(self.call_log),
            "FAKE_GH_LOG": str(self.upstream_log),
            "FAKE_RATE_LIMIT": RATE_BODY,
            "GH_TOKEN": "ghp_BUDGETTOKENdoNotLeak0123456789abcdef",
            "HT_SESSION_NAME": self.session,
            "HOME": str(self.tmp / "home"),
        }
        (self.tmp / "home").mkdir(exist_ok=True)
        self.patch = mock.patch.dict(os.environ, {}, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)], check=False))
        for name in ("CLAUDE_CODE_SESSION_ID", "CODEX_COMPANION_SESSION_ID", "GH_WRAPPER_TTL",
                     "GH_WRAPPER_NO_CACHE", "GH_BUDGET_DIR", "GH_WRAPPER_PRUNE"):
            os.environ.pop(name, None)
        os.environ.update(self.base)

    def env(self, **extra):
        env = {key: value for key, value in os.environ.items()
               if key not in ("CLAUDE_CODE_SESSION_ID", "CODEX_COMPANION_SESSION_ID",
                              "GH_BUDGET_DIR", "GH_WRAPPER_TTL")}
        env.update(self.base)
        env.update(extra)
        return env

    def run_gh(self, *args, env=None):
        return subprocess.run([sys.executable, str(WRAPPER), *args], capture_output=True, text=True,
                              env=env or self.env(), cwd=str(self.tmp), timeout=120)

    def upstream_calls(self):
        if not self.upstream_log.exists():
            return []
        return [line for line in self.upstream_log.read_text(encoding="utf-8").splitlines() if line]

    def log_rows(self):
        if not self.call_log.exists():
            return []
        return [line.split("\t") for line in self.call_log.read_text(encoding="utf-8").splitlines() if line]

    def path(self, session=None):
        return self.tmp / "budget" / ("s." + (session or self.session))

    def seed(self, count, session=None, minute=None):
        target = self.path(session)
        target.parent.mkdir(parents=True, exist_ok=True)
        minute = int(time.time()) // 60 if minute is None else minute
        target.write_text("%d %d\n" % (minute, count), encoding="utf-8")
        return target

    def add(self, minute, count, session=None):
        target = self.path(session)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write("%d %d\n" % (minute, count))

    def count(self, session=None):
        target = self.path(session)
        try:
            lines = [line.split() for line in target.read_text(encoding="utf-8").splitlines()]
        except OSError:
            return 0
        return sum(int(parts[1]) for parts in lines if len(parts) == 2 and parts[0].isdigit())


class BudgetWarnTests(BudgetCase):
    def test_warn_at_300_runs_the_call_and_writes_one_line(self):
        self.seed(300)
        result = self.run_gh("pr", "checks", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.upstream_calls()), 1)
        self.assertIn("gh budget: budgettest used 300 of 600 GitHub calls this hour; "
                      "slow down or use the cache.", result.stderr)
        self.assertIn("~/.local/share/vstack/tools/gh-wrapper/wait-checks <repo> <pr>", result.stderr)
        self.assertIn(RULES, result.stderr)
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        self.assertEqual(self.count(), 301)
        self.assertEqual([row[6] for row in self.log_rows()], ["warned"])

    def test_warn_does_not_block_a_write(self):
        self.seed(310)
        result = self.run_gh("pr", "merge", "9", "--squash")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.upstream_calls()), 1)
        self.assertEqual(self.count(), 311)

    def test_cached_replies_cost_nothing(self):
        self.seed(300)
        self.assertEqual(self.run_gh("pr", "checks", "4").returncode, 0)
        self.assertEqual(self.count(), 301)
        again = self.run_gh("pr", "checks", "4")
        self.assertEqual(again.returncode, 0)
        self.assertEqual(again.stderr, "", "a cache hit must not warn again")
        self.assertEqual(self.count(), 301)
        self.assertEqual([row[6] for row in self.log_rows()], ["warned", "hit"])


class BudgetRefuseTests(BudgetCase):
    def test_refuse_at_600_stops_before_github(self):
        self.seed(600)
        result = self.run_gh("pr", "checks", "2")
        self.assertEqual(result.returncode, 75)
        self.assertEqual(self.upstream_calls(), [], "a refused call must not reach GitHub")
        self.assertIn("gh budget: budgettest is over 600 GitHub calls this hour; wait until", result.stderr)
        self.assertIn("UTC", result.stderr)
        self.assertIn(RULES, result.stderr)
        self.assertEqual(self.count(), 600)
        self.assertEqual([row[6] for row in self.log_rows()], ["refused"])

    def test_refuse_covers_one_rest_read(self):
        self.seed(600)
        result = self.run_gh("api", "repos/valentinyeo/vstack")
        self.assertEqual(result.returncode, 75)
        self.assertEqual(self.upstream_calls(), [])
        self.assertIn("is over 600 GitHub calls this hour", result.stderr)

    def test_unknown_session_is_never_refused(self):
        self.seed(9999, session="-")
        env = self.env()
        for name in ("HT_SESSION_NAME", "CLAUDE_CODE_SESSION_ID", "CODEX_COMPANION_SESSION_ID"):
            env.pop(name, None)
        result = self.run_gh("pr", "checks", "3", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.upstream_calls()), 1)
        self.assertEqual(result.stderr, "")
        self.assertEqual([row[6] for row in self.log_rows()], ["miss"])

    def test_writes_are_never_refused(self):
        self.seed(600)
        for argv in (["pr", "merge", "1", "--squash"],
                     ["pr", "create", "--title", "t", "--body", "b"],
                     ["pr", "comment", "1", "--body", "b"],
                     ["pr", "edit", "1", "--body", "b"],
                     ["pr", "ready", "1"]):
            result = self.run_gh(*argv)
            self.assertEqual(result.returncode, 0, "%s: %s" % (argv, result.stderr))
        self.assertEqual(len(self.upstream_calls()), 5)
        self.assertEqual(self.count(), 605)


class BudgetCommandTests(BudgetCase):
    def test_budget_prints_this_session_top_five_and_rate_limit(self):
        self.seed(7, session="aaa")
        self.seed(5, session="bbb")
        result = self.run_gh("budget")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gh budget budgettest: 0 of 600 GitHub calls this hour, warn at 300", result.stdout)
        self.assertIn("top sessions this hour:", result.stdout)
        lines = result.stdout.splitlines()
        top = [line for line in lines if line.startswith("  ")]
        self.assertEqual([line.split()[0] for line in top], ["aaa", "bbb"])
        self.assertIn("REST core 4832 of 5000 left; GraphQL 4991 of 5000 left; resets", result.stdout)
        self.assertEqual(len(self.upstream_calls()), 1)
        self.assertIn("rate_limit", self.upstream_calls()[0])
        self.assertNotIn("budget", self.upstream_calls()[0].split(), "gh budget never reaches gh.real")

    def test_budget_rate_limit_comes_from_one_cached_call(self):
        self.run_gh("budget")
        self.run_gh("budget")
        self.assertEqual(len(self.upstream_calls()), 1, "one cached rate_limit call serves both")

    def test_budget_reports_an_unknown_session_honestly(self):
        env = self.env()
        env.pop("HT_SESSION_NAME", None)
        result = self.run_gh("budget", env=env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("no session id, so this chat is never refused", result.stdout)


class BudgetCountRuleTests(BudgetCase):
    def test_minutes_inside_the_rolling_hour_count(self):
        self.seed(600, minute=int(time.time()) // 60 - 59)
        result = self.run_gh("pr", "checks", "5")
        self.assertEqual(result.returncode, 75)
        self.assertEqual(self.upstream_calls(), [])

    def test_minutes_older_than_the_rolling_hour_are_ignored(self):
        self.seed(600, minute=int(time.time()) // 60 - 60)
        result = self.run_gh("pr", "checks", "6")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.count(), 1, "the old bucket is dropped and only this call remains")

    def test_a_fixed_hour_boundary_cannot_reset_the_count(self):
        minute = int(time.time()) // 60
        self.add(minute, 400)
        self.add(minute - 59, 400)
        result = self.run_gh("pr", "checks", "8")
        self.assertEqual(result.returncode, 75, "the rolling hour still holds 800 calls")

    def test_a_stale_session_file_is_dropped(self):
        stale = self.tmp / "budget" / "s.other"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("%d 12\n" % (int(time.time()) // 60 - 500), encoding="utf-8")
        old = time.time() - 5 * 3600
        os.utime(stale, (old, old))
        self.assertEqual(self.run_gh("pr", "checks", "9").returncode, 0)
        self.assertFalse(stale.exists(), "a counter nobody touched for hours is dropped")

    def test_the_wait_until_is_when_the_oldest_bucket_expires(self):
        minute = int(time.time()) // 60
        self.add(minute - 30, 600)
        result = self.run_gh("pr", "checks", "10")
        self.assertEqual(result.returncode, 75)
        expected = time.strftime("%H:%M UTC", time.gmtime((minute - 30 + 1) * 60))
        self.assertIn("wait until %s" % expected, result.stderr)

    def test_a_warned_api_read_still_reaches_github(self):
        self.seed(300)
        result = self.run_gh("api", "repos/valentinyeo/vstack")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.upstream_calls()), 1)
        self.assertIn("slow down or use the cache", result.stderr)
        self.assertIn("Next: gh budget.", result.stderr)


if __name__ == "__main__":
    unittest.main()
