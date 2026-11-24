import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run-verifier"
VERDICT = ROOT / "scripts/verdict.py"
WORKFLOWS = ROOT / ".github/workflows"
LANE_WORKFLOWS = ("pstack-sources.yml",)
FAKE_PI = '''#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time

args = sys.argv[1:]
lane = args[args.index("--provider") + 1]
model = args[args.index("--model") + 1]
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(lane + " " + model + "\\n")
with open(os.environ["FAKE_LOG"] + ".args", "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
mode = json.loads(os.environ["FAKE_PLAN"]).get(model, "empty")
text = {"pass": "PASS", "notes": "PASS+NOTES", "fail": "FAIL\\nReason: broken",
        "verdict": "VERDICT: PASS\\n\\nEvidence: commands and logs",
        "json": "{\\"verdict\\": \\"PASS\\", \\"evidence\\": [\\"ran the tests\\"]}",
        "fenced": "Evidence:\\n```\\nPASS\\n```\\nMore prose.",
        "nobash": "PASS",
        "pass429": "PASS\\nNo 429 or quota error seen in this run."}.get(mode)
if text:
    if mode != "nobash":
        print(json.dumps({"type": "tool_execution_end", "toolCallId": "1", "toolName": "bash",
                          "result": {"structuredContent": {"output": "ok", "exit_code": 0}, "isError": False}}))
    print(json.dumps({"type": "message_end", "message": {"role": "assistant",
                                                         "content": [{"type": "text", "text": text}]}}))
elif mode == "429":
    sys.stderr.write("429 Too Many Requests: quota used up\\n")
    sys.exit(1)
elif mode == "429_hang":
    print(json.dumps({"type": "tool_execution_end", "toolCallId": "1", "toolName": "bash",
                      "result": {"structuredContent": {"output": "ok", "exit_code": 0}, "isError": False}}),
          flush=True)
    sys.stderr.write("429 Too Many Requests: quota used up\\n")
    sys.stderr.flush()
    time.sleep(30)
elif mode == "429_retry_event_hang":
    print(json.dumps({"type": "auto_retry_start", "attempt": 1, "delayMs": 30000,
                      "errorMessage": "429 rate limit exceeded"}), flush=True)
    time.sleep(30)
elif mode == "hang_silent":
    time.sleep(30)
elif mode == "hang_after_session":
    print(json.dumps({"type": "session", "id": "1"}), flush=True)
    time.sleep(30)
elif mode == "chatter_no_bash":
    print(json.dumps({"type": "session", "id": "1"}), flush=True)
    for _ in range(300):
        print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "."}}),
              flush=True)
        time.sleep(0.05)
elif mode == "progress_until_cap":
    print(json.dumps({"type": "tool_execution_start", "toolCallId": "1", "toolName": "bash",
                      "args": {"command": "pytest"}}), flush=True)
    for _ in range(200):
        print(json.dumps({"type": "tool_execution_update", "toolCallId": "1", "toolName": "bash"}), flush=True)
        time.sleep(0.15)
elif mode == "silent_bash_then_pass":
    print(json.dumps({"type": "tool_execution_start", "toolCallId": "1", "toolName": "bash",
                      "args": {"command": "python3 -m unittest discover -s tests"}}), flush=True)
    time.sleep(float(os.environ.get("FAKE_SILENT_SECONDS", "0.95")))
    print(json.dumps({"type": "tool_execution_end", "toolCallId": "1", "toolName": "bash",
                      "result": {"structuredContent": {"output": "ok", "exit_code": 0}, "isError": False}}),
          flush=True)
    print(json.dumps({"type": "message_end", "message": {"role": "assistant",
                                                         "content": [{"type": "text", "text": "PASS"}]}}),
          flush=True)
elif mode == "hang_after_tool_end":
    print(json.dumps({"type": "tool_execution_start", "toolCallId": "1", "toolName": "bash",
                      "args": {"command": "echo hi"}}), flush=True)
    print(json.dumps({"type": "tool_execution_end", "toolCallId": "1", "toolName": "bash",
                      "result": {"structuredContent": {"output": "hi", "exit_code": 0}, "isError": False}}),
          flush=True)
    time.sleep(30)
elif mode == "spawn_child_hang":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    with open(os.environ["FAKE_CHILD_PID"], "w", encoding="utf-8") as handle:
        handle.write(str(child.pid))
    time.sleep(30)
elif mode == "broken":
    sys.exit(2)
'''
AUTHOR = "Author model: anthropic/claude-sonnet"


class RunVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.fake = self.dir / "pi"
        self.fake.write_text(FAKE_PI)
        self.fake.chmod(0o755)
        self.event = self.dir / "event.json"
        self.event.write_text(json.dumps({"pull_request": {"body": AUTHOR}}))
        self.prompt = self.dir / "prompt.txt"
        self.prompt.write_text("PROMPT-TEXT-NEVER-PRINTED\n")
        self.log = self.dir / "attempts.log"
        self.env_file = self.dir / "github-env"
        self.out = self.dir / "verifier.jsonl"

    def run_verifier(self, plan=None, keys=None, args=None, body=None):
        self.event.write_text(json.dumps({"pull_request": {"body": body or AUTHOR}}))
        self.log.unlink(missing_ok=True)
        Path(str(self.log) + ".args").unlink(missing_ok=True)
        self.env_file.unlink(missing_ok=True)
        self.out.unlink(missing_ok=True)
        environment = {k: v for k, v in os.environ.items()
                       if k not in ("GITHUB_EVENT_PATH", "GITHUB_ENV", "PI_BIN", "FAKE_LOG", "FAKE_PLAN",
                                    "OPENCODE_API_KEY", "AI_GATEWAY_API_KEY")}
        environment.update({"PI_BIN": str(self.fake), "FAKE_LOG": str(self.log),
                            "FAKE_PLAN": json.dumps(plan or {}), "GITHUB_ENV": str(self.env_file)})
        environment.update({"OPENCODE_API_KEY": "fake"} if keys is None else keys)
        command = [str(SCRIPT), "--out", str(self.out), "--prompt-file", str(self.prompt),
                   "--event", str(self.event)]
        return subprocess.run(command + (args if args is not None else ["--", "--thinking", "low"]),
                              capture_output=True, text=True, env=environment)

    def attempts(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_self_test(self):
        result = subprocess.run([str(SCRIPT), "--self-test"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run-verifier self-test ok", result.stdout)

    def test_an_empty_reply_falls_through_to_the_next_model(self):
        result = self.run_verifier({"glm-5.3-flash": "pass"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attempts(), ["opencode-go deepseek-v4.1-flash", "opencode-go glm-5.3-flash"])
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")
        self.assertIn("verdict from opencode-go/glm-5.3-flash", result.stderr)
        self.assertIn("deepseek-v4.1-flash gave no verdict", result.stderr)
        self.assertEqual(self.out.read_text().count('"PASS"'), 1)
        self.assertNotIn("PROMPT-TEXT-NEVER-PRINTED", result.stderr)

    def test_a_429_falls_through_and_fail_counts_as_a_verdict(self):
        result = self.run_verifier({"deepseek-v4.1-flash": "429", "glm-5.3-flash": "fail"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attempts(), ["opencode-go deepseek-v4.1-flash", "opencode-go glm-5.3-flash"])
        self.assertIn("429 or quota", result.stderr)
        self.assertIn("FAIL", self.out.read_text())
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")

    def test_a_non_zero_exit_falls_through(self):
        result = self.run_verifier({"deepseek-v4.1-flash": "broken", "glm-5.3-flash": "notes"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("exit 2", result.stderr)
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")

    def test_no_lane_gives_a_verdict(self):
        result = self.run_verifier({})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.attempts(), ["opencode-go deepseek-v4.1-flash", "opencode-go glm-5.3-flash",
                                           "opencode-go kimi-k3"])
        self.assertIn("run-verifier: no lane gave a verdict", result.stderr)
        self.assertFalse(self.env_file.exists())
        self.assertTrue(self.out.exists())

    def test_gateway_runs_when_opencode_is_unset(self):
        result = self.run_verifier({"deepseek/deepseek-v4.1-flash": "pass"}, {"AI_GATEWAY_API_KEY": "fake"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attempts(), ["vercel-ai-gateway deepseek/deepseek-v4.1-flash"])
        self.assertEqual(self.env_file.read_text(),
                         "VERIFIER_MODEL=vercel-ai-gateway/deepseek/deepseek-v4.1-flash\n")

    def test_gateway_starts_only_after_every_opencode_model(self):
        result = self.run_verifier({"zai/glm-5.3-flash": "pass"},
                                   {"OPENCODE_API_KEY": "fake", "AI_GATEWAY_API_KEY": "fake"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attempts(), ["opencode-go deepseek-v4.1-flash", "opencode-go glm-5.3-flash",
                                           "opencode-go kimi-k3", "vercel-ai-gateway deepseek/deepseek-v4.1-flash",
                                           "vercel-ai-gateway zai/glm-5.3-flash"])
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=vercel-ai-gateway/zai/glm-5.3-flash\n")

    def test_a_verdict_that_mentions_429_is_still_a_verdict(self):
        result = self.run_verifier({"deepseek-v4.1-flash": "pass429"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attempts(), ["opencode-go deepseek-v4.1-flash"])
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/deepseek-v4.1-flash\n")

    def test_the_verdict_prefix_the_skill_lint_brief_asks_for_is_a_verdict(self):
        result = self.run_verifier({"glm-5.3-flash": "verdict"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")
        self.assertIn("VERDICT: PASS", self.out.read_text())

    def test_the_json_verdict_field_the_advisor_returns_is_a_verdict(self):
        result = self.run_verifier({"glm-5.3-flash": "json"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")

    def test_a_bare_verdict_inside_a_fence_is_quoted_evidence_not_an_answer(self):
        result = self.run_verifier({"deepseek-v4.1-flash": "fenced", "glm-5.3-flash": "pass"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attempts(), ["opencode-go deepseek-v4.1-flash", "opencode-go glm-5.3-flash"])
        self.assertIn("no verdict line", result.stderr)

    def test_a_verdict_without_a_bash_run_falls_through(self):
        result = self.run_verifier({"deepseek-v4.1-flash": "nobash", "glm-5.3-flash": "pass"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attempts(), ["opencode-go deepseek-v4.1-flash", "opencode-go glm-5.3-flash"])
        self.assertIn("no bash evidence", result.stderr)

    def test_the_authors_family_is_never_attempted(self):
        result = self.run_verifier({}, body="Author model: deepseek/deepseek-v4.1-flash")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.attempts(), ["opencode-go glm-5.3-flash", "opencode-go kimi-k3"])

    def test_no_keys_means_no_attempt(self):
        result = self.run_verifier({}, {})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.attempts(), [])
        self.assertIn("run-verifier: no lane gave a verdict", result.stderr)

    def test_a_missing_author_declaration_keeps_the_picker_error(self):
        result = self.run_verifier({}, body="no declaration here")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Author model: <family>/<model>", result.stderr)
        self.assertEqual(self.attempts(), [])

    def test_extra_pi_arguments_and_the_prompt_reach_pi(self):
        result = self.run_verifier({"deepseek-v4.1-flash": "pass"},
                                   args=["--", "--thinking", "low", "--no-session"])
        self.assertEqual(result.returncode, 0, result.stderr)
        received = json.loads(Path(str(self.log) + ".args").read_text().splitlines()[0])
        self.assertEqual(received[-2:], ["-p", "PROMPT-TEXT-NEVER-PRINTED\n"])
        self.assertEqual(received[:6], ["--provider", "opencode-go", "--model", "deepseek-v4.1-flash", "--thinking", "low"])
        self.assertIn("--no-session", received)
        self.assertIn("--mode", received)

    def test_no_verdict_prints_clear_summary_line_with_default_flags(self):
        result = self.run_verifier(
            {"glm-5.3-flash": "429", "kimi-k3": "nobash"},
            {"OPENCODE_API_KEY": "fake"},
            body="Author model: deepseek/deepseek-v4.1-flash",
        )
        self.assertEqual(result.returncode, 1)
        expected = (
            "NO VERDICT: every model lane failed: "
            "opencode-go/glm-5.3-flash: 429 or quota, "
            "opencode-go/kimi-k3: no bash evidence. "
            "This is not a code failure."
        )
        self.assertIn(expected, result.stderr)
        check = subprocess.run([sys.executable, str(VERDICT), "-"], input=expected + "\n",
                               capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(check.returncode, 1, "NO VERDICT must never count as PASS")

    def test_pr_303_four_lane_replay_fails_fast_with_clear_no_verdict(self):
        # Replays PR #303 run 45209209477 (attempt 1, job 137815597854):
        # opencode-go/glm-5.3-flash hit 429/quota, opencode-go/kimi-k3 had no bash evidence,
        # and both vercel-ai-gateway lanes hung without output instead of failing over early.
        start = time.monotonic()
        result = self.run_verifier(
            {
                "glm-5.3-flash": "429_hang",
                "kimi-k3": "nobash",
                "zai/glm-5.3-flash": "hang_silent",
                "moonshotai/kimi-k3": "hang_after_session",
            },
            {"OPENCODE_API_KEY": "fake", "AI_GATEWAY_API_KEY": "fake"},
            args=["--attempt-timeout", "6", "--idle-timeout", "0.4", "--no-bash-timeout", "0.8",
                  "--", "--thinking", "low"],
            body="Author model: deepseek/deepseek-v4.1-flash",
        )
        elapsed = time.monotonic() - start
        self.assertEqual(result.returncode, 1)
        self.assertLess(elapsed, 4.0, f"stuck lanes should fail over before hard cap, took {elapsed:.2f}s\n{result.stderr}")
        self.assertEqual(
            self.attempts(),
            [
                "opencode-go glm-5.3-flash",
                "opencode-go kimi-k3",
                "vercel-ai-gateway zai/glm-5.3-flash",
                "vercel-ai-gateway moonshotai/kimi-k3",
            ],
        )
        expected = (
            "NO VERDICT: every model lane failed: "
            "opencode-go/glm-5.3-flash: 429 or quota, "
            "opencode-go/kimi-k3: no bash evidence, "
            "vercel-ai-gateway/zai/glm-5.3-flash: no output for 0.4s, "
            "vercel-ai-gateway/moonshotai/kimi-k3: no output for 0.4s. "
            "This is not a code failure."
        )
        self.assertIn(expected, result.stderr)

    def test_429_on_stderr_while_hanging_fails_over_immediately(self):
        start = time.monotonic()
        result = self.run_verifier(
            {"deepseek-v4.1-flash": "429_hang", "glm-5.3-flash": "pass"},
            args=["--attempt-timeout", "6", "--idle-timeout", "5", "--", "--thinking", "low"],
        )
        elapsed = time.monotonic() - start
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 3.0, f"429 on stderr should abort early, took {elapsed:.2f}s")
        self.assertIn("429 or quota", result.stderr)
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")

    def test_429_provider_error_event_while_hanging_fails_over_immediately(self):
        start = time.monotonic()
        result = self.run_verifier(
            {"deepseek-v4.1-flash": "429_retry_event_hang", "glm-5.3-flash": "pass"},
            args=["--attempt-timeout", "6", "--idle-timeout", "5", "--", "--thinking", "low"],
        )
        elapsed = time.monotonic() - start
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 3.0, f"429 retry event should abort early, took {elapsed:.2f}s")
        self.assertIn("429 or quota", result.stderr)
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")

    def test_chattering_model_that_never_calls_bash_fails_over_early(self):
        start = time.monotonic()
        result = self.run_verifier(
            {"deepseek-v4.1-flash": "chatter_no_bash", "glm-5.3-flash": "pass"},
            args=["--attempt-timeout", "6", "--idle-timeout", "5", "--no-bash-timeout", "0.4",
                  "--", "--thinking", "low"],
        )
        elapsed = time.monotonic() - start
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 3.0, f"model with no bash call should fail over early, took {elapsed:.2f}s")
        self.assertIn("no bash call after 0.4s", result.stderr)
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")

    def test_active_lane_making_progress_keeps_the_hard_cap(self):
        start = time.monotonic()
        result = self.run_verifier(
            {"deepseek-v4.1-flash": "progress_until_cap", "glm-5.3-flash": "pass"},
            args=["--attempt-timeout", "1.2", "--idle-timeout", "0.5", "--no-bash-timeout", "0.3",
                  "--", "--thinking", "low"],
        )
        elapsed = time.monotonic() - start
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(elapsed, 1.0, f"active lane was cut off before hard cap ({elapsed:.2f}s)")
        self.assertIn("timed out after 1.2s", result.stderr)
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")

    def test_silent_bash_tool_running_past_idle_timeout_still_passes(self):
        result = self.run_verifier(
            {"deepseek-v4.1-flash": "silent_bash_then_pass", "glm-5.3-flash": "fail"},
            args=["--attempt-timeout", "5", "--idle-timeout", "0.3", "--no-bash-timeout", "0.5",
                  "--", "--thinking", "low"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attempts(), ["opencode-go deepseek-v4.1-flash"])
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/deepseek-v4.1-flash\n")
        self.assertIn('"PASS"', self.out.read_text())
        self.assertNotIn("no output for", result.stderr)

    def test_idle_timeout_resumes_after_tool_execution_ends(self):
        start = time.monotonic()
        result = self.run_verifier(
            {"deepseek-v4.1-flash": "hang_after_tool_end", "glm-5.3-flash": "pass"},
            args=["--attempt-timeout", "5", "--idle-timeout", "0.3", "--no-bash-timeout", "0.5",
                  "--", "--thinking", "low"],
        )
        elapsed = time.monotonic() - start
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 2.5, f"model silent after tool end should fail over early, took {elapsed:.2f}s")
        self.assertIn("no output for 0.3s", result.stderr)
        self.assertEqual(self.env_file.read_text(), "VERIFIER_MODEL=opencode-go/glm-5.3-flash\n")

    def test_aborted_lane_kills_its_child_process_group(self):
        pid_file = self.dir / "child.pid"
        environment = {k: v for k, v in os.environ.items()
                       if k not in ("GITHUB_EVENT_PATH", "GITHUB_ENV", "PI_BIN", "FAKE_LOG", "FAKE_PLAN",
                                    "OPENCODE_API_KEY", "AI_GATEWAY_API_KEY")}
        environment.update({
            "PI_BIN": str(self.fake),
            "FAKE_LOG": str(self.log),
            "FAKE_PLAN": json.dumps({"deepseek-v4.1-flash": "spawn_child_hang", "glm-5.3-flash": "pass"}),
            "FAKE_CHILD_PID": str(pid_file),
            "GITHUB_ENV": str(self.env_file),
            "OPENCODE_API_KEY": "fake",
        })
        result = subprocess.run(
            [str(SCRIPT), "--out", str(self.out), "--prompt-file", str(self.prompt),
             "--event", str(self.event), "--attempt-timeout", "5", "--idle-timeout", "0.4",
             "--", "--thinking", "low"],
            capture_output=True, text=True, env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(pid_file.exists(), "fake pi should have spawned a child process")
        child_pid = int(pid_file.read_text().strip())
        # Give the kernel a brief moment to reap the killed child.
        alive = True
        for _ in range(20):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                alive = False
                break
            time.sleep(0.05)
        if alive:
            os.kill(child_pid, 9)
        self.assertFalse(alive, f"child process {child_pid} survived lane timeout as an orphan")


class VerifierWorkflowTests(unittest.TestCase):
    def test_the_runner_calls_the_lane_runner_with_the_prompt_file(self):
        text = (WORKFLOWS / "pstack-sources.yml").read_text()
        self.assertIn("scripts/run-verifier", text)
        self.assertIn("--prompt-file /tmp/verify.md", text)
        self.assertIn("--out verifier.jsonl", text)
        self.assertIn("--attempt-timeout 840", text)
        self.assertIn("AI_GATEWAY_API_KEY: ${{ secrets.AI_GATEWAY_API_KEY }}", text)
        self.assertNotIn('test -n "$OPENCODE_API_KEY"', text)
        self.assertIn("GITHUB_ENV", text)
        self.assertIn("git diff --exit-code", text)

    def test_the_runner_comes_from_the_base_checkout(self):
        lines = [line for line in (WORKFLOWS / "pstack-sources.yml").read_text().splitlines()
                 if "scripts/run-verifier" in line]
        self.assertTrue(lines)
        for line in lines:
            self.assertIn('"$GITHUB_WORKSPACE/picker-base/scripts/run-verifier"', line)

    def test_the_lane_runner_keeps_the_old_single_attempt_as_a_fallback(self):
        text = (WORKFLOWS / "pstack-sources.yml").read_text()
        self.assertIsNotNone(re.search(r'if \[ ! -f "\$GITHUB_WORKSPACE/picker-base/scripts/run-verifier" \]', text))
        self.assertIn("pi --provider opencode-go --model", text)
        self.assertIn('"$GITHUB_WORKSPACE/picker-base/scripts/pick-verifier-model"', text)

    def test_either_key_is_enough_for_the_lane_runner(self):
        text = (WORKFLOWS / "pstack-sources.yml").read_text()
        self.assertIsNotNone(re.search(r'\[ -z "\$OPENCODE_API_KEY" \] && \[ -z "\$AI_GATEWAY_API_KEY" \]', text))

    def test_every_verifier_workflow_hands_over_the_gateway_key(self):
        for name in LANE_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertIn("AI_GATEWAY_API_KEY: ${{ secrets.AI_GATEWAY_API_KEY }}",
                              (WORKFLOWS / name).read_text())

    def test_workflow_posts_no_verdict_comment_when_every_lane_fails(self):
        text = (WORKFLOWS / "pstack-sources.yml").read_text()
        self.assertIn("run-verifier.err", text)
        self.assertIn("NO VERDICT:", text)
        self.assertIn("Post no-verdict notice", text)
        self.assertIn("steps.drive.outcome == 'failure'", text)
        # Keep the workflow call compatible with picker-base on older main commits.
        self.assertNotIn("--idle-timeout", text)
        self.assertNotIn("--no-bash-timeout", text)

        # Extract the exact run block of "Post no-verdict notice" and execute it with a fake gh CLI.
        match = re.search(
            r"- name: Post no-verdict notice\n.*?run: \|\n((?:          [^\n]*\n|\n)+)",
            text,
            re.S,
        )
        self.assertIsNotNone(match, "could not find Post no-verdict notice run block")
        script = "\n".join(line[10:] if line.startswith("          ") else line
                           for line in match.group(1).splitlines()) + "\n"

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            fake_bin = work / "bin"
            fake_bin.mkdir()
            posted = work / "posted.txt"
            gh = fake_bin / "gh"
            gh.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "args = sys.argv[1:]\n"
                "body = open(args[args.index('--body-file') + 1]).read()\n"
                "open(os.environ['POSTED_OUT'], 'w').write(body)\n"
            )
            gh.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
                "POSTED_OUT": str(posted),
                "PR_NUMBER": "303",
                "PR_HEAD": "79c22953a27b36047f3f8896f455786f22255356",
            }

            # 1) Direct NO VERDICT line from the updated run-verifier.
            direct_line = (
                "NO VERDICT: every model lane failed: "
                "opencode-go/glm-5.3-flash: 429 or quota, "
                "opencode-go/kimi-k3: no bash evidence, "
                "vercel-ai-gateway/zai/glm-5.3-flash: no output for 120s, "
                "vercel-ai-gateway/moonshotai/kimi-k3: no output for 120s. "
                "This is not a code failure."
            )
            (work / "run-verifier.err").write_text(
                "run-verifier: no lane gave a verdict\n" + direct_line + "\n"
            )
            res = subprocess.run(["bash", "-euo", "pipefail", "-c", script],
                                 cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn(direct_line, posted.read_text())
            self.assertIn("79c22953a27b36047f3f8896f455786f22255356", posted.read_text())

            # 2) Replay the literal 4-lane log from PR #303 run 45209209477 (old picker-base format).
            posted.unlink()
            (work / "verdict.md").unlink()
            (work / "run-verifier.err").write_text(
                "run-verifier: opencode-go/glm-5.3-flash gave no verdict (429 or quota, no verdict line), trying next\n"
                "run-verifier: opencode-go/kimi-k3 gave no verdict (no bash evidence), trying next\n"
                "run-verifier: vercel-ai-gateway/zai/glm-5.3-flash gave no verdict (timed out after 540s), trying next\n"
                "run-verifier: vercel-ai-gateway/moonshotai/kimi-k3 gave no verdict (timed out after 540s), trying next\n"
                "run-verifier: no lane gave a verdict\n"
            )
            res = subprocess.run(["bash", "-euo", "pipefail", "-c", script],
                                 cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            expected_pr303 = (
                "NO VERDICT: every model lane failed: "
                "opencode-go/glm-5.3-flash: 429 or quota, no verdict line, "
                "opencode-go/kimi-k3: no bash evidence, "
                "vercel-ai-gateway/zai/glm-5.3-flash: timed out after 540s, "
                "vercel-ai-gateway/moonshotai/kimi-k3: timed out after 540s. "
                "This is not a code failure."
            )
            self.assertIn(expected_pr303, posted.read_text())

            # 3) A non-no-verdict failure (e.g. missing Author model) must not post a NO VERDICT comment.
            posted.unlink()
            (work / "verdict.md").unlink()
            (work / "run-verifier.err").write_text(
                "pick-verifier-model: the PR body has no `Author model: <family>/<model>` line.\n"
            )
            res = subprocess.run(["bash", "-euo", "pipefail", "-c", script],
                                 cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertFalse(posted.exists(), "must not post NO VERDICT for picker/author errors")


if __name__ == "__main__":
    unittest.main()
