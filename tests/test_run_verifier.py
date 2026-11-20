import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run-verifier"
WORKFLOWS = ROOT / ".github/workflows"
LANE_WORKFLOWS = ("pstack-sources.yml",)
FAKE_PI = '''#!/usr/bin/env python3
import json
import os
import sys

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


class VerifierWorkflowTests(unittest.TestCase):
    def test_the_runner_calls_the_lane_runner_with_the_prompt_file(self):
        text = (WORKFLOWS / "pstack-sources.yml").read_text()
        self.assertIn("scripts/run-verifier", text)
        self.assertIn("--prompt-file /tmp/verify.md", text)
        self.assertIn("--out verifier.jsonl", text)
        self.assertIn("--attempt-timeout 540", text)
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


if __name__ == "__main__":
    unittest.main()
