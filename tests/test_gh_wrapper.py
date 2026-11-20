#!/usr/bin/env python3
"""tools/gh-wrapper/gh: pr reads are cached, watch runs on the cache, the cache is pruned, tokens never land on disk.

The wrapper replaces /usr/bin/gh in front of /usr/bin/gh.real. Every test here drives the real wrapper file
against a fake gh.real that counts its invocations, so the saving is measured, not assumed.
"""
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock

warnings.simplefilter("ignore", ResourceWarning)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools/gh-wrapper" / "gh"

FAKE = '''#!/usr/bin/env python3
import os, sys, time
line = " ".join(sys.argv[1:])
fd = os.open(os.environ["FAKE_GH_LOG"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.write(fd, (line + "\\n").encode())
os.close(fd)
time.sleep(float(os.environ.get("FAKE_GH_DELAY", "0")))
sys.stdout.write(os.environ.get("FAKE_GH_STDOUT", "fake " + line + "\\n"))
sys.stderr.write(os.environ.get("FAKE_GH_STDERR", ""))
sys.exit(int(os.environ.get("FAKE_GH_CODE", "0")))
'''


def load_wrapper(name="gh_wrapper"):
    loader = importlib.machinery.SourceFileLoader(name, str(WRAPPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class WrapperCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gh-wrapper-test."))
        self.real = self.tmp / "gh.real"
        self.real.write_text(FAKE, encoding="utf-8")
        self.real.chmod(0o755)
        self.cache = self.tmp / "cache"
        self.call_log = self.tmp / "calls.tsv"
        self.count = self.tmp / "upstream.log"
        self.tmp_env = {
            "GH_REAL": str(self.real),
            "HT_GH_CACHE_DIR": str(self.cache),
            "GH_CALL_LOG": str(self.call_log),
            "FAKE_GH_LOG": str(self.count),
            "GH_TOKEN": "ghp_TESTTOKENdoNotLeak0123456789abcdef",
            "HOME": str(self.tmp / "home"),
        }
        (self.tmp / "home").mkdir(exist_ok=True)
        # In-process module calls read os.environ too, so the patch must reach them: without it a
        # prune test would walk the live ~/.local/state/gh-shared-cache.
        self.patch = mock.patch.dict(os.environ, {}, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_WRAPPER_TTL", "GH_WRAPPER_NO_CACHE",
                     "GH_WRAPPER_PRUNE", "HT_GH_APP_TOKEN_FILE"):
            os.environ.pop(name, None)
        os.environ.update(self.tmp_env)

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)], check=False)

    def module(self, name="gh_wrapper"):
        module = load_wrapper(name)
        resolved = str(module.cache_dir())
        self.assertTrue(resolved.startswith(str(self.tmp)),
                        "the test cache dir must be isolated, got %s" % resolved)
        return module

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GH_TOKEN", "GITHUB_TOKEN", "GH_WRAPPER_NO_CACHE", "GH_WRAPPER_TTL",
                             "GH_WRAPPER_PRUNE", "GH_ENTERPRISE_TOKEN", "HT_GH_APP_TOKEN_FILE")}
        env.update(self.tmp_env)
        env.update(extra)
        return env

    def run_gh(self, *args, env=None, cwd=None):
        return subprocess.run([sys.executable, str(WRAPPER), *args], capture_output=True, text=True,
                              env=env or self.env(), cwd=str(cwd or self.tmp), timeout=120)

    def upstream_calls(self):
        if not self.count.exists():
            return []
        return [line for line in self.count.read_text(encoding="utf-8").splitlines() if line.strip()]

    def log_rows(self):
        if not self.call_log.exists():
            return []
        return [line.split("\t") for line in self.call_log.read_text(encoding="utf-8").splitlines() if line]


