#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallClaim(unittest.TestCase):
    def test_install_idempotent_and_actual_hook_routes_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            guard = home / '.claude/hooks/ticket-first-guard.py'
            guard.parent.mkdir(parents=True)
            guard.write_text('def claim(data):\n    return 47\n')
            env = dict(os.environ, HOME=directory)
            for _ in range(2):
                subprocess.run([sys.executable, str(ROOT/'bin/install-ticket-claim')], env=env, check=True, capture_output=True)
            self.assertEqual(guard.read_text().count('# poteto-ticket claim route'), 1)
            helper = home / '.local/lib/poteto-ticket/poteto-ticket'
            self.assertEqual(helper.read_bytes(), (ROOT/'bin/poteto-ticket').read_bytes())
            helper.write_text('import sys\nprint("CLAIM", *sys.argv[1:])\n')
            driver = '''import json,re,sys
from pathlib import Path
import subprocess
WORKER=re.compile(r'codex exec')
def brief_text(cmd):return ''
exec(Path(sys.argv[1]).read_text())
sys.exit(claim(json.loads(sys.argv[2])))
'''
            data = {'cwd': str(ROOT), 'tool_name': 'Bash', 'tool_input': {
                'command': 'codex exec "Fix https://app.hypertask.ai/detail/project-2060/2573"'}}
            r = subprocess.run([sys.executable, '-c', driver, str(guard), json.dumps(data)], env=env, text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('CLAIM claim SOFT-2573', r.stdout)
            data['cwd'] = '/unrelated'
            r = subprocess.run([sys.executable, '-c', driver, str(guard), json.dumps(data)], env=env, capture_output=True)
            self.assertEqual(r.returncode, 47)


if __name__ == '__main__':
    unittest.main()
