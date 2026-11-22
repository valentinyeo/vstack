#!/usr/bin/env python3
"""Every per-project hook in setup.md must be in .claude/settings.json (not global-only hooks)."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / 'skills' / 'valentin-mode' / 'setup.md'
SETTINGS = ROOT / '.claude/settings.json'

FAIL_OPEN = 'sh -c \'f="$HOME/.claude/hooks/{name}"; [ -f "$f" ] || exit 0; exec python3 "$f"\''


def hooks_named_in_setup():
    text = SETUP.read_text()
    return re.findall(r'\|\s*`([^`]+\.py)`\s*\|', text)


GLOBAL_ONLY = {'long-chat.py'}


def hooks_required_in_settings():
    return [name for name in hooks_named_in_setup() if name not in GLOBAL_ONLY]


def command_strings(settings):
    strings = []
    for entries in settings.get('hooks', {}).values():
        for entry in entries:
            for hook in entry.get('hooks', []):
                strings.append(hook.get('command', ''))
    return strings


class ValentinModeSettings(unittest.TestCase):
    def test_settings_registers_every_project_setup_hook(self):
        settings = json.loads(SETTINGS.read_text())
        commands = command_strings(settings)
        for name in hooks_required_in_settings():
            with self.subTest(hook=name):
                expected = FAIL_OPEN.format(name=name)
                self.assertIn(
                    expected, commands,
                    f'{name} missing from .claude/settings.json; want fail-open command from setup.md',
                )


if __name__ == '__main__':
    unittest.main()