class CacheTests(WrapperCase):
    def test_ten_concurrent_checks_cause_one_upstream_call(self):
        env = self.env(FAKE_GH_DELAY="0.4")
        procs = [subprocess.Popen([sys.executable, str(WRAPPER), "pr", "checks", "1"], env=env,
                                  cwd=str(self.tmp), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(10)]
        codes = []
        for proc in procs:
            out, err = proc.communicate(timeout=120)
            codes.append(proc.returncode)
            self.assertIn("pr checks 1", out)
        self.assertEqual(codes, [0] * 10)
        self.assertEqual(len(self.upstream_calls()), 1, self.upstream_calls())

    def test_different_args_get_different_entries(self):
        self.run_gh("pr", "checks", "1")
        self.run_gh("pr", "checks", "2")
        self.run_gh("pr", "checks", "1", "--required")
        self.assertEqual(len(self.upstream_calls()), 3)
        self.run_gh("pr", "checks", "1")
        self.run_gh("pr", "checks", "2")
        self.assertEqual(len(self.upstream_calls()), 3)

    def test_repo_and_token_identity_keep_entries_apart(self):
        self.run_gh("pr", "view", "1", "-R", "o/one")
        self.run_gh("pr", "view", "1", "-R", "o/two")
        self.assertEqual(len(self.upstream_calls()), 2)
        self.run_gh("pr", "view", "1", "-R", "o/one", env=self.env(GH_TOKEN="ghp_OTHERSECRET000000000000000000000000000"))
        self.assertEqual(len(self.upstream_calls()), 3)
        self.run_gh("pr", "view", "1", "-R", "o/one")
        self.assertEqual(len(self.upstream_calls()), 3)

    def test_origin_remote_keys_the_entry(self):
        for name in ("repo-a", "repo-b"):
            work = self.tmp / name
            work.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=str(work), check=True)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/o/%s.git" % name],
                           cwd=str(work), check=True)
        self.run_gh("pr", "status", cwd=self.tmp / "repo-a")
        self.run_gh("pr", "status", cwd=self.tmp / "repo-b")
        self.assertEqual(len(self.upstream_calls()), 2)
        self.run_gh("pr", "status", cwd=self.tmp / "repo-a")
        self.assertEqual(len(self.upstream_calls()), 2)

    def test_writing_commands_are_never_cached(self):
        for argv in (["pr", "create", "--title", "t", "--body", "b"],
                     ["pr", "merge", "1", "--squash"],
                     ["pr", "edit", "1", "--body", "b"],
                     ["pr", "comment", "1", "--body", "b"],
                     ["pr", "review", "1", "--approve"],
                     ["pr", "close", "1"],
                     ["pr", "ready", "1"]):
            self.run_gh(*argv)
            self.run_gh(*argv)
        self.assertEqual(len(self.upstream_calls()), 14, self.upstream_calls())

    def test_exit_code_and_stderr_replay(self):
        env = self.env(FAKE_GH_CODE="8", FAKE_GH_STDOUT="skills\tpending\t0\thttps://e/1\n",
                       FAKE_GH_STDERR="something to say\n")
        first = self.run_gh("pr", "checks", "9", env=env)
        second = self.run_gh("pr", "checks", "9", env=env)
        self.assertEqual(first.returncode, 8)
        self.assertEqual(second.returncode, 8)
        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual(second.stderr, first.stderr)
        self.assertEqual(second.stdout, "skills\tpending\t0\thttps://e/1\n")
        self.assertEqual(second.stderr, "something to say\n")
        self.assertEqual(len(self.upstream_calls()), 1)

    def test_ttl_expiry_and_env_override(self):
        env = self.env(GH_WRAPPER_TTL="0")
        self.run_gh("pr", "checks", "1", env=env)
        self.run_gh("pr", "checks", "1", env=env)
        self.assertEqual(len(self.upstream_calls()), 2)

    def test_no_cache_flag_and_env_bypass(self):
        self.run_gh("pr", "checks", "1", "--no-cache")
        self.run_gh("pr", "checks", "1", "--no-cache")
        self.run_gh("pr", "checks", "1", env=self.env(GH_WRAPPER_NO_CACHE="1"))
        self.assertEqual(len(self.upstream_calls()), 3)
        self.run_gh("pr", "checks", "1", "--no-cache")
        self.assertEqual(len(self.upstream_calls()), 4, "a bypassed call must not fill the cache")

    def test_log_marks_hits_with_the_old_columns_kept(self):
        self.run_gh("pr", "checks", "1", "-R", "o/r")
        self.run_gh("pr", "checks", "1", "-R", "o/r")
        rows = self.log_rows()
        self.assertEqual(len(rows), 2, rows)
        self.assertTrue(all(len(row) == 7 for row in rows), rows)
        self.assertEqual([row[6] for row in rows], ["miss", "hit"])
        self.assertEqual(rows[0][2], "pr")
        self.assertIn("pr checks 1", rows[0][3])
        self.assertEqual(rows[0][4], rows[1][4])
        self.assertIn(rows[0][4], ("app", "user"))


