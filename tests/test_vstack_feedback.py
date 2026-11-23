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


def opt(name, default=None):
    return a[a.index(name) + 1] if name in a else default


def find(ref):
    return next((t for t in s.get('tasks', []) if t.get('ticketNumber') == ref), None)


key = ' '.join(a[:2])
s['calls'].append(a)
if key == 'task list':
    status = opt('--status')
    project = opt('--project')
    label = opt('--labels') or ''
    rows = []
    for task in s.get('tasks', []):
        if project and str(task.get('projectId')) != project:
            continue
        if status and task.get('status') != status:
            continue
        names = {x.get('name') for x in task.get('labels', []) if isinstance(x, dict)}
        if label and not set(label.split(',')) & names:
            continue
        rows.append(task)
    p.write_text(json.dumps(s))
    print(json.dumps({'success': True, 'tasks': rows, 'nextCursor': None, 'has_more': False}))
elif key == 'task create':
    labels = [n for n in (opt('--labels') or '').split(',') if n]
    num = 100 + len(s.get('tasks', []))
    task = {'ticketNumber': f'VSTA-{num}', 'projectId': int(opt('--project') or 13556),
            'title': opt('--title'), 'status': 'Normal',
            'labels': [{'name': n} for n in labels], 'description': opt('--description') or ''}
    s.setdefault('tasks', []).append(task)
    s['created'] = s.get('created', 0) + 1
    p.write_text(json.dumps(s))
    print(json.dumps({'success': True, 'task': task}))
elif key == 'task get':
    task = find(a[2])
    if task is None:
        print(json.dumps({'success': False, 'error': 'not found'}))
        sys.exit(1)
    p.write_text(json.dumps(s))
    print(json.dumps({'success': True, 'tasks': [task]}))
elif key == 'task update':
    task = find(a[2])
    if task is None:
        print(json.dumps({'success': False, 'error': 'not found'}))
        sys.exit(1)
    if opt('--description') is not None:
        task['description'] = opt('--description')
    s['updated'] = s.get('updated', 0) + 1
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

    def create_call(self):
        return next(c for c in self.data()['calls'] if c[:2] == ['task', 'create'])

    def opt(self, call, name):
        return call[call.index(name) + 1] if name in call else None

    def add_task(self, **fields):
        state = self.data()
        task = {'ticketNumber': 'VSTA-42', 'projectId': 13556, 'title': 'Same title',
                'status': 'Normal', 'labels': [{'name': 'Vstack'}], 'description': ''}
        task.update(fields)
        state['tasks'] = [task]
        self.state.write_text(json.dumps(state))

    def test_creates_on_board_with_label(self):
        self.run_tool('Add a feedback command', '--why', 'Sessions cannot report vstack faults.')
        calls = self.data()['calls']
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:4], ['task', 'list', '--project', '13556'])
        create = self.create_call()
        self.assertEqual(self.opt(create, '--title'), 'Add a feedback command')
        self.assertEqual(self.opt(create, '--project'), '13556')
        self.assertEqual(self.opt(create, '--labels'), 'Vstack')
        self.assertEqual(self.data()['created'], 1)

    def test_refuses_without_agent_token(self):
        env = dict(self.env, SHIP_SESSION_NAME='Missing Agent')
        r = subprocess.run([str(TOOL), 'x', '--why', 'y'], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.data()['calls'], [])

    def test_skips_duplicate_title(self):
        self.add_task()
        out = self.run_tool('Same title', '--why', 'blocked').stdout
        self.assertIn('project-13556/42', out)
        self.assertIn('duplicate', out.lower())
        self.assertEqual(self.data().get('created', 0), 0)
        self.assertEqual(len(self.data()['calls']), 1)

    def test_label_and_board_options(self):
        self.run_tool(
            'A handover failed at read in Demo Chat', '--why', 'A fresh start failed.',
            '--board', '1234', '--label', 'Long Chat Handover', '--label', 'brain-medium')
        calls = self.data()['calls']
        self.assertEqual(calls[0][:4], ['task', 'list', '--project', '1234'])
        self.assertEqual(self.opt(calls[0], '--labels'), 'Long Chat Handover')
        create = self.create_call()
        self.assertEqual(self.opt(create, '--project'), '1234')
        self.assertEqual(self.opt(create, '--labels'), 'Long Chat Handover,brain-medium')

    def test_facts_reach_the_description(self):
        self.run_tool('Report the failure', '--why', 'A fresh start failed.',
                      '--fact', 'Chat: Demo Chat', '--fact', 'Failed step: read')
        description = self.opt(self.create_call(), '--description')
        self.assertIn('<li>Chat: Demo Chat</li>', description)
        self.assertIn('<li>Failed step: read</li>', description)

    def test_count_creates_with_seen_one(self):
        self.run_tool('Report the failure', '--why', 'A fresh start failed.',
                      '--count', '--fact', 'Chat: Demo Chat')
        description = self.opt(self.create_call(), '--description')
        self.assertIn('Seen 1 times.', description)
        self.assertIn('<strong>Done when</strong>', description)

    def test_count_bumps_the_open_ticket(self):
        self.add_task(
            title='Report the failure', labels=[{'name': 'Vstack'}], description='')
        out = self.run_tool('Report the failure', '--why', 'A fresh start failed.',
                            '--count', '--fact', 'Chat: Demo Chat').stdout
        data = self.data()
        self.assertEqual(data.get('created', 0), 0)
        self.assertEqual(data['updated'], 1)
        self.assertIn('project-13556/42', out)
        self.assertIn('Seen 2 times.', data['tasks'][0]['description'])

    def test_count_keeps_bumping(self):
        self.add_task(title='Report the failure', status='Normal',
                      labels=[{'name': 'Vstack'}],
                      description='<p>Seen 4 times. Last at old.</p>')
        self.run_tool('Report the failure', '--why', 'A fresh start failed.', '--count')
        self.assertIn('Seen 5 times.', self.data()['tasks'][0]['description'])

    def test_count_done_when_override(self):
        self.run_tool('Report the failure', '--why', 'A fresh start failed.', '--count',
                      '--done', 'A fresh start in this chat finishes.')
        description = self.opt(self.create_call(), '--description')
        self.assertIn('A fresh start in this chat finishes.', description)
        self.assertIn('Seen 1 times.', description)


if __name__ == '__main__':
    unittest.main()
