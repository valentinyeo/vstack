#!/usr/bin/env python3
"""Drive vstack-feedback against a stateful fake hypertask."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'skills/vstack-feedback/vstack-feedback'

FAKE = '''#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ['FAKE_STATE'])
s = json.loads(p.read_text())
a = sys.argv[1:]
if '--token' in a:
    i = a.index('--token')
    if a[i + 1] != 'agent-test-token':
        sys.exit(3)
    del a[i:i + 2]
if '--json' in a:
    a.remove('--json')
key = ' '.join(a[:2])
s['calls'].append(a)
if key == 'task list':
    status = a[a.index('--status') + 1] if '--status' in a else None
    project = a[a.index('--project') + 1] if '--project' in a else None
    label = a[a.index('--labels') + 1] if '--labels' in a else ''
    rows = []
    for task in s.get('tasks', []):
        if project and str(task.get('projectId')) != project:
            continue
        if status and task.get('status') != status:
            continue
        names = {x.get('name') for x in task.get('labels', []) if isinstance(x, dict)}
        if label and label not in names:
            continue
        rows.append(task)
    p.write_text(json.dumps(s))
    print(json.dumps({'success': True, 'tasks': rows, 'nextCursor': None, 'has_more': False}))
elif key == 'task create':
    assert a[a.index('--project') + 1] == '13556'
    labels = set(a[a.index('--labels') + 1].split(','))
    assert labels == {'Vstack'}, labels
    title = a[a.index('--title') + 1]
    num = 100 + len(s.get('tasks', []))
    task = {'ticketNumber': f'VSTA-{num}', 'projectId': 13556, 'title': title,
            'status': 'Normal', 'labels': [{'name': n} for n in labels]}
    s.setdefault('tasks', []).append(task)
    s['created'] = s.get('created', 0) + 1
    p.write_text(json.dumps(s))
    print(json.dumps({'success': True, 'task': task}))
else:
  raise SystemExit(f'unexpected {key}')
'''


class Feedback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        token = home / '.config/hypertask-agents/credentials/sessions/vstack-maintainer-agent-token'
        token.parent.mkdir(parents=True)
        token.write_text('agent-test-token')
        binary = home / 'bin' / 'hypertask'
        binary.parent.mkdir(parents=True)
        binary.write_text(FAKE)
        binary.chmod(0o755)
        self.state = home / 'state.json'
        self.state.write_text(json.dumps({'calls': [], 'tasks': []}))
        self.env = dict(
            os.environ,
            HOME=str(home),
            PATH=f'{binary.parent}:{os.environ.get("PATH", "")}',
            FAKE_STATE=str(self.state),
            SHIP_SESSION_NAME='Vstack Maintainer',
        )

    def run_tool(self, *args, success=True):
        r = subprocess.run([str(TOOL), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode == 0, success, r.stdout + r.stderr)
        self.assertNotIn('agent-test-token', r.stdout + r.stderr)
        return r

    def data(self):
        return json.loads(self.state.read_text())

    def test_creates_on_board_with_label(self):
        self.run_tool('Add a feedback command', '--why', 'Sessions cannot report vstack faults.')
        calls = self.data()['calls']
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:4], ['task', 'list', '--project', '13556'])
        create = calls[1]
        self.assertEqual(create[create.index('--title') + 1], 'Add a feedback command')
        self.assertEqual(self.data()['created'], 1)

    def test_refuses_without_agent_token(self):
        env = dict(self.env, SHIP_SESSION_NAME='Missing Agent')
        r = subprocess.run([str(TOOL), 'x', '--why', 'y'], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.data()['calls'], [])

    def test_skips_duplicate_title(self):
        state = self.data()
        state['tasks'] = [{'ticketNumber': 'VSTA-42', 'projectId': 13556, 'title': 'Same title',
                           'status': 'Normal', 'labels': [{'name': 'Vstack'}]}]
        self.state.write_text(json.dumps(state))
        out = self.run_tool('Same title', '--why', 'blocked').stdout
        self.assertIn('project-13556/42', out)
        self.assertIn('duplicate', out.lower())
        self.assertEqual(self.data().get('created', 0), 0)
        self.assertEqual(len(self.data()['calls']), 1)


if __name__ == '__main__':
    unittest.main()