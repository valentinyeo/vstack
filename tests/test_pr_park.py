import argparse
import base64
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/board-drain'
LABEL = 'Board Drain Loop'
REPO = 'valentinyeo/vstack'
NOW = 1800000000
COMMENT = 'parked: over the 5-per-agent cap; branch kept, reopen when a slot frees'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


drain = load('pr_park_drain_test', SKILL / 'drain-check')

FAKE = r'''#!/usr/bin/python3
import json, os, re, sys
from pathlib import Path
path = Path(os.environ['PARK_FAKE_STATE'])
data = json.loads(path.read_text())
args = sys.argv[1:]
cli = Path(sys.argv[0]).name
with Path(os.environ['PARK_FAKE_LOG']).open('a') as log:
    log.write(json.dumps({'cli': cli, 'args': args,
                         'own': os.environ.get('HT_TOKEN') == data['token']
                         and os.environ.get('HYPERTASKS_JWT_TOKEN') == data['token']}) + '\n')
def save():
    path.write_text(json.dumps(data))
def answer(value):
    print(json.dumps(value))
    sys.exit(0)
def fail(text):
    print(text, file=sys.stderr)
    sys.exit(1)
if cli == 'gh':
    if args[:2] == ['pr', 'close']:
        assert args[3:] == ['--comment', data['comment']], args
        pull = next(p for p in data['pulls'] if p['url'] == args[2])
        assert pull['state'] == 'OPEN'
        pull['state'] = 'CLOSED'
        save()
        sys.exit(0)
    if args[:2] == ['pr', 'reopen']:
        assert len(args) == 3, args
        pull = next(p for p in data['pulls'] if p['url'] == args[2])
        assert pull['state'] == 'CLOSED'
        pull['state'] = 'OPEN'
        save()
        sys.exit(0)
    if data.get('read_error'):
        fail('offline')
    if 'search/issues' in args:
        print(data.get('count', 10))
        sys.exit(0)
    if args[:3] == ['api', 'graphql', '-f']:
        query = args[3]
        if 'search(query:' in query:
            pulls = [p for p in data['pulls'] if p['state'] == 'OPEN']
            answer({'data': {'search': {'issueCount': len(pulls), 'nodes': pulls,
                    'pageInfo': {'hasNextPage': False}}}})
        refs = re.findall(r'p(\d+):repository\(.*?pullRequest\(number:(\d+)\)', query)
        assert refs, query
        nodes = {}
        for alias, number in refs:
            pull = next(p for p in data['pulls'] if p['number'] == int(number))
            nodes['p' + alias] = {'pullRequest': pull}
        answer({'data': nodes})
if cli == 'hypertask':
    assert args.pop(0) == '--json', args
    if args == ['context']:
        answer({'connected_agent': {'id': 'agent-1' if os.environ.get('HT_TOKEN') == data['token'] else 'wrong'}})
    if args == ['project', 'show', '13556']:
        answer({'project': {'uniqueIdentifier': 'VSTA', 'sections': [
            {'section_title': s} for s in ('Todo', 'Doing', 'Checks', 'AI Review', 'Done')]}})
    if args[:2] == ['task', 'list']:
        answer({'tasks': data['tasks']})
    if args[:2] == ['task', 'move']:
        assert os.environ.get('HT_TOKEN') == data['token']
        assert os.environ.get('HYPERTASKS_JWT_TOKEN') == data['token']
        if data.pop('fail_move', False):
            save()
            fail('move interrupted')
        task = next(t for t in data['tasks'] if t['ticketNumber'] == args[2])
        assert args[3] == '--section'
        task['section'] = args[4]
        save()
        answer({'success': True})
fail('unexpected fake command: ' + cli + ' ' + repr(args))
'''


