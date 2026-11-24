"""A reply to Valentin names the work in plain words, never a bare ticket key.

Valentin, 2026-11-22: "they must not just constantly give me IDs for tickets. SOFT-3072 means nothing to me.
am i supposed to memorize this?" valentin-mode already says "Full https:// URLs, never a bare ticket id", but
a rule in markdown was broken all day. The Stop hook reads the chat's last assistant reply and blocks it while
a key like ABCD-123 sits outside a full https:// link. Code blocks and his own quoted words are ignored.
Valentin, 2026-11-24: "agents must reply with hypertask tickets and pr urls, never JUST pr urls", so the same
hook blocks a reply that shows a pull request link with no ticket link beside it.

The hook is declared in skills/valentin-mode/SKILL.md's frontmatter, the way context.py and responsive
mode's said-started.py are, so it runs in every valentin-mode chat and nowhere else.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/no-bare-ids.py'
SKILL = ROOT / 'skills/valentin-mode/SKILL.md'
BESIDE_SKILL = ROOT / 'skills/valentin-mode/no-bare-ids.py'
RULES = ROOT / 'CLAUDE.md'
MESSAGE = 'Name the work in plain words. If he needs the ticket, give its full https:// link.'
PR_MESSAGE = 'Every pull request link comes with the Hypertask ticket link for that work, never alone.'
TICKET = 'https://app.hypertask.ai/detail/project-13556/213'
PR = 'https://github.com/valentinyeo/vstack/pull/378'


def human(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}}


def say(text):
    return {'type': 'assistant', 'isSidechain': False,
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


class NoBareIds(unittest.TestCase):
    def hook(self, reply=None, entries=None, payload=None):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        if payload is None:
            transcript = folder / 'transcript.jsonl'
            lines = entries if entries is not None else [human('what is left?'), say(reply)]
            transcript.write_text(''.join(json.dumps(entry) + '\n' for entry in lines))
            payload = json.dumps({'hook_event_name': 'Stop', 'transcript_path': str(transcript)})
        return subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                              capture_output=True, check=False)

    def reason(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        answer = json.loads(result.stdout)
        self.assertEqual(answer.get('decision'), 'block')
        return answer.get('reason', '')

    def assert_blocked(self, reply, message=MESSAGE):
        reason = self.reason(self.hook(reply))
        self.assertIn(message, reason)
        return reason

    def assert_passes(self, reply):
        result = self.hook(reply)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '', 'a clean reply prints nothing: ' + result.stdout)

    def test_a_bare_key_blocks_the_reply(self):
        reason = self.assert_blocked('SOFT-3072 is first')
        self.assertIn('SOFT-3072', reason)

    def test_a_full_link_passes(self):
        self.assert_passes('the idle-stop removal: https://app.hypertask.ai/detail/project-2060/3072')

    def test_a_key_only_inside_a_code_block_passes(self):
        self.assert_passes('The fix sits here:\n\n```\ngit log --grep SOFT-3072\n```\n\nIt stops the idle kill.')

    def test_a_key_only_in_his_own_words_passes(self):
        self.assert_passes('You wrote:\n\n> what about SOFT-3072?\n\nThat one shipped yesterday.')

    def test_several_keys_are_all_named(self):
        reason = self.assert_blocked('VSTA-119 and SOFT-3072 both wait on the merge.')
        self.assertIn('VSTA-119', reason)
        self.assertIn('SOFT-3072', reason)

    def test_an_inline_code_key_passes(self):
        self.assert_passes('The branch is `vsta-no-bare-ids`, named after the work, not the number.')

    def test_a_reply_without_a_key_passes(self):
        self.assert_passes('The idle-stop removal is live. Two of three checks pass.')

    def test_an_encoding_name_is_not_a_ticket(self):
        self.assert_passes('The file is read as UTF-8, then SHA-256 hashed.')

    def test_a_second_stop_does_not_loop(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        transcript = folder / 'transcript.jsonl'
        transcript.write_text(json.dumps(say('SOFT-3072 is first')) + '\n')
        result = subprocess.run([sys.executable, str(HOOK)], text=True, capture_output=True, check=False,
                                input=json.dumps({'stop_hook_active': True,
                                                  'transcript_path': str(transcript)}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '')

    def test_a_pull_request_link_alone_blocks_the_reply(self):
        reason = self.assert_blocked(f'The PR is up: {PR}', PR_MESSAGE)
        self.assertIn(PR, reason)

    def test_a_pull_request_link_with_its_ticket_link_passes(self):
        self.assert_passes(f'The PR is up: {PR}\nThe ticket: {TICKET}')

    def test_a_pull_request_link_only_inside_a_code_block_passes(self):
        self.assert_passes(f'Pushed this:\n\n```\n{PR}\n```\n\nCI is running.')

    def test_a_pull_request_link_only_in_his_own_words_passes(self):
        self.assert_passes(f'You wrote:\n\n> {PR}?\n\nThat one merged.')

    def test_several_pull_requests_with_one_ticket_link_pass(self):
        other = 'https://github.com/valentinyeo/vstack/pull/379'
        self.assert_passes(f'{PR} and {other} both serve {TICKET}')

    def test_a_bare_key_and_a_lone_pull_request_link_are_both_named(self):
        reason = self.assert_blocked(f'SOFT-3072 is {PR}')
        self.assertIn(MESSAGE, reason)
        self.assertIn(PR_MESSAGE, reason)

    def test_garbage_input_and_a_missing_transcript_pass(self):
        for payload in ('not json', '', 'null', '[]', json.dumps({'transcript_path': '/nonexistent/x.jsonl'})):
            with self.subTest(payload=payload):
                result = self.hook(payload=payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '')

    def test_its_self_test_passes(self):
        result = subprocess.run([sys.executable, str(HOOK), '--self-test'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('no-bare-ids self-test ok', result.stdout)


class Wiring(unittest.TestCase):
    """Loading valentin-mode is what switches the check on, so the wiring is the feature."""

    def test_the_skill_registers_the_stop_hook(self):
        text = SKILL.read_text()
        self.assertIn('command: python3 "$CLAUDE_PLUGIN_ROOT/no-bare-ids.py"', text)

    def test_the_hook_sits_beside_the_skill_as_a_link_to_the_shared_copy(self):
        self.assertTrue(BESIDE_SKILL.is_symlink(), 'no-bare-ids.py must be a symlink to the shared hook')
        self.assertEqual(BESIDE_SKILL.resolve(), HOOK.resolve())

    def test_the_rule_table_names_the_hook_and_this_test(self):
        text = RULES.read_text()
        self.assertIn('No bare ticket ids to Valentin', text)
        self.assertIn('hooks/no-bare-ids.py', text)
        self.assertIn('tests/test_no_bare_ids.py', text)


if __name__ == '__main__':
    unittest.main()
