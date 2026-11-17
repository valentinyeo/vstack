import re
import unittest
from pathlib import Path


class DrainRuleTests(unittest.TestCase):
    def test_shared_rule_keeps_autonomous_run_contract(self):
        text = (Path(__file__).resolve().parents[1] / 'skills/valentin-mode/SKILL.md').read_text()
        drain = text.split('- **Drain:**', 1)[1].split('- **Short chats:**', 1)[0]
        for clause in ('0.15.43', 'playbooks/autonomous-run.md', 'checkable',
                       'worker finished', 'CI result', 'verdict posted', 'watcher',
                       'fallback', 'checkpoint', 'plateau', 'dead end'):
            with self.subTest(clause=clause):
                self.assertIn(clause, drain)
        self.assertNotIn('Orchestrate', drain)
        self.assertNotIn('/clear', drain)
        checkpoint = re.search(r'`Drain: ([^`]+)`', drain)
        self.assertIsNotNone(checkpoint)
        for field in ('goal', 'changed', 'next wake'):
            self.assertIn(field, checkpoint.group(1))


if __name__ == '__main__':
    unittest.main()
