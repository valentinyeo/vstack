import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/pick-verifier-model"


class PickVerifierModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.event = Path(self.temp.name) / "event.json"

    def run_picker(self, body, env=None, args=None):
        self.event.write_text(json.dumps({"pull_request": {"body": body}}))
        environment = {k: v for k, v in os.environ.items() if k != "GITHUB_EVENT_PATH"}
        environment.update(env or {"GITHUB_EVENT_PATH": str(self.event)})
        return subprocess.run([str(SCRIPT)] + (args or []), capture_output=True, text=True, env=environment)

    def test_self_test(self):
        result = self.run_picker("", args=["--self-test"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_non_deepseek_author_gets_deepseek(self):
        result = self.run_picker("## Why\nx\n\nAuthor model: anthropic/claude-sonnet\n")
        self.assertEqual((result.returncode, result.stdout), (0, "deepseek-v4.1-flash\n"))

    def test_deepseek_author_gets_glm(self):
        result = self.run_picker("Author model: deepseek/deepseek-v4.1-flash")
        self.assertEqual(result.stdout, "glm-5.3-flash\n")

    def test_every_author_counts(self):
        result = self.run_picker("Author model: deepseek/a\nAuthor model: openai/b\nAuthor model: glm/c")
        self.assertEqual(result.stdout, "kimi-k3\n")

    def test_missing_declaration_fails_with_message(self):
        for body in ("", None, "Author: me", "Author model:", "text Author model: deepseek/x", "Author model: deepseek/x trailing"):
            with self.subTest(body=body):
                result = self.run_picker(body)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("Author model: <family>/<model>", result.stderr)

    def test_family_comes_from_the_whole_string_not_the_prefix(self):
        cases = {
            "Author model: deepseek-ai/DeepSeek-V3": "glm-5.3-flash",
            "Author model: opencode-go/deepseek-v4.1-flash": "glm-5.3-flash",
            "Author model: openrouter/deepseek/deepseek-chat": "glm-5.3-flash",
            "Author model: deepseek-v4.1-flash": "glm-5.3-flash",
            "Author model: z.ai/glm-5.3-flash": "deepseek-v4.1-flash",
            "Author model: Z.AI/GLM-4.6": "deepseek-v4.1-flash",
            "Author model: moonshotai/kimi-k2": "deepseek-v4.1-flash",
            "Author model: opencode-go/kimi-k3": "deepseek-v4.1-flash",
            "Author model: openrouter/anthropic/claude-3.5": "deepseek-v4.1-flash",
        }
        for body, want in cases.items():
            with self.subTest(body=body):
                self.assertEqual(self.run_picker(body).stdout, want + "\n")

    def test_odd_spellings_still_count(self):
        for body in (
            "Author model: DEEPSEEK/x",
            "Author model: deep_seek/x",
            "Author model: Deep-Seek-V4",
            "Author model: \uff24\uff45\uff45\uff50\uff33\uff45\uff45\uff4b/x",  # fullwidth
            "Author model: deep\u200bseek/x",  # zero-width space
            "Author model: deepseek-ai/deepseek-r1-distill-qwen-32b",
        ):
            with self.subTest(body=body):
                self.assertEqual(self.run_picker(body).stdout, "glm-5.3-flash\n")

    def test_only_whole_line_declarations_count(self):
        for body in (
            "Author model: deepseek/x trailing text",
            "Author model: z.ai/glm-5.3-flash   before: a   after: b",
            "Author model: Claude Sonnet 5.5",
            "Author model: anthropic/claude-sonnet, deepseek/x",
            "- Author model: deepseek/x",
            "> Author model: deepseek/x",
            "**Author model:** deepseek/x",
            "Author model : deepseek/x",
            "Author model:deepseek/x",
            "author model: deepseek/x",
            " Author model: deepseek/x",
            "Author model: deepseek/x ",
        ):
            with self.subTest(body=body):
                result = self.run_picker(body)
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertIn("Author model: <family>/<model>", result.stderr)
        # an ignored line never hides a real declaration
        result = self.run_picker("Author model: deepseek/x trailing\nAuthor model: anthropic/claude-sonnet")
        self.assertEqual(result.stdout, "deepseek-v4.1-flash\n")

    def test_fenced_lines_are_ignored(self):
        transcript = "Author model: z.ai/glm-5.3-flash\nAuthor model: moonshotai/kimi-k2\nAuthor model: deepseek/x"
        bodies = {
            "backticks": "```\n%s\n```\nAuthor model: anthropic/claude-sonnet" % transcript,
            "info string": "```text\n%s\n```\nAuthor model: anthropic/claude-sonnet" % transcript,
            "longer fence": "````\n%s\n```\nstill code\n````\nAuthor model: anthropic/claude-sonnet" % transcript,
            "tildes": "~~~\n%s\n~~~\nAuthor model: anthropic/claude-sonnet" % transcript,
            "declaration first": "Author model: anthropic/claude-sonnet\n```\n%s\n```" % transcript,
            "crlf": "```\r\n%s\r\n```\r\nAuthor model: anthropic/claude-sonnet\r\n" % transcript.replace("\n", "\r\n"),
            "unclosed": "Author model: anthropic/claude-sonnet\n```\n%s" % transcript,
        }
        for name, body in bodies.items():
            with self.subTest(name=name):
                result = self.run_picker(body)
                self.assertEqual((result.returncode, result.stdout), (0, "deepseek-v4.1-flash\n"), result.stderr)

    def test_only_fenced_declarations_fail_as_missing(self):
        result = self.run_picker("```\nAuthor model: deepseek/x\n```")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Author model: <family>/<model>", result.stderr)

    def test_declaration_after_a_closed_fence_counts(self):
        result = self.run_picker("```\nx\n```\nAuthor model: deepseek/x")
        self.assertEqual(result.stdout, "glm-5.3-flash\n")

    def test_other_families_are_known(self):
        for body in (
            "Author model: o3-mini",
            "Author model: openai/o4-mini",
            "Author model: x-ai/grok-4",
            "Author model: google/gemini-3",
            "Author model: qwen/qwen3-coder",
            "Author model: xiaomi/mimo-v2",
            "Author model: minimax/MiniMax-M2",
            "Author model: Claude-Sonnet-5.5",
            "Author model: codex",
        ):
            with self.subTest(body=body):
                result = self.run_picker(body)
                self.assertEqual((result.returncode, result.stdout), (0, "deepseek-v4.1-flash\n"))

    def test_unknown_family_fails_with_message(self):
        for body in (
            "Author model: acme/mystery-1",
            "Author model: me",
            "Author model: d\u0435epseek/x",  # Cyrillic e
            "Author model: anthropic/claude\nAuthor model: acme/x",
        ):
            with self.subTest(body=body):
                result = self.run_picker(body)
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertIn("unknown model family", result.stderr)

    def test_all_verifier_families_authored_fails(self):
        result = self.run_picker("Author model: deepseek/a\nAuthor model: glm/b\nAuthor model: kimi/c")
        self.assertEqual(result.returncode, 1)
        self.assertIn("every verifier family", result.stderr)

    def test_all_lists_every_allowed_model_in_the_fixed_order(self):
        result = self.run_picker("Author model: anthropic/claude-sonnet", args=["--all"])
        self.assertEqual((result.returncode, result.stdout),
                         (0, "deepseek-v4.1-flash\nglm-5.3-flash\nkimi-k3\n"))

    def test_all_skips_every_authored_family(self):
        cases = {
            "Author model: deepseek/x": "glm-5.3-flash\nkimi-k3\n",
            "Author model: z.ai/glm-5.3-flash": "deepseek-v4.1-flash\nkimi-k3\n",
            "Author model: moonshotai/kimi-k2": "deepseek-v4.1-flash\nglm-5.3-flash\n",
            "Author model: deepseek/x\nAuthor model: opencode-go/kimi-k3": "glm-5.3-flash\n",
        }
        for body, want in cases.items():
            with self.subTest(body=body):
                self.assertEqual(self.run_picker(body, args=["--all"]).stdout, want)

    def test_all_refuses_exactly_like_the_single_pick(self):
        cases = {
            "no declaration": (None, "Author model: <family>/<model>"),
            "every family authored": ("Author model: deepseek/a\nAuthor model: glm/b\nAuthor model: kimi/c",
                                      "every verifier family"),
            "unknown family": ("Author model: acme/mystery-1", "unknown model family"),
        }
        for name, (body, message) in cases.items():
            with self.subTest(case=name):
                single = self.run_picker(body)
                every = self.run_picker(body, args=["--all"])
                self.assertEqual((every.returncode, every.stdout), (single.returncode, single.stdout))
                self.assertEqual((every.returncode, every.stdout), (1, ""))
                self.assertIn(message, every.stderr)

    def test_all_prints_every_line_for_the_same_body_the_single_pick_reads(self):
        body = "Author model: deepseek/x"
        self.assertEqual(self.run_picker(body).stdout, "glm-5.3-flash\n")
        self.assertEqual(self.run_picker(body, args=["--all"]).stdout, "glm-5.3-flash\nkimi-k3\n")

    def test_missing_event_path_fails(self):
        result = self.run_picker("", env={"UNRELATED": "1"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("GITHUB_EVENT_PATH", result.stderr)

    def test_event_without_pull_request_fails(self):
        self.event.write_text("{}")
        result = subprocess.run([str(SCRIPT), "--event", str(self.event)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
