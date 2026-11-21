"""long-chat handover must teach fresh sessions to load valentin-mode by hand."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/long-chat/SKILL.md'

FIRST_LINE = (
    'Load valentin-mode first: if this chat did not start with /valentin-mode, '
    'read ~/.local/share/vstack/skills/valentin-mode/SKILL.md and the responsive-mode '
    'SKILL.md it pastes, and follow them; your first reply names its version line.'
)


class LongChatSkill(unittest.TestCase):
    def test_handover_requires_valentin_mode_first_line(self):
        text = SKILL.read_text()
        self.assertIn(FIRST_LINE, text)
        self.assertIn('Its first line must be exactly:', text)


if __name__ == '__main__':
    unittest.main()