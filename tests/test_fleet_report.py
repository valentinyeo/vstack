#!/usr/bin/env python3
"""Tests for skills/fleet-report/fleet-report (fixtures only; never reads real ~/.claude)."""

import importlib.machinery
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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
if {code} == 4:
    print("paused until 2027-01-15T14:00:00Z: Claude budget pause")
else:
    print("armed" if {code} == 0 else "not armed")
sys.exit({code})
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        self.env["FLEET_REPORT_LOOP_STATE"] = str(script)
        return script

    def fake_pstack_diff(self, exit_code: int, extras: int, gaps: int = 0, behind: int | None = None) -> Path:
        lines = [f"EXTRA workflow: job-{i}" for i in range(extras)]
        lines.extend(f"GAP verify-skill: gap-{i}" for i in range(gaps))
        if behind:
            lines.insert(0, f"WARN checkout is {behind} commits behind origin/main; results may show extras already removed upstream")
        body = "\n".join(lines)
        script = self.home / "pstack-diff.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"print({json.dumps(body)})\n"
            f"sys.exit({exit_code})\n",
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

    def test_missing_hook_is_visible_and_settings_stay_unchanged(self):
        self.fake_version_script("valentin-mode v5 (latest)")
        self.fake_loop_state(0)
        self.fake_pstack_diff(0, 0)
        settings = self.home / '.claude/settings.json'
        settings.write_text((ROOT / 'tests/fixtures/hook-paths/skill-update-missing.json').read_text())
        before = settings.read_bytes()
        rows = self.run_report([dict(name='Demo', harness='codex', cwd=str(self.home / 'repo'))])
        self.assertEqual(rows[0]['hook_paths'], 'MISSING')
        self.assertIn('HOOKS MISSING', rows[0]['verdict'])
        self.assertIn('skill-update.py', rows[0]['hook_details'])
        mod = load_module()
        self.assertIn('skill-update.py', mod.format_table(rows))
        page = self.home / 'report.html'
        mod.write_html(page, rows)
        self.assertIn('skill-update.py', page.read_text())
        self.assertIn('reinstall vstack', page.read_text())
        self.assertEqual(settings.read_bytes(), before)

    def test_inne_sessions_are_not_inspected(self):
        self.fake_version_script("valentin-mode v5 (latest)")
        rows = self.run_report([dict(name='Not ours', harness='codex', cwd='/home/inne/project')])
        self.assertEqual(rows, [])

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
        self.assertEqual(row["gap_count"], 0)
        v, reason, action = mod.verdict(
            "claude", row["loaded"], 5, 5, 0, False, 0, 0, None, None, False, False, False, None
        )
        self.assertEqual(v, "OK")
        self.assertEqual(action, "")

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
        self.assertIn("updates on its next message", row["reason"])
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
        self.assertEqual(row["verdict"], "NO VALENTIN-MODE", row)
        self.assertIn("/valentin-mode", row["action"])

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

    def test_pstack_diff_extra_fix(self):
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
        self.assertEqual(row["verdict"], "FIX", row)
        self.assertEqual(row["extra_count"], 2)
        self.assertIn("EXTRA", row["self_check"])
        self.assertIn("PR", row["action"])

    def test_pstack_gap_only(self):
        mod = load_module()
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(0)
        self.fake_pstack_diff(1, 0, gaps=2)
        repo = self.home / "gaps"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.write_transcript(
            str(repo),
            "sid-gap",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [dict(name="Gaps", harness="claude", cwd=str(repo), sid="sid-gap", tmux="live-gaps")]
        )
        row = rows[0]
        self.assertEqual(row["verdict"], "GAPS", row)
        self.assertEqual(row["gap_count"], 2)
        extras, gaps, behind, parsed = mod.parse_pstack_stdout("GAP a\nGAP b\n")
        self.assertEqual((extras, gaps, behind, parsed), (0, 2, None, True))

    def test_loop_off_only_with_board_line(self):
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(1)
        self.fake_pstack_diff(0, 0)
        repo = self.home / "boarded"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "CLAUDE.md").write_text("Hypertask board: 15, label: Demo\n", encoding="utf-8")
        self.write_transcript(
            str(repo),
            "sid-loop",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [dict(name="Looper", harness="claude", cwd=str(repo), sid="sid-loop", tmux="live-loop")]
        )
        row = rows[0]
        self.assertIn("LOOP OFF", row["verdict"])
        self.assertIn("/board-drain", row["action"])

    def test_a_paused_chat_is_not_reported_as_looped_off(self):
        """VSTA-309: a chat told to go idle shows PAUSED, not LOOP OFF and a re-arm action."""
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(4)
        self.fake_pstack_diff(0, 0)
        repo = self.home / "paused"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "CLAUDE.md").write_text("Hypertask board: 15, label: Demo\n", encoding="utf-8")
        self.write_transcript(
            str(repo),
            "sid-paused",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [dict(name="Pauser", harness="claude", cwd=str(repo), sid="sid-paused",
                  tmux="live-paused")]
        )
        row = rows[0]
        self.assertIn("PAUSED", row["verdict"])
        self.assertNotIn("LOOP OFF", row["verdict"])
        self.assertNotIn("/board-drain", row["action"])

    def test_loop_not_checked_without_board_line(self):
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(1)
        self.fake_pstack_diff(0, 0)
        repo = self.home / "noboard"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.write_transcript(
            str(repo),
            "sid-nb",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [dict(name="NoBoard", harness="claude", cwd=str(repo), sid="sid-nb", tmux="live-nb")]
        )
        row = rows[0]
        self.assertEqual(row["verdict"], "OK", row)

    def test_a_dead_watcher_shows_its_time(self):
        """VSTA-151: the report lists a chat whose board watcher died, without messaging it."""
        self.fake_version_script("valentin-mode v5 (latest)")
        self.fake_pstack_diff(0, 0)
        repo = self.home / "watched"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "CLAUDE.md").write_text("Hypertask board: 13734, label: Looper\n", encoding="utf-8")
        self.write_transcript(
            str(repo),
            "sid-watch",
            '{"message":{"content":"valentin-mode v5 (latest)"}}\n',
        )
        state = self.home / "board-drain-state"
        state.mkdir()
        seen = time.time() - 3 * 3600
        stamp = lambda moment: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(moment))
        (state / "looper.json").write_text(json.dumps({
            "name": "Looper", "every": "6h", "armed_at": stamp(time.time() - 86400),
            "expires_at": stamp(time.time() + 6 * 86400), "job": "efcdac5d",
            "owner_pid": os.getpid(), "host": socket.gethostname(),
            "board": 13734, "label": "Looper", "watch_pid": None,
            "watch_started": stamp(seen), "watch_beat": stamp(seen), "watch_every": 180,
        }))
        rows = self.run_report(
            [dict(name="Looper", harness="claude", cwd=str(repo), sid="sid-watch",
                  tmux="live-looper")],
            extra_env={"BOARD_DRAIN_STATE_DIR": str(state)},
        )
        row = rows[0]
        self.assertEqual(row["watcher"], f"dead since {stamp(seen)}", row)
        self.assertIn(f"dead since {stamp(seen)}", row["board"])
        self.assertIn("WATCHER DEAD", row["verdict"])
        self.assertIn("/board-drain", row["action"])
        table = load_module().format_table(rows)
        self.assertIn("WATCHER", table)
        self.assertIn(f"dead since {stamp(seen)}", table)

    def test_dead_watcher_shows_whether_notice_went_out(self):
        """VSTA-151 round 2: fleet report shows dead since <time> and whether the notice went out."""
        self.fake_version_script("valentin-mode v5 (latest)")
        self.fake_pstack_diff(0, 0)
        repo = self.home / "watched-notice"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "CLAUDE.md").write_text("Hypertask board: 13556, label: Demo\n", encoding="utf-8")
        for sid in ("sid-sent", "sid-pending", "sid-ok"):
            self.write_transcript(
                str(repo), sid, '{"message":{"content":"valentin-mode v5 (latest)"}}\n'
            )
        state = self.home / "board-drain-state"
        state.mkdir()
        now = time.time()
        stamp = lambda moment: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(moment))
        seen_a = stamp(now - 3600)
        sent_at = stamp(now - 2900)
        seen_b = stamp(now - 1800)
        base = {
            "every": "6h", "armed_at": stamp(now - 86400),
            "expires_at": stamp(now + 6 * 86400), "job": "efcdac5d",
            "owner_pid": os.getpid(), "host": socket.gethostname(),
            "board": 13556, "watch_every": 180,
        }
        (state / "notified-chat.json").write_text(json.dumps({
            **base, "name": "Notified Chat", "label": "Notified Chat",
            "watch_pid": None, "watch_started": seen_a, "watch_beat": seen_a,
            "dead_notice": {"at": sent_at, "since": seen_a, "via": "ntfy"},
        }))
        (state / "pending-chat.json").write_text(json.dumps({
            **base, "name": "Pending Chat", "label": "Pending Chat",
            "watch_pid": None, "watch_started": seen_b, "watch_beat": seen_b,
        }))
        (state / "alive-chat.json").write_text(json.dumps({
            **base, "name": "Alive Chat", "label": "Alive Chat",
            "watch_pid": os.getpid(), "watch_started": stamp(now), "watch_beat": stamp(now),
        }))
        rows = self.run_report(
            [
                dict(name="Notified Chat", harness="claude", cwd=str(repo), sid="sid-sent", tmux="live-a"),
                dict(name="Pending Chat", harness="claude", cwd=str(repo), sid="sid-pending", tmux="live-b"),
                dict(name="Alive Chat", harness="claude", cwd=str(repo), sid="sid-ok", tmux="live-c"),
            ],
            extra_env={"BOARD_DRAIN_STATE_DIR": str(state)},
        )
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Notified Chat"]["watcher"], f"dead since {seen_a}")
        self.assertEqual(by_name["Notified Chat"]["notice"], f"sent {sent_at} (ntfy)")
        self.assertEqual(by_name["Pending Chat"]["watcher"], f"dead since {seen_b}")
        self.assertEqual(by_name["Pending Chat"]["notice"], "not sent")
        self.assertEqual(by_name["Alive Chat"]["watcher"], "ok")
        self.assertEqual(by_name["Alive Chat"]["notice"], "-")
        mod = load_module()
        table = mod.format_table(rows)
        self.assertIn("NOTICE", table)
        self.assertIn(f"sent {sent_at} (ntfy)", table)
        self.assertIn("not sent", table)
        page = self.home / "report-notice.html"
        mod.write_html(page, rows)
        html_text = page.read_text()
        self.assertIn("<th>Notice</th>", html_text)
        self.assertIn(f"sent {sent_at} (ntfy)", html_text)
        self.assertIn("not sent", html_text)

    def test_parse_pstack_stdout_behind(self):
        mod = load_module()
        out = (
            "WARN checkout is 12 commits behind origin/main; x\n"
            "GAP verifier workflow: no job\n"
            "EXTRA workflow: foo\n"
        )
        self.assertEqual(mod.parse_pstack_stdout(out), (1, 1, 12, True))
        self.assertEqual(
            mod.format_self_check(1, 1, 12, upstream=True),
            "EXTRA 1 GAP 1 behind 12 (upstream)",
        )

    def test_verdict_stale_behind_ignores_local_extras(self):
        mod = load_module()
        v, reason, action = mod.verdict(
            "claude",
            "valentin-mode v4 (latest)",
            4,
            4,
            0,
            False,
            5,
            1,
            None,
            None,
            False,
            True,
            False,
            170,
        )
        self.assertEqual(v, "GAPS")
        self.assertNotIn("FIX", v)

    def test_format_self_check_fetch_failed_without_behind(self):
        mod = load_module()
        self.assertEqual(
            mod.format_self_check(1, 0, None, stale=True, fetch_failed=True),
            "EXTRA 1 GAP 0 (fetch failed)",
        )
        self.assertEqual(
            mod.format_self_check(None, None, None, stale=True, fetch_failed=True),
            "unparsed (fetch failed)",
        )

    def test_verdict_fetch_failed_uses_local_extras(self):
        mod = load_module()
        v, reason, action = mod.verdict(
            "claude",
            "valentin-mode v4 (latest)",
            4,
            4,
            0,
            False,
            1,
            0,
            None,
            None,
            False,
            True,
            True,
            3,
        )
        self.assertIn("FIX", v)
        self.assertNotIn("OK", v)
        self.assertIn("STALE", v)

    def test_json_upstream_counts_match_self_check(self):
        mod = load_module()
        self.fake_pstack_diff(1, 1, behind=3)
        bare = self.home / "bare-up.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        repo = self.home / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "f").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "f"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
        subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
        subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "main"], check=True)

        def fake_upstream(_cwd: str):
            return 0, 0, True

        original = mod.run_pstack_diff_upstream
        mod.run_pstack_diff_upstream = fake_upstream
        self.addCleanup(setattr, mod, "run_pstack_diff_upstream", original)

        with patch.dict(os.environ, self.env, clear=False):
            pstack = mod.run_pstack_diff(str(repo))

        self.assertIn("(upstream)", pstack["self_check"])
        self.assertEqual(pstack["extra_count"], 0)
        self.assertEqual(pstack["gap_count"], 0)
        self.assertEqual(pstack["local_extra_count"], 1)
        self.assertTrue(pstack["upstream"])
        v, _, _ = mod.verdict(
            "claude",
            "valentin-mode v4 (latest)",
            4,
            4,
            0,
            False,
            pstack["extra_count"],
            pstack["gap_count"],
            pstack["upstream_extras"],
            pstack["upstream_gaps"],
            pstack["upstream_ok"],
            pstack["stale"],
            pstack["fetch_failed"],
            pstack["behind"],
        )
        self.assertEqual(v, "OK")

    def test_fetch_failure_not_ok_with_local_counts(self):
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(0)
        self.fake_pstack_diff(1, 1, behind=2)
        repo = self.home / "offline"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "f").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "f"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", "http://127.0.0.1:9/no-such-repo"],
            check=True,
        )

        self.write_transcript(
            str(repo),
            "sid-fetch",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [
                dict(
                    name="Offline",
                    harness="claude",
                    cwd=str(repo),
                    sid="sid-fetch",
                    tmux="live-off",
                )
            ]
        )
        row = rows[0]
        self.assertIn("fetch failed", row["self_check"])
        self.assertNotIn("(upstream)", row["self_check"])
        self.assertEqual(row["extra_count"], 1, row)
        self.assertEqual(row["local_extra_count"], 1, row)
        self.assertFalse(row["upstream"])
        self.assertNotEqual(row["verdict"], "OK", row)
        self.assertIn("FIX", row["verdict"])

    def test_fetch_failure_self_check_without_behind_marker(self):
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(0)
        self.fake_pstack_diff(1, 1, gaps=0, behind=None)
        repo = self.home / "offline-nobehind"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "f").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "f"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", "http://127.0.0.1:9/no-such-repo"],
            check=True,
        )
        self.write_transcript(
            str(repo),
            "sid-fetch-nb",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [
                dict(
                    name="OfflineNoBehind",
                    harness="claude",
                    cwd=str(repo),
                    sid="sid-fetch-nb",
                    tmux="live-off-nb",
                )
            ]
        )
        row = rows[0]
        self.assertIn("(fetch failed)", row["self_check"], row)
        self.assertNotEqual(row["verdict"], "OK", row)

    def test_parse_roster_line(self):
        mod = load_module()
        line = mod.parse_roster_lines("Alpha (live-a, claude, ~/projects/alpha)\n3 live sessions")
        self.assertEqual(len(line), 1)
        self.assertEqual(line[0]["name"], "Alpha")
        self.assertEqual(line[0]["harness"], "claude")

    def test_script_always_exits_zero(self):
        done = subprocess.run([sys.executable, str(SCRIPT)], env=self.env, check=False)
        self.assertEqual(done.returncode, 0)

    def test_html_bad_path_still_exits_zero(self):
        bad = self.home / "no" / "such" / "dir" / "report.html"
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--html", str(bad)],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_broken_pstack_diff_no_install_is_unknown(self):
        """Verdict fault 1: real pstack-diff, empty PSTACK_DIFF_PSTACK, must not be OK."""
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(0)
        empty_pstack = self.home / "empty-pstack"
        empty_pstack.mkdir()
        repo = self.home / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.write_transcript(
            str(repo),
            "sid-nopstack",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [dict(name="Chat", harness="claude", cwd=str(repo), sid="sid-nopstack", tmux="live-nopstack")],
            extra_env={
                "FLEET_REPORT_PSTACK_DIFF": str(ROOT / "skills/pstack-diff/pstack-diff"),
                "PSTACK_DIFF_PSTACK": str(empty_pstack),
            },
        )
        row = rows[0]
        self.assertEqual(row["pstack_exit"], 1, row)
        self.assertNotEqual(row["self_check"], "EXTRA 0 GAP 0", row)
        self.assertEqual(row["verdict"], "UNKNOWN", row)
        self.assertIn("pstack", row["reason"].casefold(), row)

    def test_pstack_diff_exit_one_empty_stdout_is_unknown(self):
        mod = load_module()
        trusted, reason = mod.pstack_run_trusted(1, "", "GAP pstack: no install under /tmp/x\n", False)
        self.assertFalse(trusted)
        self.assertIn("no install", reason)
        script = self.home / "crash-pstack.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            'sys.stderr.write("GAP pstack: no install under /tmp/x\\n")\n'
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        repo = self.home / "repo2"
        repo.mkdir()
        env_patch = {**self.env, "FLEET_REPORT_PSTACK_DIFF": str(script)}
        with patch.dict(os.environ, env_patch, clear=True):
            _label, _code, extras, gaps, _behind, trusted2, _reason2 = mod.run_pstack_diff_at(repo)
        self.assertFalse(trusted2)
        self.assertIsNone(extras)
        self.assertIsNone(gaps)

    def test_pstack_diff_exit_two_no_output_is_unknown(self):
        mod = load_module()
        script = self.home / "exit2-pstack.py"
        script.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(2)\n", encoding="utf-8")
        script.chmod(0o755)
        trusted, reason = mod.pstack_run_trusted(2, "", "", False)
        self.assertFalse(trusted)
        self.assertIn("no parsed", reason)

    def test_missing_pstack_diff_reports_unknown(self):
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(0)
        repo = self.home / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.write_transcript(
            str(repo),
            "sid-miss",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [dict(name="Chat", harness="claude", cwd=str(repo), sid="sid-miss", tmux="live-miss")],
            extra_env={"FLEET_REPORT_PSTACK_DIFF": str(self.home / "no-such-pstack-diff")},
        )
        row = rows[0]
        self.assertEqual(row["self_check"], "missing")
        self.assertEqual(row["verdict"], "UNKNOWN", row)
        self.assertIn("pstack-diff", row["reason"])

    def test_stale_clone_unfetched_reports_upstream_extra(self):
        self.fake_version_script("valentin-mode v4 (latest)")
        self.fake_loop_state(0)
        bare = self.home / "bare.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        upstream = self.home / "upstream"
        upstream.mkdir()
        subprocess.run(["git", "init", "-q", str(upstream)], check=True)
        subprocess.run(["git", "-C", str(upstream), "config", "user.email", "t@test"], check=True)
        subprocess.run(["git", "-C", str(upstream), "config", "user.name", "t"], check=True)
        (upstream / "README").write_text("v1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(upstream), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(upstream), "commit", "-q", "-m", "v1"], check=True)
        subprocess.run(["git", "-C", str(upstream), "branch", "-M", "main"], check=True)
        subprocess.run(["git", "-C", str(upstream), "remote", "add", "origin", str(bare)], check=True)
        subprocess.run(["git", "-C", str(upstream), "push", "-q", "origin", "main"], check=True)

        clone = self.home / "clone"
        subprocess.run(
            ["git", "clone", "-q", str(bare), str(clone)],
            check=True,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
        )
        subprocess.run(
            ["git", "-C", str(clone), "config", "user.email", "t@test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(clone), "config", "user.name", "t"],
            check=True,
        )
        subprocess.run(["git", "-C", str(bare), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)

        (upstream / "README").write_text("v2\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(upstream), "commit", "-aq", "-m", "v2"], check=True)
        subprocess.run(["git", "-C", str(upstream), "push", "-q", "origin", "main"], check=True)

        fleet_prefix = "fleet-report-pstack-"
        script = self.home / "pstack-diff-stale.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"prefix = {json.dumps(fleet_prefix)}\n"
            "root = sys.argv[1]\n"
            "if prefix in root:\n"
            '    print("EXTRA workflow: upstream-only")\n'
            "    sys.exit(1)\n"
            'print("clean checkout")\n'
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        self.env["FLEET_REPORT_PSTACK_DIFF"] = str(script)

        self.write_transcript(
            str(clone),
            "sid-stale",
            '{"message":{"content":"valentin-mode v4 (latest)"}}\n',
        )
        rows = self.run_report(
            [
                dict(
                    name="Stale",
                    harness="claude",
                    cwd=str(clone),
                    sid="sid-stale",
                    tmux="live-stale",
                )
            ]
        )
        row = rows[0]
        self.assertIn("(upstream)", row["self_check"], row)
        self.assertEqual(row["extra_count"], 1, row)
        self.assertEqual(row["verdict"], "FIX", row)


if __name__ == "__main__":
    unittest.main()