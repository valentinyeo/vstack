#!/usr/bin/env python3
"""Drive the CLI against a stateful fake Hypertask executable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE = '''#!/usr/bin/env python3
import json, os, pathlib, sys
p=pathlib.Path(os.environ['FAKE_STATE'])
s=json.loads(p.read_text())
a=sys.argv[1:]
if '--token' in a:
 i=a.index('--token'); assert a[i+1]=='private-test-token'; del a[i:i+2]
if '--json' in a:a.remove('--json')
key=' '.join(a[:2])
if '--help' in a:
 s['help'].append(key); p.write_text(json.dumps(s)); sys.exit(0)
assert key in s['help'], 'missing --help preflight'
s['calls'].append(a)
if s.get('fail')==key:
 p.write_text(json.dumps(s)); print('private-test-token failed',file=sys.stderr);sys.exit(1)
if key=='task create':
 assert a[a.index('--section')+1]=='Todo'
 assert set(a[a.index('--labels')+1].split(','))=={'Poteto','brain-medium'}
 s['created']+=1;s['section']='Todo';out={'success':True,'task':{'id':99,'ticketNumber':'SOFT-99'}}
elif key=='task get':out={'tasks':[{'ticketNumber':'SOFT-99','projectId':s.get('board',2060)}]}
elif key=='task assign':s['owner']=a[a.index('--agent')+1];out={'success':True}
elif key=='task update':s['section']=a[a.index('--section')+1];out={'success':True}
elif key=='activity add':s['log'].append(a[a.index('--text')+1]);out={'success':True}
elif key=='comment add':s['comments'].append(a);out={'success':True}
elif key=='ai write':s['writer']+=1;assert '--apply' in a;out={'success':True}
else:raise Exception(key)
p.write_text(json.dumps(s));print(json.dumps(out))
'''


class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        token = home / '.config/hypertask-agents/credentials/sessions/poteto-agent-token'
        token.parent.mkdir(parents=True)
        token.write_text('private-test-token')
        binary = home / 'hypertask'
        binary.write_text(FAKE)
        binary.chmod(0o755)
        self.state = home / 'state.json'
        self.state.write_text(json.dumps(dict(help=[], calls=[], created=0, writer=0, log=[], comments=[])))
        self.env = dict(os.environ, HOME=str(home), PATH=f'{home}:'+os.environ['PATH'], FAKE_STATE=str(self.state))

    def run_cli(self, *args, success=True):
        r = subprocess.run([str(ROOT/'bin/poteto-ticket'), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode == 0, success, r.stdout+r.stderr)
        self.assertNotIn('private-test-token', r.stdout+r.stderr)
        return r

    def data(self):
        return json.loads(self.state.read_text())

    def alter(self, **values):
        d = self.data(); d.update(values); self.state.write_text(json.dumps(d))

    def test_six_commands(self):
        self.run_cli('new', 'Test the ticket workflow')
        self.run_cli('claim', '99')
        self.assertEqual(self.data()['owner'], 'Poteto')
        self.assertEqual(self.data()['section'], 'Doing')
        self.assertEqual(self.data()['log'], ['Claimed.'])
        self.run_cli('log', 'SOFT-99', 'Work continues.')
        self.assertEqual(self.data()['comments'], [])
        self.run_cli('review', 'SOFT-99')
        self.assertEqual(self.data()['section'], 'AI Review')
        self.run_cli('ask', 'SOFT-99', 'Approve this spend?')
        self.assertEqual(self.data()['section'], 'Valentin Review')
        self.assertIn('question', self.data()['comments'][-1])
        self.run_cli('done', 'SOFT-99', 'https://github.com/a/b/pull/1#issuecomment-12')
        self.assertEqual(self.data()['section'], 'Done')
        self.assertIn('done', self.data()['comments'][-1])
        self.assertEqual(self.data()['writer'], 1)
        self.assertEqual(self.data()['created'], 1)

    def test_claim_and_log_with_agent_lane_shim(self):
        home = Path(self.tmp.name)
        shims = home / 'shims'
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/worker-shims'), '--dir', str(shims),
             '--path', self.env['PATH']], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.env['PATH'] = f'{shims}:' + self.env['PATH']
        self.run_cli('claim', 'SOFT-99')
        self.run_cli('log', 'SOFT-99', 'Work continues.')
        self.assertEqual(self.data()['log'], ['Claimed.', 'Work continues.'])
        result = self.run_cli('log', 'SOFT-99', 'PASS: verified', success=False)
        self.assertIn('agent-lane-guard', result.stderr)
        self.assertEqual(self.data()['log'], ['Claimed.', 'Work continues.'])

    def test_invalid_proof_never_writes(self):
        for proof in ['missing', 'https://example.com', 'https://github.com/a/b/pull/1',
                      'https://github.com.evil/a/b/pull/1#issuecomment-1']:
            self.run_cli('done', '99', proof, success=False)
        self.assertEqual(self.data()['calls'], [])

    def test_failed_claim_does_not_move(self):
        self.alter(fail='task assign')
        self.run_cli('claim', '99', success=False)
        self.assertNotIn('section', self.data())

    def test_failed_writer_resumes_without_duplicate(self):
        self.alter(fail='ai write')
        self.assertIn('SOFT-99', self.run_cli('new', 'Test workflow', success=False).stdout)
        self.alter(fail=None)
        self.run_cli('new', 'Test workflow', '--task', 'SOFT-99')
        self.assertEqual(self.data()['created'], 1)
        self.assertEqual(self.data()['writer'], 1)

    def test_foreign_board_never_writes(self):
        self.alter(board=15)
        self.run_cli('claim', 'SOFT-99', success=False)
        self.assertEqual([c[:2] for c in self.data()['calls']], [['task','get']])

    def test_failed_done_comment_does_not_close(self):
        self.alter(fail='comment add')
        self.run_cli('done', '99', 'https://github.com/a/b/actions/runs/1', success=False)
        self.assertNotIn('section', self.data())


if __name__ == '__main__':
    unittest.main()
