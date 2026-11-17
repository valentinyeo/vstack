import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/book-check.py'
spec = importlib.util.spec_from_file_location('book_check', HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
FULL = hook.FAULTS + '\nBook check:\n' + '\n'.join(f'- {item}: covered' for item in hook.ITEMS)


class FaultRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.brief = Path(self.tmp.name) / 'brief.md'
        self.brief.write_text(FULL)

    def check(self, command, expected):
        result = subprocess.run([sys.executable, str(HOOK)], text=True, capture_output=True,
                                input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}}))
        self.assertEqual(result.returncode, expected, result.stderr)

    def test_bulleted_fault_line(self):
        for marker in ['- ', '* ', '+ ', '1. ']:
            with self.subTest(marker=marker):
                self.brief.write_text(marker + FULL)
                self.check(f'codex exec "$(cat {self.brief})"', 0)

    def test_background_spawn_reads_brief(self):
        for suffix in [' &', ' && echo done', '; echo done', ' > /tmp/worker.log 2>&1 &']:
            with self.subTest(suffix=suffix):
                self.check(f'spawn-worker {self.brief}{suffix}', 0)

    def test_long_print_option_requires_fault_routes(self):
        for launcher in ['pi', 'hax']:
            with self.subTest(launcher=launcher):
                self.check(launcher + ' --print ' + shlex.quote(FULL.replace(hook.FAULTS, '')), 2)
                self.check(launcher + ' --print ' + shlex.quote(FULL), 0)

    def test_prefixed_launches_cannot_skip_gates(self):
        for prefix in ['nohup', 'setsid', 'sudo', 'command', 'nice -n 5', 'stdbuf -oL', 'xargs -I{}', 'exec']:
            with self.subTest(prefix=prefix):
                self.brief.write_text('missing book and routes')
                self.check(f'{prefix} codex exec "$(cat {self.brief})"', 2)
                self.brief.write_text(FULL)
                self.check(f'{prefix} codex exec "$(cat {self.brief})"', 0)

    def test_spawn_brief_flag_before_other_options(self):
        self.check(f'spawn-worker --brief {self.brief} --level normal', 0)
        self.brief.write_text(FULL.replace(hook.FAULTS, ''))
        self.check(f'spawn-worker --brief {self.brief} --level normal', 2)

    def test_fault_rule_renders_inside_rule_table(self):
        table = (ROOT / 'CLAUDE.md').read_text().splitlines()
        row = next(i for i, line in enumerate(table) if 'Worker briefs name both fault destinations' in line)
        start = row
        while start and table[start - 1].startswith('|'):
            start -= 1
        self.assertTrue(any('---' in line for line in table[start:row]), 'fault rule detached from table header')


if __name__ == '__main__':
    unittest.main()
