#!/usr/bin/env python3
"""Tests for skills/fleet-report/fleet-report (fixtures only; never reads real ~/.claude)."""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/fleet-report/fleet-report"
FIXTURES = ROOT / "tests/fixtures/fleet-report"


def load_module():
    loader = importlib.machinery.SourceFileLoader("fleet_report", str(SCRIPT))
    spec = importlib.util.spec_from_loader("fleet_report", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FleetReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = dict(os.environ)
        self.env["FLEET_REPORT_HOME"] = str(self.home)
        self.env["FLEET_REPORT_VSTACK"] = str(ROOT)
        os.makedirs(self.home / ".claude/projects", exist_ok=True)

    def write_transcript(self, cwd: str, sid: str, text: str) -> Path:
        encoded = load_module().encode_cwd(cwd)
        project = self.home / ".claude/projects" / encoded
        project.mkdir(parents=True, exist_ok=True)
        path = project / f"{sid}.jsonl"
        path.write_text(text, encoding="utf-8")
        return path

    def fake_version_script(self, line: str) -> Path:
        script = self.home / "version.sh"
        script.write_text(
            f"""#!/bin/sh
echo "{line}"
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        self.env["FLEET_REPORT_VERSION_SH"] = str(script)
        return script

    def fake_loop_state(self, code: int) -> Path:
        script = self.home / "loop-state.py"
        script.write_text(
            f"""#!/usr/bin/env python3
import sys
print("armed" if {code} == 0 else "not armed")
sys.exit({code})
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        self.env["FLEET_REPORT_LOOP_STATE"] = str(script)
        return script

    def fake_pstack_diff(self, exit_code: int, extras: int) -> Path:
        script = self.home / "pstack-diff.py"
        body = "\n".join(f"EXTRA workflow: job-{i}" for i in range(extras))
        script.write_text(
            f"""#!/usr/bin/env python3
import sys
print({body!r})
sys.exit({exit_code})
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        self.env["FLEET_REPORT_PSTACK_DIFF"] = str(script)
        return script

    def run_report(self, sessions: list[dict], *, extra_env: dict | None = None) -> dict:
        sessions_path = self.home / "sessions.json"
        sessions_path.write_text(json.dumps(sessions), encoding="utf-8")
        env = dict(self.env)
        env["FLEET_REPORT_SESSIONS_JSON"] = str(sessions_path)
        if extra_env:
            env.update(extra_env)
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_latest_is_ok(self):
        mod = load_module()
        self.fake_version_script("valentin-mode v5 (latest)")
        self.fake_loop_state(0)
        self.fake_pstack_diff(0, 0)
        repo = self.home / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.write_transcript(
            str(repo),
            "sid-ok",
            '{"message":{"content":"valentin-mode v5 (latest)"}}\n',
        )

        rows = self.run_report(
            [dict(name="Demo", harness="claude", cwd=str(repo), sid="sid-ok", tmux="live-demo")]
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["verdict"], "OK", row)
        self.assertIn("v5", row["loaded"])
        self.assertEqual(row["latest"], "v5")
        self.assertEqual(row["extra_count"], 0)
        self.assertEqual(mod.verdict("claude", row["loaded"], 5, 5, 0, "exit 0", 0)[0], "OK")

    def test_behind_version(self):
        self.fake_version_script("valentin-mode v6 (latest)")
        self.fake_loop_state(0)
        self.fake_pstack_diff(0, 0)
        self.write_transcript(
            "/work/behind",
            "sid-behind",
            (
                '{"message":{"content":"valentin-mode v5 (latest)"}}\n'
                '{"message":{"content":"valentin-mode v5, latest is v6 (updates itself within 10 minutes)"}}\n'
            ),
        )
        rows = self.run_report(
            [dict(name="Behind", harness="claude", cwd="/work/behind", sid="sid-behind", tmux="live-behind")]
        )
        row = rows[0]
        self.assertEqual(row["verdict"], "BEHIND", row)
        self.assertIn("v5", row["loaded"])
        self.assertIn("v6", row["loaded"])

    def test_never_loaded_fails(self):
        self.fake_version_script("valentin-mode v3 (latest)")
        self.fake_loop_state(0)
        self.fake_pstack_diff(0, 0)
        self.write_transcript("/work/empty", "sid-empty", '{"message":{"content":"hello"}}\n')
        rows = self.run_report(
            [dict(name="Empty", harness="claude", cwd="/work/empty", sid="sid-empty", tmux="live-empty")]
        )
        row = rows[0]
        self.assertEqual(row["loaded"], "never loaded")
        self.assertEqual(row["verdict"], "FAILING", row)
        self.assertIn("never loaded", row["reason"])

    def test_non_claude_no_transcript(self):
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(0)
        self.fake_pstack_diff(0, 0)
        rows = self.run_report(
            [dict(name="Codex", harness="codex", cwd="/work/codex", sid="", tmux="live-codex")]
        )
        row = rows[0]
        self.assertEqual(row["loaded"], "unknown (no transcript)")
        self.assertEqual(row["verdict"], "OK", row)

    def test_pstack_diff_extra_fails(self):
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(0)
        self.fake_pstack_diff(1, 2)
        repo = self.home / "extras"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.write_transcript(
            str(repo),
            "sid-extra",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [dict(name="Extra", harness="claude", cwd=str(repo), sid="sid-extra", tmux="live-extra")]
        )
        row = rows[0]
        self.assertEqual(row["verdict"], "FAILING", row)
        self.assertEqual(row["extra_count"], 2)
        self.assertIn("EXTRA", row["reason"])

    def test_parse_roster_line(self):
        mod = load_module()
        line = mod.parse_roster_lines("Alpha (live-a, claude, ~/projects/alpha)\n3 live sessions")
        self.assertEqual(len(line), 1)
        self.assertEqual(line[0]["name"], "Alpha")
        self.assertEqual(line[0]["harness"], "claude")

    def test_script_always_exits_zero(self):
        done = subprocess.run([sys.executable, str(SCRIPT)], env=self.env, check=False)
        self.assertEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()