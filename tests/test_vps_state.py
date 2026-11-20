"""Tests for skills/vps-state/vps-state, hooks/vps-state-hook and the verify skill.

Every run is fed fixtures under tests/fixtures/vps-state, never this host, so the
answers are the same on GitHub's runners as here. Fixtures hold real /proc files.
"""

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "vps-state" / "vps-state"
HOOK = ROOT / "hooks" / "vps-state-hook"
VERIFY = ROOT / ".claude" / "skills" / "verify-vps-state"
VERIFY_RUN = VERIFY / "run"
FIX = ROOT / "tests" / "fixtures" / "vps-state"

# A Claude Code Bash shell inherits a PATH with no ~/.local/bin, so a bare
# command name exits 127 there. These are the files that tell a chat what to type.
DOCS = [ROOT / "skills" / "vps-state" / "SKILL.md", VERIFY / "SKILL.md"] + sorted(
    (VERIFY / "features").glob("*.md"))
CLAUDE_BASH_PATH = "/usr/bin:/bin"

GB = 1024 ** 3
MB = 1024
CORES = 18


def load_script():
    loader = importlib.machinery.SourceFileLoader("vps_state", str(SCRIPT))
    spec = importlib.util.spec_from_loader("vps_state", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_verify_run():
    loader = importlib.machinery.SourceFileLoader("verify_vps_state_run", str(VERIFY_RUN))
    spec = importlib.util.spec_from_loader("verify_vps_state_run", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def fixture_env(name, home):
    case = FIX / name
    env = dict(os.environ)
    env["VPS_STATE_PROC"] = str(case / "proc")
    env["VPS_STATE_CORES"] = str(CORES)  # a fixture must mean the same on any host
    env["HOME"] = str(home)
    return env


def documented_bin(text):
    """The vps-state command a doc tells a chat to type, exactly as written."""
    for span in re.findall(r"`([^`\n]+)`", text):
        token = span.split()[0]
        if token.strip("\"'").endswith("vps-state"):
            return token
    return None


def bare_commands(text):
    """Code spans that start with the bare command name, so they need PATH."""
    found = []
    for span in re.findall(r"`([^`\n]+)`", text):
        token = span.split()[0]
        if token.strip("\"'") == "vps-state":
            found.append(span)
    return found


def cli(name, *args, home=None, timeout=60):
    home = home or pathlib.Path(tempfile.mkdtemp(prefix="vps-state-home-"))
    case = FIX / name
    cmd = [sys.executable, str(SCRIPT), "--ps-file", str(case / "ps.txt"), "--no-cleanup"]
    statvfs = case / "statvfs.json"
    if statvfs.exists():
        cmd += ["--statvfs-json", str(statvfs)]
    cmd += list(args)
    return subprocess.run(
        cmd, env=fixture_env(name, home), capture_output=True, text=True, timeout=timeout
    )


def facts_of(name):
    module = load_script()
    case = FIX / name
    statvfs = case / "statvfs.json"
    facts = module.collect(
        str(case / "proc"),
        ps_file=str(case / "ps.txt"),
        statvfs_json=str(statvfs) if statvfs.exists() else None,
        cores=CORES,
    )
    return module, facts


def write_proc(root, load5, avail_kb, cpu60=10.0, io60=1.0, mem60=0.1,
               free=400 * GB, total=678 * GB):
    """A minimal fake /proc for the grid: load and memory are what vary."""
    proc = pathlib.Path(root) / "proc"
    (proc / "pressure").mkdir(parents=True, exist_ok=True)
    (proc / "sys" / "kernel" / "pty").mkdir(parents=True, exist_ok=True)
    (proc / "sys" / "fs").mkdir(parents=True, exist_ok=True)
    (proc / "loadavg").write_text("{:.2f} {:.2f} {:.2f} 3/4000 900001\n".format(load5, load5, load5))
    (proc / "meminfo").write_text(
        "MemTotal:       98873664 kB\nMemAvailable:   {} kB\n".format(avail_kb))
    for name, some, full in (("cpu", cpu60, 0.0), ("io", io60 * 2, io60), ("memory", mem60, mem60)):
        (proc / "pressure" / name).write_text(
            "some avg10={0:.2f} avg60={1:.2f} avg300={1:.2f} total=1\n"
            "full avg10={2:.2f} avg60={2:.2f} avg300={2:.2f} total=1\n".format(some, cpu60, full))
    (proc / "sys" / "kernel" / "pty" / "nr").write_text("20\n")
    (proc / "sys" / "kernel" / "pty" / "max").write_text("4096\n")
    (proc / "sys" / "fs" / "file-nr").write_text("21000\t0\t9223372036854775807\n")
    (proc / "sys" / "kernel" / "pid_max").write_text("4194304\n")
    ps = pathlib.Path(root) / "ps.txt"
    ps.write_text(
        "    PID    PPID   RSS %CPU ELAPSED STAT COMMAND\n"
        "   1000       1 512000  1.0    3600 Ss   claude\n"
        "   1001       1 800000  9.0     600 Rl   claude -p \"work\"\n")
    disk = pathlib.Path(root) / "statvfs.json"
    disk.write_text(json.dumps({"path": "/", "total": total, "free": free,
                                "files_total": 91619328, "files_free": 74940760}))
    return str(proc), str(ps), str(disk)


class FixtureVerdicts(unittest.TestCase):
    def test_fixtures_exist(self):
        for name in ("add", "careful", "hold-cpu", "hold-disk", "hold-mem", "broken",
                     "real-2026-11-20"):
            self.assertTrue((FIX / name).is_dir(), name)

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK), SCRIPT)

    def test_add_fixture_is_add_for_both(self):
        proc = cli("add", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"]["worker"], "ADD")
        self.assertEqual(data["verdict"]["chat"], "ADD")
        self.assertEqual(data["reasons"]["worker"], [])

    def test_careful_fixture_starts_at_most_one(self):
        data = json.loads(cli("careful", "--json").stdout)
        self.assertEqual(data["verdict"]["worker"], "CAREFUL")
        self.assertIn("load5", " ".join(data["reasons"]["worker"]))
        self.assertEqual(data["verdict"]["chat"], "ADD")

    def test_hold_cpu_fixture(self):
        data = json.loads(cli("hold-cpu", "--json").stdout)
        self.assertEqual(data["verdict"]["worker"], "HOLD")
        self.assertEqual(data["verdict"]["chat"], "HOLD")
        self.assertIn("cpu", " ".join(data["reasons"]["worker"]).lower())

    def test_hold_disk_fixture(self):
        data = json.loads(cli("hold-disk", "--json").stdout)
        self.assertEqual(data["verdict"]["worker"], "HOLD")
        self.assertIn("disk", " ".join(data["reasons"]["worker"]).lower())

    def test_hold_mem_fixture(self):
        data = json.loads(cli("hold-mem", "--json").stdout)
        self.assertEqual(data["verdict"]["worker"], "HOLD")
        self.assertEqual(data["verdict"]["chat"], "HOLD")

    def test_real_capture_holds(self):
        data = json.loads(cli("real-2026-11-20", "--json", home=pathlib.Path(tempfile.mkdtemp())).stdout)
        self.assertEqual(data["verdict"]["worker"], "HOLD")
        self.assertEqual(data["verdict"]["chat"], "HOLD")
        self.assertGreater(data["facts"]["load"]["load5"], 20)
        self.assertEqual(data["facts"]["cores"], CORES)
        self.assertGreaterEqual(data["processes"]["kinds"]["worker"]["count"], 5)
        self.assertGreaterEqual(data["processes"]["kinds"]["chat"]["count"], 1)
        self.assertIsNotNone(data["processes"]["median_rss_mb"]["chat"])
        self.assertIsNotNone(data["processes"]["median_rss_mb"]["worker"])


class ExitCodes(unittest.TestCase):
    def test_can_launch_add_exits_0(self):
        self.assertEqual(cli("add", "--can-launch", "worker").returncode, 0)
        self.assertEqual(cli("add", "--can-launch", "chat").returncode, 0)

    def test_can_launch_careful_exits_1(self):
        self.assertEqual(cli("careful", "--can-launch", "worker").returncode, 1)

    def test_can_launch_hold_exits_2(self):
        self.assertEqual(cli("hold-cpu", "--can-launch", "worker").returncode, 2)
        self.assertEqual(cli("hold-mem", "--can-launch", "chat").returncode, 2)

    def test_can_launch_broken_probe_exits_3(self):
        self.assertEqual(cli("broken", "--can-launch", "worker").returncode, 3)
        self.assertEqual(cli("broken", "--can-launch", "chat").returncode, 3)

    def test_can_launch_bad_argument(self):
        self.assertEqual(cli("add", "--can-launch", "banana").returncode, 3)


class RunnerGate(unittest.TestCase):
    """ADD worker must be exactly the fleet runner gate, over load and memory."""

    @staticmethod
    def runner_gate(load5, avail_kb):
        # /home/valentin/.local/share/house-rules/fleet/runner, green()
        return load5 / CORES < 1.0 and int(avail_kb / 1048576) > 24

    def test_grid_matches_runner_gate(self):
        module = load_script()
        loads = [0.0, 5.0, 10.0, 17.9, 18.0, 18.1, 20.0, 24.0, 27.0, 30.0]
        mems = [8 * 1024 * MB, 12 * 1024 * MB, 23 * 1024 * MB, 24 * 1024 * MB,
                24 * 1024 * MB + 512, 25 * 1024 * MB, 26 * 1024 * MB,
                40 * 1024 * MB, 76 * 1024 * MB]
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-grid-"))
        for load5 in loads:
            for avail in mems:
                proc, ps, disk = write_proc(tmp, load5, avail)
                facts = module.collect(proc, ps_file=ps, statvfs_json=disk, cores=CORES)
                result = module.evaluate(facts)
                with self.subTest(load5=load5, avail_gb=round(avail / 1048576, 3)):
                    self.assertEqual(result["verdict"]["worker"] == "ADD",
                                     self.runner_gate(load5, avail))

    def test_memory_boundary_is_the_runners_integer_gb(self):
        module = load_script()
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-boundary-"))
        for avail_kb, expect in ((24 * 1048576, "CAREFUL"),
                                 (24 * 1048576 + 512, "CAREFUL"),
                                 (25 * 1048576 - 1, "CAREFUL"),
                                 (25 * 1048576, "ADD")):
            proc, ps, disk = write_proc(tmp, 4.0, avail_kb)
            got = module.evaluate(module.collect(proc, ps_file=ps, statvfs_json=disk, cores=CORES))
            with self.subTest(avail_kb=avail_kb):
                self.assertEqual(got["verdict"]["worker"], expect)

    def test_pressure_and_disk_can_block_add_below_the_cpu_gate(self):
        module = load_script()
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-pressure-"))
        for kwargs in ({"cpu60": 26.0}, {"io60": 6.0},
                       {"free": 70 * GB}, {"free": 60 * GB, "total": 678 * GB}):
            proc, ps, disk = write_proc(tmp, 4.0, 70 * 1024 * MB, **kwargs)
            got = module.evaluate(module.collect(proc, ps_file=ps, statvfs_json=disk, cores=CORES))
            with self.subTest(**kwargs):
                self.assertNotEqual(got["verdict"]["worker"], "ADD")
        # Memory pressure binds the chat answer, not the worker one.
        proc, ps, disk = write_proc(tmp, 4.0, 70 * 1024 * MB, mem60=3.0)
        got = module.evaluate(module.collect(proc, ps_file=ps, statvfs_json=disk, cores=CORES))
        self.assertNotEqual(got["verdict"]["chat"], "ADD")
        self.assertEqual(got["verdict"]["worker"], "ADD")


class CoreSeam(unittest.TestCase):
    """A fixture that says 18 cores must say 18 on a 4 core runner too."""

    def test_env_override_wins(self):
        module, facts = facts_of("add")
        self.assertEqual(facts["cores"], CORES)
        self.assertAlmostEqual(facts["load"]["ratio"], round(4.0 / CORES, 3), places=3)

    def test_garbage_override_falls_back_to_the_live_count(self):
        module = load_script()
        old = os.environ.get("VPS_STATE_CORES")
        os.environ["VPS_STATE_CORES"] = "banana"
        try:
            self.assertEqual(module.resolve_cores(), os.cpu_count() or 1)
        finally:
            if old is None:
                os.environ.pop("VPS_STATE_CORES", None)
            else:
                os.environ["VPS_STATE_CORES"] = old


class StatusFile(unittest.TestCase):
    PATTERN = re.compile(r"^(add|steady|hold) load5=\d+\.\d{2} cores=\d+$")

    def line_for(self, name):
        home = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-status-"))
        proc = cli(name, "--json", home=home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = home / ".local" / "state" / "vps-load" / "status"
        self.assertTrue(status.exists(), status)
        return status.read_text().strip()

    def test_written_in_the_format_the_runner_reads(self):
        self.assertEqual(self.line_for("add"), "add load5=4.00 cores=18")
        self.assertTrue(self.line_for("careful").startswith("steady load5=25.00"))
        self.assertTrue(self.line_for("hold-cpu").startswith("hold load5=6.00"))
        self.assertTrue(self.line_for("hold-mem").startswith("hold load5=2.00"))

    def test_no_write_leaves_the_file_alone(self):
        home = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-nowrite-"))
        status = home / ".local" / "state" / "vps-load" / "status"
        status.parent.mkdir(parents=True)
        status.write_text("add load5=7.55 cores=18\n")
        proc = cli("hold-cpu", "--no-write", home=home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(status.read_text(), "add load5=7.55 cores=18\n")

    def test_brief_and_can_launch_write_too(self):
        home = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-brief-"))
        cli("careful", "--brief", home=home)
        status = home / ".local" / "state" / "vps-load" / "status"
        self.assertTrue(status.read_text().startswith("steady"))


class Output(unittest.TestCase):
    def test_brief_is_one_line(self):
        proc = cli("hold-cpu", "--brief")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, proc.stdout)
        self.assertLess(len(lines[0]), 200)
        self.assertTrue(lines[0].startswith("HOLD worker"), lines[0])

    def test_human_block_leads_with_the_verdict(self):
        proc = cli("real-2026-11-20")
        lines = proc.stdout.splitlines()
        self.assertTrue(lines[0].startswith("HOLD worker"), lines[0])
        self.assertGreaterEqual(len(lines), 8)
        self.assertIn("Clean up your own", proc.stdout)

    def test_cleanup_lists_tools_and_the_rule(self):
        proc = cli("add")
        for needle in ("/clean-up", "host-disk-sweep", "tmp-cleanup", "never another session"):
            self.assertIn(needle, proc.stdout)

    def test_json_carries_the_same_numbers(self):
        data = json.loads(cli("real-2026-11-20", "--json").stdout)
        facts = data["facts"]
        self.assertGreater(facts["load"]["load5"], 0)
        self.assertAlmostEqual(facts["load"]["load5"] / facts["cores"],
                               facts["load"]["ratio"], places=3)
        self.assertGreater(facts["memory"]["avail_gb"], 0)
        self.assertGreater(facts["disk"]["free_gb"], 0)
        self.assertIn("unknown", facts)
        self.assertIsInstance(facts["unknown"], list)
        self.assertEqual(len(data["processes"]["top_cpu"]), 8)
        self.assertEqual(len(data["processes"]["top_rss"]), 8)

    def test_headroom_divides_by_the_median_rss(self):
        data = json.loads(cli("add", "--json").stdout)
        headroom = data["headroom"]
        self.assertEqual(headroom["reserve_gb"], 24.0)
        self.assertGreater(headroom["workers"], 0)
        self.assertGreater(headroom["chats"], 0)
        self.assertAlmostEqual(
            headroom["workers"],
            int((data["facts"]["memory"]["avail_kb"] - 24 * 1048576)
                // (data["processes"]["median_rss_mb"]["worker"] * 1024)))


class BrokenProbes(unittest.TestCase):
    def test_missing_pressure_files_say_unknown(self):
        proc = cli("broken")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("unknown", proc.stdout.lower())
        self.assertNotIn("Traceback", proc.stderr)
        data = json.loads(cli("broken", "--json").stdout)
        self.assertTrue(data["facts"]["unknown"])
        self.assertNotEqual(data["verdict"]["worker"], "ADD")
        self.assertNotEqual(data["verdict"]["chat"], "ADD")

    def test_garbage_numbers_do_not_crash(self):
        module, facts = facts_of("broken")
        self.assertIsNone(facts["load"])
        self.assertIsNone(facts["memory"])
        self.assertIn("load", facts["unknown"])
        result = module.evaluate(facts)
        self.assertEqual(result["headroom"]["chats"], 0)
        self.assertEqual(result["headroom"]["workers"], 0)

    def test_ps_failure_is_unknown_not_a_crash(self):
        home = pathlib.Path(tempfile.mkdtemp())
        case = FIX / "add"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--ps-file", "/nonexistent/ps.txt",
             "--statvfs-json", str(case / "statvfs.json"), "--json", "--no-write"],
            env=fixture_env("add", home), capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("processes", data["facts"]["unknown"])
        self.assertIsNone(data["processes"])

    def test_statvfs_json_that_is_not_an_object_is_unknown(self):
        home = pathlib.Path(tempfile.mkdtemp())
        case = FIX / "add"
        for payload in ("[1, 2]", '"hello"', "3", "null"):
            disk = home / "statvfs.json"
            disk.write_text(payload)
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--ps-file", str(case / "ps.txt"),
                 "--statvfs-json", str(disk), "--json", "--no-write"],
                env=fixture_env("add", home), capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, payload + proc.stderr)
            self.assertNotIn("Traceback", proc.stderr, payload)
            data = json.loads(proc.stdout)
            self.assertIsNone(data["facts"]["disk"], payload)
            self.assertIn("disk", data["facts"]["unknown"], payload)

    def test_unreadable_proc_root_is_unknown(self):
        home = pathlib.Path(tempfile.mkdtemp())
        env = dict(os.environ)
        env["VPS_STATE_PROC"] = "/nonexistent/proc"
        env["HOME"] = str(home)
        proc = subprocess.run([sys.executable, str(SCRIPT), "--ps-file", "/nonexistent/ps.txt",
                               "--brief", "--no-write"],
                              env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("unknown", proc.stdout.lower())


class SessionHook(unittest.TestCase):
    def test_hook_is_executable(self):
        self.assertTrue(os.access(HOOK, os.X_OK), HOOK)

    def test_hook_prints_one_server_line_fast(self):
        home = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-hook-"))
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["PATH"] = "/usr/bin:/bin"
        env.pop("VPS_STATE_PROC", None)
        start = time.monotonic()
        proc = subprocess.run([str(HOOK)], env=env, capture_output=True, text=True, timeout=30)
        elapsed = time.monotonic() - start
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertLess(elapsed, 3.0, "hook took {:.1f}s".format(elapsed))
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        server = [line for line in lines if line.startswith("Server: ")]
        self.assertEqual(len(server), 1, proc.stdout)
        self.assertIn("run vps-state before starting chats or workers", proc.stdout)
        self.assertTrue(server[0].strip() != "Server:", proc.stdout)

    def test_hook_exits_0_with_no_script_and_prints_nothing(self):
        home = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-hook-"))
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["PATH"] = "/usr/bin:/bin"
        env["VPS_STATE_BIN"] = "/nonexistent/vps-state"
        proc = subprocess.run([str(HOOK)], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")


class ClaudeBashPath(unittest.TestCase):
    """Live proof 2026-11-20: a Claude Code Bash shell's PATH has no ~/.local/bin.

    The test runs what the docs tell a chat to type inside the same minimal
    environment, with a temporary HOME whose ~/.local/bin links this checkout.
    """

    def installed_home(self):
        home = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-claude-path-"))
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".local" / "bin" / "vps-state").symlink_to(SCRIPT)
        return home

    def run_in_minimal_env(self, argv, home):
        env = {"HOME": str(home), "PATH": CLAUDE_BASH_PATH}
        return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)

    def test_documented_command_runs_without_127(self):
        skill = (ROOT / "skills" / "vps-state" / "SKILL.md").read_text()
        command = documented_bin(skill)
        self.assertIsNotNone(command, "skills/vps-state/SKILL.md names no vps-state command")
        self.assertNotEqual(
            command, "vps-state",
            "the skill tells chats to run a bare vps-state; a Claude Code Bash shell "
            "has no ~/.local/bin on PATH, so it exits 127")
        home = self.installed_home()
        for args in (["--brief"], ["--can-launch", "worker"], ["--can-launch", "chat"]):
            with self.subTest(args=args):
                proc = self.run_in_minimal_env(
                    ["bash", "-c", command + " " + " ".join(args)], home)
                self.assertNotEqual(proc.returncode, 127, proc.stderr)
                self.assertNotIn("command not found", proc.stderr)
                self.assertNotIn("No such file or directory", proc.stderr)
                if args == ["--brief"]:
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertIn(proc.stdout.split()[0], ("ADD", "CAREFUL", "HOLD"),
                                  proc.stdout)
                else:
                    self.assertIn(proc.returncode, (0, 1, 2, 3), proc.stderr)

    def test_hook_prints_its_line_without_127(self):
        home = self.installed_home()
        proc = self.run_in_minimal_env([str(HOOK)], home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Server: ", proc.stdout)
        self.assertNotIn("command not found", proc.stderr)
        self.assertNotIn("No such file or directory", proc.stderr)

    def test_docs_name_no_bare_command(self):
        for path in DOCS:
            for number, line in enumerate(path.read_text().splitlines(), 1):
                for span in bare_commands(line):
                    self.fail("{}:{}: `{}` needs ~/.local/bin on PATH; a Claude Code "
                              "Bash shell has it not, so name the command by full "
                              "path".format(path.relative_to(ROOT), number, span))


class VerifySkillPaths(unittest.TestCase):
    def test_run_resolves_the_script_and_the_hook_by_absolute_path(self):
        run_skill = load_verify_run()
        for path in (run_skill.DEFAULT_SCRIPT, run_skill.HOOK):
            self.assertTrue(path.is_absolute(), "{} is not absolute".format(path))
            self.assertTrue(path.is_file(), "{} is missing".format(path))
        self.assertEqual(run_skill.DEFAULT_SCRIPT.resolve(), SCRIPT.resolve())
        self.assertEqual(run_skill.HOOK.resolve(), HOOK.resolve())


class Install(unittest.TestCase):
    def test_install_links_the_script_and_the_hook(self):
        home = pathlib.Path(tempfile.mkdtemp(prefix="vps-state-install-"))
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["VSTACK_DIR"] = str(home / ".local" / "share" / "vstack")
        # The install guard only links from ~/.local/share/vstack (VSTA-47).
        env["VSTACK_INSTALL_ANYWHERE"] = "1"
        proc = subprocess.run([str(ROOT / "install")], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        link = home / ".local" / "bin" / "vps-state"
        self.assertTrue(link.is_symlink(), link)
        self.assertEqual(link.resolve(), SCRIPT.resolve())
        hook = home / ".claude" / "hooks" / "vps-state-hook"
        self.assertTrue(hook.is_symlink(), hook)
        self.assertEqual(hook.resolve(), HOOK.resolve())


class VerifySkillGrade(unittest.TestCase):
    def setUp(self):
        self.run_skill = load_verify_run()

    def reported(self, **overrides):
        data = {"load5": 30.0, "cores": 18, "mem_avail_gb": 75.0,
                "disk_free_gb": 97.0, "disk_used_pct": 86.0}
        data.update(overrides)
        return data

    def test_consistent_numbers_pass(self):
        live = self.reported(load5=30.5, mem_avail_gb=74.0, disk_free_gb=96.0)
        checks = self.run_skill.cross_check(self.reported(), live)
        self.assertTrue(checks, checks)
        self.assertEqual(self.run_skill.grade(checks), "PASS", checks)

    def test_wrong_numbers_fail(self):
        for live in (self.reported(load5=45.0), self.reported(cores=16),
                     self.reported(mem_avail_gb=20.0), self.reported(disk_used_pct=96.0),
                     self.reported(disk_free_gb=10.0)):
            with self.subTest(live=live):
                checks = self.run_skill.cross_check(self.reported(), live)
                self.assertEqual(self.run_skill.grade(checks), "FAIL", checks)

    def test_missing_live_number_fails(self):
        checks = self.run_skill.cross_check(self.reported(), self.reported(mem_avail_gb=None))
        self.assertEqual(self.run_skill.grade(checks), "FAIL", checks)

    def test_exit_code_must_match_the_verdict(self):
        self.assertTrue(self.run_skill.exit_codes_ok({"worker": "HOLD", "chat": "CAREFUL"},
                                                     {"worker": 2, "chat": 1}))
        self.assertFalse(self.run_skill.exit_codes_ok({"worker": "HOLD", "chat": "CAREFUL"},
                                                      {"worker": 0, "chat": 1}))
        self.assertFalse(self.run_skill.exit_codes_ok({"worker": "ADD", "chat": "ADD"},
                                                      {"worker": 0, "chat": None}))


class WorkflowConcurrency(unittest.TestCase):
    """A session-start budget check flags both workflows as missing concurrency."""

    def test_checks_and_column_contract_cancel_superseded_runs(self):
        for name, group in (("checks", "checks"), ("column-contract", "column-contract")):
            text = (ROOT / ".github" / "workflows" / (name + ".yml")).read_text()
            self.assertIn("concurrency:", text, name)
            self.assertIn("cancel-in-progress: true", text, name)
            self.assertIn("group: " + group + "-${{ github.event.pull_request.number || github.ref }}",
                          text, name)
            permissions = text.index("permissions:")
            self.assertGreater(text.index("concurrency:"), permissions, name)


if __name__ == "__main__":
    unittest.main()
