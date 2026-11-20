#!/usr/bin/env python3
"""calls.tsv rolls at a size limit, keeps two gz copies, stays safe under concurrency."""
import gzip
import importlib.machinery
import importlib.util
import multiprocessing
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools/gh-wrapper" / "gh"


def load_wrapper(name="gh_log_rotate"):
    loader = importlib.machinery.SourceFileLoader(name, str(WRAPPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def _worker(args):
    """One process, many appends — same pattern as chats calling gh in parallel."""
    log_path, worker_id, per = args
    os.environ["GH_CALL_LOG"] = log_path
    os.environ["GH_CALL_LOG_ROLL_BYTES"] = os.environ.get("GH_CALL_LOG_ROLL_BYTES", "800")
    os.environ.setdefault("HOME", str(Path(log_path).parent))
    mod = load_wrapper("gh_log_rotate_w%s" % worker_id)
    base = worker_id * per
    for offset in range(per):
        try:
            mod._log_call(["gh", "api", "repos/o/r/issue-%s" % (base + offset)])
        except Exception as error:
            Path(log_path).parent.joinpath("worker-%s.err" % worker_id).write_text(
                repr(error), encoding="utf-8")
            raise
    return per


class LogRotateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gh-log-rotate."))
        self.log = self.tmp / "calls.tsv"
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.patch = mock.patch.dict(os.environ, {
            "GH_CALL_LOG": str(self.log),
            "GH_CALL_LOG_ROLL_BYTES": "500",
            "HOME": str(self.tmp),
        }, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def module(self):
        return load_wrapper("gh_log_rotate_main_%s" % id(self))

    def _line(self, n=1):
        return ("%d\tcaller\tGET\t/repos/o/r\tuser\ts1\t-\n" % (1700000000 + n)) * n

    def _count_lines(self):
        total = 0
        log = self.log
        parent = log.parent
        for name in (log.name + ".2.gz", log.name + ".1.gz", log.name):
            path = parent / name
            if not path.exists():
                continue
            if str(path).endswith(".gz"):
                with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
                    total += sum(1 for line in handle if line.strip())
            else:
                total += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        return total

    def test_roll_at_limit_keeps_two_gz(self):
        mod = self.module()
        body = self._line(1) * 30
        self.log.write_text(body, encoding="utf-8")
        self.assertGreaterEqual(self.log.stat().st_size, 500)
        mod._maybe_roll_log(str(self.log))
        one = self.tmp / "calls.tsv.1.gz"
        self.assertTrue(one.exists())
        self.assertFalse(self.log.exists())
        self.log.write_text(body, encoding="utf-8")
        mod._maybe_roll_log(str(self.log))
        two = self.tmp / "calls.tsv.2.gz"
        self.assertTrue(two.exists())
        self.assertTrue(one.exists())
        self.assertFalse((self.tmp / "calls.tsv.3.gz").exists())

    def test_under_limit_no_roll(self):
        mod = self.module()
        self.log.write_text("short\n", encoding="utf-8")
        mod._maybe_roll_log(str(self.log))
        self.assertTrue(self.log.exists())
        self.assertFalse((self.tmp / "calls.tsv.1.gz").exists())

    def test_log_call_still_appends_on_roll_error(self):
        mod = self.module()
        self.log.write_text("x" * 600, encoding="utf-8")
        mod._log_call(["gh", "api", "repos/o/r"])
        rows = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)
        self.assertIn("\t", rows[0])

    def test_concurrent_writers_lose_no_lines(self):
        # Forked children must see a real os.environ, not unittest.mock.patch.dict.
        self.patch.stop()
        try:
            os.environ["GH_CALL_LOG"] = str(self.log)
            # Small enough to roll after the burst (~110 KiB of lines); large enough
            # that eight writers are not rolling on every line.
            os.environ["GH_CALL_LOG_ROLL_BYTES"] = "120000"
            os.environ["HOME"] = str(self.tmp)
            self.log.write_text("", encoding="utf-8")
            n_proc, per = 8, 200
            ctx = multiprocessing.get_context("fork")
            with ctx.Pool(n_proc) as pool:
                results = pool.map(_worker, [(str(self.log), wid, per) for wid in range(n_proc)])
            self.assertEqual(sum(results), n_proc * per)
            self.assertEqual(self._count_lines(), n_proc * per)
        finally:
            self.patch.start()

    def test_lock_busy_skips_roll_without_error(self):
        mod = self.module()
        self.log.write_text("x" * 800, encoding="utf-8")
        lock_path = self.tmp / "roll.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = open(lock_path, "a+")
        import fcntl
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            mod._maybe_roll_log(str(self.log))
            self.assertTrue(self.log.exists())
            self.assertGreaterEqual(self.log.stat().st_size, 800)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        mod._log_call(["gh", "api", "repos/o/r"])
        rows = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()