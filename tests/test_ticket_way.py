#!/usr/bin/env python3
"""Replay actual shell commands through Claude's hook protocol."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/ticket-way.py'


class TicketWay(unittest.TestCase):
    def check_command(self, command, blocked):
        result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({
            'tool_name': 'Bash', 'cwd': str(ROOT),
            'tool_input': {'command': command},
        }), text=True, capture_output=True)
        self.assertEqual(result.returncode, 2 if blocked else 0, result.stderr)
        if blocked:
            self.assertIn('poteto-ticket', result.stderr)

    def test_project_enables_hook(self):
        settings = json.loads((ROOT / '.claude/settings.json').read_text())
        commands = [h['command'] for entry in settings['hooks']['PreToolUse']
                    if entry['matcher'] == 'Bash' for h in entry['hooks']]
        self.assertTrue(any('/hooks/ticket-way.py' in command for command in commands))

    def test_today(self):
        for row in json.loads((ROOT / 'tests/fixtures/poteto-raw-2026-11-17.json').read_text()):
            with self.subTest(timestamp=row['timestamp']):
                self.check_command(row['command'], True)
                self.check_command(row['fullCommand'], True)

    def test_bypasses(self):
        for command in [
            "env -i HT=hypertask sh -c '$HT task create --project 2060 --title x'",
            'command -- hypertask task update SOFT-2573 --section Done',
            'env POTETO_TICKET_ALLOW_RAW=1 hypertask task create --project 2060 --title x',
            'sh -c "hypertask comment add SOFT-2573 --text status"',
            '"/home/valentin/.local/bin/hypertask" task update SOFT-2573 --section Done',
            'HT=hypertask; "$HT" activity add SOFT-2573 --text status',
            "env HT=hypertask sh -c '$HT task create --project 2060 --title x'",
            'echo ok && hypertask --token="$T" task update SOFT-2573 --section Doing',
            'hypertask task move SOFT-2573 Done',
            'hypertask task assign SOFT-2573 --agent Poteto',
            'hypertask agent say SOFT-2573 status',
        ]:
            with self.subTest(command=command):
                self.check_command(command, True)

    def test_reads_help_and_wrapper(self):
        for command in [
            'bin/poteto-ticket new "a brief"',
            'bin/poteto-ticket claim SOFT-2573',
            'hypertask task get SOFT-2573',
            'hypertask --json task agent-log SOFT-2573',
            'hypertask task create --help',
            'hypertask task create --project 2060 --help',
            'echo "hypertask task create"',
            'rg "hypertask task create" bin',
            'git status',
        ]:
            with self.subTest(command=command):
                self.check_command(command, False)


if __name__ == '__main__':
    unittest.main()