def pull(number, key=None):
    return {'url': f'https://github.com/{REPO}/pull/{number}', 'number': number,
            'state': 'OPEN', 'title': f'fix: VSTA-{key or number}',
            'body': '', 'headRefName': f'vsta-{key or number}', 'baseRefName': 'main',
            'createdAt': f'2026-11-{number:02d}T00:00:00Z',
            'repository': {'nameWithOwner': REPO}}


def task(number, label=LABEL, section='Checks'):
    return {'ticketNumber': f'VSTA-{number}', 'projectId': 13556, 'section': section,
            'labels': [{'name': label}], 'updatedAt': '2026-11-25T00:00:00Z',
            'assignees': [{'type': 'agent', 'agentId': 'agent-1'}]}


class ParkingTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.home = Path(self.scratch.name)
        self.bin = self.home / '.local/bin'
        self.bin.mkdir(parents=True)
        for name in ('gh', 'hypertask'):
            path = self.bin / name
            path.write_text(FAKE)
            path.chmod(0o755)
        self.state = self.home / 'state.json'
        self.log = self.home / 'calls.jsonl'
        claim = base64.urlsafe_b64encode(json.dumps({'agentId': 'agent-1'}).encode()).decode().rstrip('=')
        self.token = f'fake.{claim}.signature'
        credentials = self.home / '.config/hypertask-agents/credentials/sessions'
        credentials.mkdir(parents=True)
        (credentials / 'board-drain-loop-agent-token').write_text(self.token)
        self.env = {'HOME': str(self.home), 'PATH': f'{self.bin}:/usr/bin:/bin',
                    'SHIP_SESSION_NAME': LABEL, 'MULTIPROMPT_TAB': '',
                    'PARK_FAKE_STATE': str(self.state), 'PARK_FAKE_LOG': str(self.log),
                    'HT_TOKEN': 'wrong-inherited-token', 'HYPERTASKS_JWT_TOKEN': 'wrong-inherited-token'}
        env_patch = patch.dict(os.environ, self.env)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        drain.reconcile.reset_aliases()
        drain.repo_cap._warned.clear()
        self.seed(6)

    def seed(self, count):
        self.state.write_text(json.dumps({'token': self.token, 'comment': COMMENT,
                              'tasks': [task(n) for n in range(1, count + 1)],
                              'pulls': [pull(n) for n in range(1, count + 1)]}))

    def data(self):
        return json.loads(self.state.read_text())

    def update(self, **values):
        self.state.write_text(json.dumps(dict(self.data(), **values)))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def writes(self):
        return [c for c in self.calls() if c['args'][:2] in
                (['pr', 'close'], ['pr', 'reopen']) or c['args'][:3] == ['--json', 'task', 'move']]

    def run_park(self, *mode):
        return subprocess.run([sys.executable, str(SKILL / 'pr-park'), '--board', '13556',
                               '--label', LABEL, *mode], capture_output=True, text=True, timeout=30)

    def run_check(self):
        args = argparse.Namespace(board=13556, label=LABEL, fixture=None, no_load=True, state_name=None)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output), \
                patch.object(drain, 'pull_facts', return_value={}), \
                patch.object(drain, 'rule_breaks', return_value=[]), \
                patch.object(drain, 'alive', return_value=True), \
                patch.object(drain, 'live_worker', return_value=True), \
                patch.object(drain.merge_gate, 'gate_findings', return_value=[]):
            code = drain.check(args, NOW)
        return code, output.getvalue()

    def test_five_open_allows(self):
        # Four cards in the working columns and a fifth in Todo, so wip-cap's ticket
        # cap stays quiet and the five open PRs are the only question asked.
        self.update(tasks=[task(n) for n in range(1, 5)] + [task(5, section='Todo')])
        code, text = self.run_check()
        self.assertEqual(code, 0, text)
        self.assertNotIn('agent PR cap:', text)
        self.assertEqual(self.writes(), [])

    def test_six_open_fails_and_names_newest(self):
        code, text = self.run_check()
        self.assertEqual(code, 1, text)
        self.assertIn('owns 6 open PRs (cap 5)', text)
        line = next(line for line in text.splitlines() if line.startswith('agent PR cap:'))
        self.assertIn('VSTA-6 https://github.com/valentinyeo/vstack/pull/6', line)
        self.assertNotIn('/pull/5', line)

    def test_multiple_extras_newest_first_and_other_label_ignored(self):
        self.seed(8)
        data = self.data()
        data['tasks'][-1]['labels'] = [{'name': 'Other Chat'}]
        self.update(tasks=data['tasks'])
        code, text = self.run_check()
        self.assertEqual(code, 1, text)
        line = next(line for line in text.splitlines() if line.startswith('agent PR cap:'))
        self.assertIn('owns 7', line)
        self.assertLess(line.index('/pull/7'), line.index('/pull/6'))
        self.assertNotIn('/pull/8', line)

    def test_matching_body_branch_link_alias_and_deduplicating(self):
        self.seed(5)
        data = self.data()
        data['pulls'][0].update(title='plain', headRefName='plain', body='Ticket: VSTA-1')
        data['pulls'][1].update(title='plain', headRefName='feature/vsta-2-fix')
        data['pulls'][2].update(title='plain', headRefName='plain')
        data['tasks'][2]['pullRequests'] = [{'url': data['pulls'][2]['url']}]
        data['pulls'][3].update(title='fix: OLD-4', headRefName='old-4')
        data['pulls'][4].update(title='fix VSTA-5 and VSTA-1')
        self.update(**data)
        board = drain.reconcile.board_config(13556)
        with patch.object(drain.reconcile, 'aliases_of', side_effect=lambda k, b: ('OLD-4',) if k == 'VSTA-4' else ()):
            opened = drain.pr_park.owned_pulls(data['tasks'], board)
        self.assertEqual(len(opened), 5)
        self.assertEqual(opened[data['pulls'][4]['url']]['keys'], ['VSTA-1', 'VSTA-5'])

    def test_dry_run_default_and_explicit_never_write(self):
        for flags in ((), ('--dry-run',)):
            result = self.run_park(*flags)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('would park: https://github.com/valentinyeo/vstack/pull/6', result.stdout)
        self.assertEqual(self.writes(), [])
        self.assertFalse(list(self.home.glob('.local/state/board-drain/parked-*.json')))

    def test_parking_keeps_branch_moves_card_with_own_token_and_is_idempotent(self):
        result = self.run_park('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        writes = self.writes()
        self.assertEqual(writes[0]['args'], ['pr', 'close', pull(6)['url'], '--comment', COMMENT])
        self.assertEqual(writes[1]['args'], ['--json', 'task', 'move', 'VSTA-6', '--section', 'Todo'])
        self.assertTrue(writes[1]['own'])
        self.assertEqual(self.data()['pulls'][-1]['state'], 'CLOSED')
        self.assertEqual(self.data()['tasks'][-1]['section'], 'Todo')
        again = self.run_park('--apply')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.writes(), writes)
        self.assertNotIn('delete', self.log.read_text())

    def test_free_slot_reopens_oldest_and_second_run_is_noop(self):
        self.seed(7)
        first = self.run_park('--apply')
        self.assertEqual(first.returncode, 0, first.stderr)
        data = self.data()
        data['pulls'][0]['state'] = 'MERGED'
        self.update(pulls=data['pulls'])
        result = self.run_park('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.writes()[-2]['args'], ['pr', 'reopen', pull(6)['url']])
        self.assertEqual(self.data()['pulls'][5]['state'], 'OPEN')
        self.assertEqual(self.data()['tasks'][5]['section'], 'Checks')
        self.assertEqual(self.data()['pulls'][6]['state'], 'CLOSED')
        writes = self.writes()
        again = self.run_park('--apply')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.writes(), writes)

    def test_multiple_free_slots_fill_oldest_first_in_one_run(self):
        self.seed(7)
        self.assertEqual(self.run_park('--apply').returncode, 0)
        data = self.data()
        for p in data['pulls'][:2]:
            p['state'] = 'MERGED'
        self.update(pulls=data['pulls'])
        result = self.run_park('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        reopened = [c['args'][2] for c in self.writes() if c['args'][:2] == ['pr', 'reopen']]
        self.assertEqual(reopened, [pull(6)['url'], pull(7)['url']])
        writes = self.writes()
        self.assertEqual(self.run_park('--apply').returncode, 0)
        self.assertEqual(self.writes(), writes)

    def test_interrupted_close_card_move_is_retried_without_closing_twice(self):
        self.update(fail_move=True)
        self.assertEqual(self.run_park('--apply').returncode, 2)
        result = self.run_park('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.data()['tasks'][-1]['section'], 'Todo')
        self.assertEqual(sum(c['args'][:2] == ['pr', 'close'] for c in self.writes()), 1)

    def test_interrupted_reopen_card_move_is_retried_without_reopening_twice(self):
        self.assertEqual(self.run_park('--apply').returncode, 0)
        data = self.data()
        data['pulls'][0]['state'] = 'MERGED'
        self.update(pulls=data['pulls'], fail_move=True)
        self.assertEqual(self.run_park('--apply').returncode, 2)
        result = self.run_park('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.data()['tasks'][-1]['section'], 'Checks')
        self.assertEqual(sum(c['args'][:2] == ['pr', 'reopen'] for c in self.writes()), 1)

    def test_read_failure_fails_open_with_one_warning_and_no_writes(self):
        self.update(read_error=True)
        result = self.run_park('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count('warning:'), 1, result.stderr)
        self.assertIn('no changes', result.stderr)
        self.assertEqual(self.writes(), [])
        self.assertFalse(list(self.home.glob('.local/state/board-drain/parked-*.json')))

    def test_drain_read_failure_warns_once_and_does_not_fail(self):
        self.seed(4)
        self.update(read_error=True)
        code, text = self.run_check()
        self.assertEqual(code, 0, text)
        self.assertEqual(text.count('warning:'), 1, text)
        self.assertIn('agent PR cap: read failed', text)

    def test_repo_cap_is_warning_only_and_uses_shared_count_cache(self):
        self.seed(4)
        self.update(count=11)
        code, text = self.run_check()
        self.assertEqual(code, 0, text)
        self.assertIn('warning: repo PR cap: valentinyeo/vstack has 11 open PRs (cap 10)', text)
        self.assertEqual(self.run_check()[0], 0)
        self.assertEqual(sum('search/issues' in c['args'] for c in self.calls()), 1)
        self.assertEqual(self.writes(), [])

    def test_repo_count_read_failure_warns_once_and_allows(self):
        self.seed(5)
        with patch.object(drain.repo_cap, 'one_call', return_value=subprocess.CompletedProcess([], 1, '', 'offline')):
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(drain.repo_cap_notes({REPO}, argparse.Namespace(fixture=None), {}, NOW), [])
                self.assertEqual(drain.repo_cap_notes({REPO}, argparse.Namespace(fixture=None), {}, NOW), [])
        self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_missing_own_login_never_uses_inherited_person_token(self):
        with patch.dict(os.environ, {'SHIP_SESSION_NAME': 'Other Chat'}):
            result = self.run_park('--apply')
        self.assertEqual(result.returncode, 0)
        self.assertIn('own', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_relabelled_card_is_not_touched(self):
        self.assertEqual(self.run_park('--apply').returncode, 0)
        writes = self.writes()
        data = self.data()
        data['tasks'][-1]['labels'] = [{'name': 'Other Chat'}]
        data['pulls'][0]['state'] = 'MERGED'
        self.update(**data)
        self.assertEqual(self.run_park('--apply').returncode, 0)
        self.assertEqual(self.writes(), writes)


if __name__ == '__main__':
    unittest.main()
