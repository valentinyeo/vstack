import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "hooks/subagent_call.py"
SPEC = importlib.util.spec_from_file_location("subagent_call", MOD)
subagent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subagent)


class SubagentCall(unittest.TestCase):
    def test_self_test(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, str(MOD), "--self-test"], capture_output=True, text=True,
                                cwd=str(ROOT))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("subagent-call self-test ok", result.stdout)

    def test_agent_id_opens(self):
        payload = {"agent_id": "a4d2c8f1e0b3a297", "agent_type": "Explore"}
        self.assertTrue(subagent.from_hook(payload))

    def test_subagents_path_opens(self):
        payload = {"transcript_path": "/home/u/.claude/projects/p/abc/subagents/agent-x.jsonl"}
        self.assertTrue(subagent.from_hook(payload))

    def test_main_chat_stays_closed(self):
        self.assertFalse(subagent.from_hook({"transcript_path": "/home/u/.claude/projects/p/abc.jsonl"}))
        self.assertFalse(subagent.from_hook({}))


if __name__ == "__main__":
    unittest.main()