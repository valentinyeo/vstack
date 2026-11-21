"""long-chat handover must teach fresh sessions to load valentin-mode by hand."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/long-chat/SKILL.md'


class LongChatSkill(unittest.TestCase):
    def test_handover_requires_valentin_mode_first_line(self):
        text = SKILL.read_text()
        self.assertIn(
            'If valentin-mode is not loaded in this chat, read '
            '~/.claude/skills/valentin-mode/SKILL.md in full first, then run /board-drain.',
            text,
        )
        self.assertIn('record whether valentin-mode was loaded in the old chat', text)
        self.assertIn('The first line must be:', text)


if __name__ == '__main__':
    unittest.main()