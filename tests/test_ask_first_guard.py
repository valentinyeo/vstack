"""The Stop guard lets a product repo's own gate demand a question (VSTA-289).

ask-first-guard blocks a reply that asks Valentin how or whether to do something that is not his
call. Hypertask's `.claude/skills/ship/scripts/ht-flag` refuses a flag switch unless the reason
links to his clear yes on a question naming `Switch <flag-key> to <mode>`, and Hypertask AGENTS.md
says off is his own safety switch. The two rules met head on: the hook blocked the one question
the product repo demands. The owner's decision is that a gate a product enforces in code wins
inside that product, so a flag switch question passes and every other "should I" still blocks.

`install` wires the hook as a Claude Stop hook through run-hook, replacing the loose full-path
entry it had on this server without touching any other Stop hook.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/ask-first-guard.py'
SETUP = ROOT / 'skills/valentin-mode/setup.md'
INSTALL = ROOT / 'install'
FLAG_SENTENCE = ('plus gates a product repo enforces in code, such as Hypertask flag switches '
                 '(ask `Switch <flag-key> to <mode>?`).')


class FlagSwitchQuestion(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def hook_output(self, reply):
        transcript = self.folder / 'transcript.jsonl'
        entries = [{'type': 'user', 'message': {'role': 'user',
                                                'content': [{'type': 'text', 'text': 'go'}]}},
                   {'type': 'assistant', 'message': {'role': 'assistant',
                                                     'content': [{'type': 'text', 'text': reply}]}}]
        transcript.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
        payload = json.dumps({'hook_event_name': 'Stop', 'transcript_path': str(transcript)})
        return subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                              capture_output=True, check=False)

    def test_a_flag_switch_question_passes(self):
        for reply in ('Should I switch beta-banner to Off? My pick: yes.',
                      'Want me to switch payments_v2 to Everyone?',
                      'Should I switch invoice-export to Owner + QA, as ht-flag needs? My pick: yes.',
                      'Switch dark-mode-default to OWNER_AND_QA?'):
            with self.subTest(reply=reply):
                result = self.hook_output(reply)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '', result.stdout)

    def test_an_ordinary_how_ask_still_blocks(self):
        for reply in ('Should I use approach A or B? My pick: A.',
                      'Should I switch the flag to Off? My pick: yes.'):
            with self.subTest(reply=reply):
                reason = json.loads(self.hook_output(reply).stdout).get('reason', '')
                self.assertIn('not his call', reason)
                self.assertIn(FLAG_SENTENCE, reason)

    def test_self_test_passes(self):
        result = subprocess.run([sys.executable, str(HOOK), '--self-test'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('self-test ok', result.stdout)


class Install(unittest.TestCase):
    def test_install_registers_the_stop_hook_through_run_hook(self):
        self.assertIn('--event Stop --replace', INSTALL.read_text())
        self.assertIn('`ask-first-guard.py`', SETUP.read_text())


if __name__ == '__main__':
    unittest.main()
