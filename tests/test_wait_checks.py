#!/usr/bin/env python3
"""tools/gh-wrapper/wait-checks waits for CI in the background with at most one call a minute.

The wrapper caches `gh pr checks` for 60 seconds, so a background wait is cheap where a watch loop
is not. The command prints one line and exits 0 when every check passed, 1 when one failed, and 2
when the 30 minute cap is reached, so no chat waits forever. These tests drive it with a stub
runner, a stub clock and a stub sleeper: no network, no real minute.
"""
import importlib.machinery
import importlib.util
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WAIT = ROOT / "tools/gh-wrapper" / "wait-checks"

PENDING = "skills\tpending\t0\thttps://e/1\nbuild\tpass\t9s\thttps://e/2\n"
PASSED = "skills\tpass\t10s\thttps://e/1\nbuild\tpass\t9s\thttps://e/2\n"
FAILED = "skills\tpass\t10s\thttps://e/1\nbuild\tfail\t9s\thttps://e/2\n"


def load_wait():
    loader = importlib.machinery.SourceFileLoader("wait_checks", str(WAIT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class WaitChecksTests(unittest.TestCase):
    def setUp(self):
        self.wait = load_wait()

    def drive(self, rounds, **kwargs):
        clock = [1000.0]
        sleeps, polls = [], []

        def runner(repo, pr):
            polls.append((repo, pr))
            return rounds[min(len(polls) - 1, len(rounds) - 1)]

        def sleeper(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        out, err = io.StringIO(), io.StringIO()
        code = self.wait.wait("o/r", "12", runner=runner, sleeper=sleeper,
                              clock=lambda: clock[0], out=out, err=err, **kwargs)
        return code, sleeps, polls, out.getvalue(), err.getvalue()

    def test_waits_while_pending_then_passes(self):
        code, sleeps, polls, out, _err = self.drive([(8, PENDING, ""), (8, PENDING, ""), (0, PASSED, "")])
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [60, 60], "one poll a minute, never faster")
        self.assertEqual(len(polls), 3)
        self.assertEqual(polls[0], ("o/r", "12"))
        self.assertEqual(len(out.splitlines()), 1, out)
        self.assertIn("o/r#12 all checks passed", out)
        self.assertIn("3 poll(s)", out)

    def test_a_failed_check_exits_one_and_names_it(self):
        code, sleeps, _polls, out, _err = self.drive([(1, FAILED, "")])
        self.assertEqual(code, 1)
        self.assertEqual(sleeps, [])
        self.assertIn("1 check(s) failed: build", out)
        self.assertEqual(len(out.splitlines()), 1, out)

    def test_a_cancelled_check_counts_as_a_failure(self):
        cancelled = "build\tcancel\t1s\thttps://e/2\n"
        code, sleeps, _polls, out, _err = self.drive([(1, cancelled, "")])
        self.assertEqual(code, 1)
        self.assertEqual(sleeps, [])
        self.assertIn("failed: build", out)

    def test_a_failed_row_ends_the_wait_even_while_others_are_pending(self):
        code, sleeps, _polls, out, _err = self.drive([(1, PENDING + FAILED, "")])
        self.assertEqual(code, 1)
        self.assertEqual(sleeps, [])
        self.assertIn("failed: build", out)

    def test_the_thirty_minute_cap_exits_two(self):
        code, sleeps, polls, out, _err = self.drive([(8, PENDING, "")], max_minutes=30)
        self.assertEqual(code, 2)
        self.assertEqual(len(sleeps), 30)
        self.assertEqual(len(polls), 31)
        self.assertIn("still pending after 30 minutes", out)

    def test_an_unknown_failure_is_reported_not_waited_on(self):
        code, sleeps, _polls, _out, err = self.drive([(127, "", "gh: command not found")])
        self.assertEqual(code, 1)
        self.assertEqual(sleeps, [])
        self.assertIn("command not found", err)

    def test_the_interval_never_drops_below_a_minute(self):
        code, sleeps, _polls, _out, _err = self.drive([(8, PENDING, ""), (0, PASSED, "")], interval=5)
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [60])

    def test_read_once_asks_gh_pr_checks_through_the_wrapper(self):
        calls = []

        class Result:
            returncode = 0
            stdout = PASSED
            stderr = ""

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return Result()

        original = self.wait.subprocess.run
        self.wait.subprocess.run = fake_run
        try:
            code, text, _message = self.wait.read_once("o/r", "12")
        finally:
            self.wait.subprocess.run = original
        self.assertEqual(code, 0)
        self.assertEqual(text, PASSED)
        self.assertEqual(calls[0][1:], ["pr", "checks", "12", "--repo", "o/r"])
        self.assertNotIn("--watch", calls[0])


if __name__ == "__main__":
    unittest.main()
