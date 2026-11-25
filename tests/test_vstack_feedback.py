#!/usr/bin/env python3
"""Drive vstack-feedback against a stateful fake hypertask."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'skills/vstack-feedback/vstack-feedback'
TOKENS = '.config/hypertask-agents/credentials/sessions'
CHAT_TOKEN = 'chat-test-token'
MAINTAINER_TOKEN = 'agent-test-token'

FAKE = '''#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ['FAKE_STATE'])
s = json.loads(p.read_text())
a = sys.argv[1:]
refused = [t for t in (os.environ.get('FAKE_REFUSE') or '').split(',') if t]
if '--token' in a:
    i = a.index('--token')
    used = a[i + 1]
    del a[i:i + 2]
    s.setdefault('tokens', []).append(used)
    if used in refused:
        s.setdefault('refused', []).append(used)
        p.write_text(json.dumps(s))
        print(json.dumps({'success': False, 'error': 'Task not found or access denied'}))
        sys.exit(1)
if '--json' in a:
    a.remove('--json')


def opt(name, default=None):
    return a[a.index(name) + 1] if name in a else default


def find(ref):
    return next((t for t in s.get('tasks', []) if t.get('ticketNumber') == ref), None)


key = ' '.join(a[:2])
s['calls'].append(a)
if key == 'task list' and os.environ.get('FAKE_REASON'):
    print('the server rejected the command input', file=sys.stderr)
    print(json.dumps({'success': False, 'error': os.environ['FAKE_REASON']}))
    sys.exit(1)
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
        self.home = Path(self.tmp.name)
        for name, token in (('vstack-maintainer', MAINTAINER_TOKEN),
                            ('demo-chat', CHAT_TOKEN)):
            path = self.home / TOKENS / f'{name}-agent-token'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(token)
        binary = self.home / 'bin' / 'hypertask'
        binary.parent.mkdir(parents=True)
        binary.write_text(FAKE)
        binary.chmod(0o755)
        self.state = self.home / 'state.json'
        self.state.write_text(json.dumps({'calls': [], 'tasks': []}))
        self.env = dict(
            os.environ,
            HOME=str(self.home),
            PATH=f'{binary.parent}:{os.environ.get("PATH", "")}',
            FAKE_STATE=str(self.state),
            FAKE_REFUSE='',
            SHIP_SESSION_NAME='Vstack Maintainer',
            MULTIPROMPT_TAB='',
            HYPERTASK_AGENT_TOKEN_FILE='',
        )

    def run_env(self, *args, **changes):
        env = dict(self.env, **changes)
        return subprocess.run([str(TOOL), *args], env=env, capture_output=True, text=True)

    def run_tool(self, *args, success=True):
        r = self.run_env(*args)
        self.assertEqual(r.returncode == 0, success, r.stdout + r.stderr)
        self.assertNotIn(MAINTAINER_TOKEN, r.stdout + r.stderr)
        self.assertNotIn(CHAT_TOKEN, r.stdout + r.stderr)
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
        r = self.run_env('x', '--why', 'y', SHIP_SESSION_NAME='Missing Agent')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.data()['calls'], [])

    def chat_names(self, tab, name):
        path = self.home / '.local/state/multiprompt/chat-names.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({tab: {'name': name}}))

    def test_ship_session_name_wins_when_the_tab_name_has_no_token(self):
        self.chat_names('tab-1', 'HT Mobile Design')
        r = self.run_env('Add a feedback command', '--why', 'x',
                         MULTIPROMPT_TAB='tab-1', SHIP_SESSION_NAME='Demo Chat')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(set(self.data()['tokens']), {CHAT_TOKEN})
        self.assertNotIn('HT Mobile Design', r.stderr)

    def test_an_explicit_token_file_wins_over_every_name(self):
        self.chat_names('tab-1', 'HT Mobile Design')
        explicit = self.home / 'given-agent-token'
        explicit.write_text(CHAT_TOKEN)
        r = self.run_env('Add a feedback command', '--why', 'x',
                         MULTIPROMPT_TAB='tab-1', SHIP_SESSION_NAME='Vstack Maintainer',
                         HYPERTASK_AGENT_TOKEN_FILE=str(explicit))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(set(self.data()['tokens']), {CHAT_TOKEN})

    def test_a_missing_explicit_token_file_names_its_source(self):
        missing = self.home / 'gone-agent-token'
        r = self.run_env('Add a feedback command', '--why', 'x',
                         HYPERTASK_AGENT_TOKEN_FILE=str(missing))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('HYPERTASK_AGENT_TOKEN_FILE', r.stderr)
        self.assertIn(str(missing), r.stderr)
        self.assertEqual(self.data()['calls'], [])

    def test_the_chat_name_still_names_the_login_when_neither_var_is_set(self):
        self.chat_names('tab-1', 'Demo Chat')
        r = self.run_env('Add a feedback command', '--why', 'x',
                         MULTIPROMPT_TAB='tab-1', SHIP_SESSION_NAME='')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(set(self.data()['tokens']), {CHAT_TOKEN})

    def test_finds_hypertask_in_local_bin_when_path_has_none(self):
        local = self.home / '.local/bin'
        local.mkdir(parents=True)
        shutil.copy(self.env['PATH'].split(':')[0] + '/hypertask', local / 'hypertask')
        r = self.run_env('Add a feedback command', '--why', 'x', PATH='/usr/bin:/bin')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.data()['created'], 1)

    def test_refused_chat_files_through_the_maintainer_login(self):
        r = self.run_env('Add a feedback command', '--why', 'not a member of this board',
                         SHIP_SESSION_NAME='Demo Chat', FAKE_REFUSE=CHAT_TOKEN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.data()['refused'], [CHAT_TOKEN])
        self.assertEqual(self.data()['tokens'][-1], MAINTAINER_TOKEN)
        description = self.opt(self.create_call(), '--description')
        self.assertIn('<li>Filed for: Demo Chat</li>', description)
        self.assertIn('not a member of this board', description)
        for token in (CHAT_TOKEN, MAINTAINER_TOKEN):
            self.assertNotIn(token, r.stdout + r.stderr)

    def test_shows_the_board_reason_not_the_generic_stderr_line(self):
        r = self.run_env('Add a feedback command', '--why', 'x',
                         FAKE_REASON=f'text: Keep each sentence within twelve words ({CHAT_TOKEN})')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('Keep each sentence within twelve words', r.stderr)
        self.assertNotIn('the server rejected the command input', r.stderr)
        for token in (CHAT_TOKEN, MAINTAINER_TOKEN):
            self.assertNotIn(token, r.stdout + r.stderr)

    def test_both_logins_refused_is_a_clear_error(self):
        r = self.run_env('Add a feedback command', '--why', 'x',
                         SHIP_SESSION_NAME='Demo Chat',
                         FAKE_REFUSE=f'{CHAT_TOKEN},{MAINTAINER_TOKEN}')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('access denied', r.stderr)
        self.assertIn('Vstack Maintainer', r.stderr)
        self.assertEqual(self.data().get('created', 0), 0)
        for token in (CHAT_TOKEN, MAINTAINER_TOKEN):
            self.assertNotIn(token, r.stdout + r.stderr)

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
