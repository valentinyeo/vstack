import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'hooks/valentin_mode_loaded.py'
FIXTURES = ROOT / 'tests/fixtures/valentin-mode'
LOADED = ('command.jsonl', 'skill-call.jsonl', 'base-dir.jsonl')
PLAIN = 'plain.jsonl'


def module():
    spec = importlib.util.spec_from_file_location('valentin_mode_loaded', MODULE)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class ValentinModeLoaded(unittest.TestCase):
    def test_its_self_test_passes(self):
        result = subprocess.run([sys.executable, str(MODULE), '--self-test'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('valentin-mode-loaded self-test ok', result.stdout)

    def test_each_real_load_shape_counts(self):
        valentin = module()
        for fixture in LOADED:
            with self.subTest(fixture=fixture):
                self.assertTrue(valentin.loaded(str(FIXTURES / fixture)),
                                f'{fixture} shows valentin-mode loaded')

    def test_a_chat_that_only_mentions_the_skill_is_not_loaded(self):
        valentin = module()
        self.assertFalse(valentin.loaded(str(FIXTURES / PLAIN)),
                         'a plain chat that names valentin-mode never loaded it')

    def test_a_missing_unreadable_or_absent_transcript_is_not_loaded(self):
        valentin = module()
        self.assertFalse(valentin.loaded(str(FIXTURES / 'missing.jsonl')), 'a missing transcript allows')
        self.assertFalse(valentin.loaded(str(FIXTURES)), 'a directory is not a transcript')
        self.assertFalse(valentin.loaded(None), 'no transcript allows')
        self.assertFalse(valentin.loaded(''), 'an empty path allows')
        with tempfile.TemporaryDirectory() as where:
            self.assertFalse(valentin.loaded(str(Path(where, 'empty.jsonl'))), 'an empty transcript allows')

    def test_a_marker_across_a_chunk_boundary_still_counts(self):
        valentin = module()
        with tempfile.TemporaryDirectory() as where:
            path = Path(where, 'large.jsonl')
            path.write_text('{"type":"user","message":{"content":"' + 'x' * (valentin.CHUNK - 20) +
                            '<command-name>/valentin-mode</command-name>"}}\n')
            self.assertTrue(valentin.loaded(str(path)), 'the streaming read keeps a carry')
            self.assertLess(path.stat().st_size, 4 * valentin.CHUNK, 'one large chunk is enough for this test')

    def test_a_load_late_in_a_long_chat_is_found(self):
        valentin = module()
        with tempfile.TemporaryDirectory() as where:
            path = Path(where, 'late.jsonl')
            path.write_text('{"type":"user","message":{"content":"' + 'x' * (2 * valentin.CHUNK) +
                            '"}}\n{"type":"user","message":{"content":'
                            '"<command-name>/valentin-mode</command-name>"}}\n')
            self.assertTrue(valentin.loaded(str(path)), 'a load two chunks into a chat is still found')

    def test_install_links_the_boundary_reader_and_book_check(self):
        text = (ROOT / 'install').read_text()
        for name in ('valentin_mode_loaded.py', 'book-check.py'):
            with self.subTest(name=name):
                self.assertIn(f'link_one {name} "$ROOT/hooks/{name}" "$HOME/.claude/hooks"', text)


if __name__ == '__main__':
    unittest.main()
