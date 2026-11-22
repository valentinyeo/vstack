"""Synthetic transcripts only. The measurement must never print private text."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/reply-verbosity.py'
spec = importlib.util.spec_from_file_location('verbosity', SCRIPT)
verbosity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verbosity)
SINCE = datetime(2026, 11, 19, tzinfo=timezone.utc)
UNTIL = datetime(2026, 11, 22, tzinfo=timezone.utc)


def user(text, **extra):
    return {'type': 'user', 'message': {'content': text}, **extra}


def reply(text, ident='reply', stop='end_turn', when='2026-11-21T12:00:00Z'):
    return {'type': 'assistant', 'uuid': ident, 'timestamp': when,
            'message': {'id': ident, 'stop_reason': stop,
                        'content': [{'type': 'text', 'text': text}]}}


LOAD = user('<command-name>/valentin-mode</command-name>', uuid='load')


class ReplyVerbosity(unittest.TestCase):
    def read(self, entries, seen=None):
        from collections import Counter
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'transcript.jsonl'
            path.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
            return list(verbosity.read_replies(path, SINCE, UNTIL,
                                              seen if seen is not None else set(), Counter()))

    def test_only_loaded_main_chat_end_turn_text_inside_window(self):
        entries = [reply('before loading', 'before'), LOAD,
                   reply('pre-tool text', 'tool', stop='tool_use'),
                   reply('old text', 'old', when='2026-11-18T12:00:00Z'),
                   reply('subagent text', 'side') | {'isSidechain': True},
                   reply('at upper boundary', 'upper', when=UNTIL.isoformat()),
                   user('A human question'), reply('The answer is four words')]
        self.assertEqual(self.read(entries), [(5, 0, 0, 0)])

    def test_split_api_blocks_join_into_one_reply(self):
        first = reply('First half', 'block1')
        second = reply('second half', 'block2')
        first['message']['id'] = second['message']['id'] = 'shared'
        first['message']['content'].insert(0, {'type': 'thinking', 'thinking': 'not counted'})
        self.assertEqual(self.read([LOAD, first, second]), [(4, 0, 0, 0)])

    def test_duplicate_rows_and_copied_history_keep_load_context(self):
        seen = set()
        entries = [LOAD, reply('Already counted', 'same')]
        self.assertEqual(self.read(entries, seen), [(2, 0, 0, 0)])
        self.assertEqual(self.read(entries + [reply('New answer', 'new')], seen), [(2, 0, 0, 0)])

    def test_notifications_keep_attribution_through_tools_and_skill_expansions(self):
        for note in ('<task-notification>complete</task-notification>',
                     '<teammate-message teammate_id="peer">note</teammate-message>',
                     '[Message from session peer] note',
                     "The user hasn't heard from you in a while"):
            with self.subTest(note=note):
                entries = [LOAD, user('Do the job'), user(note),
                           user([{'type': 'tool_result', 'content': 'result'}]),
                           user('Base directory for this skill: /synthetic', isMeta=True),
                           reply('A notification answer')]
                self.assertEqual(self.read(entries), [(3, 0, 3, 0)])

    def test_queued_human_message_resets_notification_attribution(self):
        entries = [LOAD, user('<task-notification/>'),
                   {'type': 'attachment', 'attachment': {'type': 'queued_command',
                                                        'prompt': 'A new human question'}},
                   reply('A direct answer')]
        self.assertEqual(self.read(entries), [(3, 0, 0, 0)])

    def test_running_tail_and_exact_status_repeat_not_changed_numbers(self):
        previous = 'Two checks are done.\nStill running: worker one.'
        current = 'Three checks are done.\n\nStill running: worker one.'
        self.assertEqual(verbosity.category_counts(current, previous), (4, 4))
        self.assertEqual(verbosity.category_counts('Running improves fitness.', ''), (0, 0))

    def test_summary_uses_nearest_rank_p90_and_overlapping_word_shares(self):
        result = verbosity.summarize([(n, 1, n, 1) for n in range(1, 11)])
        self.assertEqual(result['reply_count'], 10)
        self.assertEqual(result['median_words'], 5.5)
        self.assertEqual(result['p90_words'], 9)
        self.assertEqual(result['categories']['notification_reply']['share_pct'], 100)
        self.assertEqual(verbosity.summarize([])['p90_words'], 0)

    def test_cli_emits_only_aggregates_not_message_text_or_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project' / 'private-session.jsonl'
            path.parent.mkdir()
            path.write_text('\n'.join(json.dumps(e) for e in
                                      [LOAD, user('secret human text'), reply('secret answer')]))
            result = subprocess.run([sys.executable, str(SCRIPT), '--root', folder,
                                     '--since', SINCE.isoformat(), '--until', UNTIL.isoformat()],
                                    capture_output=True, text=True, timeout=10, check=True)
            output = json.loads(result.stdout)
            self.assertEqual(output['reply_count'], 1)
            for private in ('secret', 'private-session', folder, 'valentin-mode'):
                self.assertNotIn(private, result.stdout)


if __name__ == '__main__':
    unittest.main()