class WatchTests(WrapperCase):
    def watch(self, argv, codes, **kwargs):
        module = self.module("gh_wrapper_watch")
        clock = [1000.0]
        sleeps, calls = [], []

        def runner(call_argv, env):
            calls.append(list(call_argv))
            code = codes[min(len(calls) - 1, len(codes) - 1)]
            body = "skills\tpending\t0\thttps://e/1\n" if code == 8 else "skills\tpass\t9s\thttps://e/1\n"
            return module.Outcome(code, body, "")

        def sleeper(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        out, err = io.StringIO(), io.StringIO()
        code = module.pr_checks_watch(argv, str(self.real), runner=runner, sleeper=sleeper,
                                     clock=lambda: clock[0], out=out, err=err, **kwargs)
        return code, sleeps, calls, out.getvalue(), err.getvalue()

    def test_watch_polls_the_cache_at_sixty_seconds(self):
        code, sleeps, calls, out, _err = self.watch(["gh", "pr", "checks", "1", "--watch", "--interval", "10"],
                                                    [8, 8, 0])
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [60, 60])
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertNotIn("--watch", call)
            self.assertNotIn("--interval", call)
        self.assertIn("Refreshing checks status every 60 seconds", out)
        self.assertEqual(out.count("https://e/1"), 3)

    def test_watch_keeps_a_longer_requested_interval(self):
        code, sleeps, _calls, _out, _err = self.watch(["gh", "pr", "checks", "1", "--watch", "-i", "300"], [8, 0])
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [300])

    def test_watch_exits_one_on_failure_and_honours_fail_fast(self):
        code, _sleeps, _calls, _out, _err = self.watch(["gh", "pr", "checks", "1", "--watch", "--fail-fast"], [1])
        self.assertEqual(code, 1)
        code, _sleeps, _calls, _out, _err = self.watch(["gh", "pr", "checks", "1", "--watch"], [1])
        self.assertEqual(code, 1)


class PruneTests(WrapperCase):
    def entry(self, name, size, age, directory=None):
        directory = directory or (self.cache / "pr")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (name + ".json")
        path.write_text("x" * size, encoding="utf-8")
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def test_prune_deletes_entries_older_than_a_day(self):
        module = self.module("gh_wrapper_prune")
        old = self.entry("a" * 64, 10, 3 * 86400)
        fresh = self.entry("b" * 64, 10, 600)
        api_old = self.entry("c" * 64, 10, 3 * 86400, directory=self.cache)
        result = module.prune_cache(force=True)
        self.assertFalse(old.exists())
        self.assertFalse(api_old.exists())
        self.assertTrue(fresh.exists())
        self.assertGreaterEqual(result["removed"], 2)

    def test_prune_caps_the_directory_size_and_keeps_the_newest(self):
        module = self.module("gh_wrapper_prune_size")
        made = [self.entry("%064x" % index, 400, 3600 - index * 100) for index in range(5)]
        module.prune_cache(force=True, max_age=10 ** 9, cap_bytes=1000)
        left = [path for path in made if path.exists()]
        self.assertLessEqual(sum(path.stat().st_size for path in left), 1000)
        self.assertEqual(left, sorted(left, key=lambda path: path.stat().st_mtime)[-2:])

    def test_prune_runs_at_most_once_per_ten_minutes(self):
        module = self.module("gh_wrapper_prune_stamp")
        self.entry("d" * 64, 10, 3 * 86400)
        module.prune_cache()
        again = self.entry("e" * 64, 10, 3 * 86400)
        second = module.prune_cache()
        self.assertTrue(second["skipped"])
        self.assertTrue(again.exists(), "a second prune inside ten minutes must do nothing")

    def test_prune_mode_runs_from_the_command_line(self):
        old = self.entry("f" * 64, 10, 3 * 86400)
        result = self.run_gh(env=self.env(GH_WRAPPER_PRUNE="1"))
        self.assertEqual(result.returncode, 0)
        self.assertFalse(old.exists())
        self.assertIn("removed", result.stdout)


class SecretTests(WrapperCase):
    def test_no_token_reaches_a_cache_file_or_the_log(self):
        token = self.tmp_env["GH_TOKEN"]
        self.run_gh("pr", "view", "1", "-R", "o/r")
        self.run_gh("pr", "view", "1", "-R", "o/r")
        self.run_gh("pr", "checks", "1", "-R", "o/r")
        seen = 0
        for root, _dirs, files in os.walk(str(self.cache)):
            for name in files:
                text = (Path(root) / name).read_bytes()
                self.assertNotIn(token.encode(), text, Path(root) / name)
                seen += 1
        log = self.call_log.read_text(encoding="utf-8")
        self.assertNotIn(token, log)
        self.assertNotIn("GITHUB_TOKEN", log)
        self.assertGreaterEqual(seen, 2, "cache files should exist to scan")


if __name__ == "__main__":
    unittest.main()
