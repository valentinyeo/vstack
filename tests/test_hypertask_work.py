import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


r = load('fleet_reconcile', ROOT / 'skills/hypertask-work/reconcile')
lease = load('fleet_lease', ROOT / 'skills/hypertask-work/lease')
NOW = 1800000000
HEAD = 'a' * 40
POLICY = {'authors': {'writer': 'openai'}, 'verifiers': {'verifier': {
    'family': 'anthropic', 'workflow': '.github/workflows/pstack-verifier.yml'}}}


def task(column='Doing'):
    return {'ticketNumber': 'SOFT-1', 'section': column, 'projectId': 2060,
            'updatedAt': NOW - 8000, 'assignees': [{'displayName': 'Runner 9'}]}


def pull(state='OPEN', checks='green', passed=False):
    return r.Pull('https://github.com/valentinyeo/another-repo/pull/1', state, checks, passed)


def comment(status='PASS', head=HEAD, when='2026-01-01', number=1):
    verdict = {'status': status, 'head_sha': head,
               'run_url': 'https://github.com/valentinyeo/another-repo/actions/runs/9'}
    return {'user': {'login': 'verifier'}, 'body': '```verify-verdict\n' + json.dumps(verdict) + '\n```',
            'updated_at': when, 'id': number}


class ReconcileTest(unittest.TestCase):
    def test_parked_and_unknown_columns_never_move(self):
        for column in ('Not now', 'Some future column', ''):
            for age in (0, 8000):
                for alive in (False, True):
                    with self.subTest(column=column, age=age, alive=alive):
                        result, reason = r.target(r.Facts(column, age, alive, (pull(checks='red'),)))
                        self.assertEqual(result, column)
                        self.assertIn(reason, ('protected column', 'unknown column; kept'))

    def test_live_prose_mentions_do_not_own_tickets(self):
        cases = [('pecunia-52.json', 'SOFT-1915', 'SOFT-1910'),
                 ('android-370.json', 'SOFT-1974', 'SOFT-2369')]
        for fixture, mentioned, owner in cases:
            pr = json.loads((ROOT / 'tests/fixtures/reconcile' / fixture).read_text())
            with self.subTest(fixture=fixture):
                self.assertFalse(r.names_ticket(pr, mentioned))
                if owner == 'SOFT-1910':
                    self.assertTrue(r.names_ticket(pr, owner))
        self.assertEqual(r.target(r.Facts('Todo', 8000))[0], 'Todo')
        self.assertEqual(r.target(r.Facts('AI Review', 8000, False, (pull('MERGED'),)))[0], 'AI Review')

    def test_structural_ownership(self):
        for pr in ({'title': 'Fix SOFT-1'}, {'headRefName': 'fix/soft-1-reconcile'},
                   {'body': 'Ticket: SOFT-1'}, {'body': '**Ticket:** [SOFT-1](https://app.hypertask.ai/detail/project-2060/1)'},
                   {'body': 'See https://app.hypertask.ai/detail/project-2060/1'}):
            with self.subTest(pr=pr):
                self.assertTrue(r.names_ticket(pr, 'SOFT-1'))
        for pr in ({'body': 'Since SOFT-1 this works'}, {'body': 'Not Ticket: SOFT-1'},
                   {'body': 'Ticket: SOFT-10'}, {'body': 'https://evil.test/project-2060/1'},
                   {'body': 'https://app.hypertask.ai/detail/project-2060/10'},
                   {'body': 'https://app.hypertask.ai/detail/project-2061/1'},
                   {'body': 'https://app.hypertask.ai/detail/project-2060/1-extra'},
                   {'title': 'SOFT-10', 'headRefName': 'fix/soft-10'}):
            with self.subTest(pr=pr):
                self.assertFalse(r.names_ticket(pr, 'SOFT-1'))

    def test_bad_keys_do_not_crash_matching_or_search(self):
        self.assertFalse(r.names_ticket({'body': 'unrelated'}, 'BROKEN'))
        with patch.object(r, 'run') as run:
            self.assertEqual(r.discover(['BROKEN']), {'BROKEN': []})
            run.assert_not_called()

    def test_merged_pass_waits_for_live_proof(self):
        self.assertEqual(r.target(r.Facts('Doing', 8000, False, (pull('MERGED', passed=True),))),
                         ('AI Review', 'merged PR with PASS; live proof pending'))

    def seven_plans(self):
        # Todo-bound moves listed first on purpose: order must come from the sort.
        back = [(dict(task(), ticketNumber=f'SOFT-{i}'), r.Facts('Doing', 8000)) for i in (1, 2)]
        live = [(dict(task('Todo'), ticketNumber=f'SOFT-{i}'), r.Facts('Todo', 8000, True)) for i in (13, 11, 12)]
        pr = [(dict(task('Todo'), ticketNumber=f'SOFT-{i}'), r.Facts('Todo', 8000, False, (pull(checks='red'),))) for i in (21, 20)]
        return back + live + pr

    def fake_board(self, moved, tasks):
        def api(*args):
            if args[:2] == ('task', 'get'):
                return {'tasks': [tasks[args[2]]]}
            moved.append(args[2])
            return {}
        return api

    def test_over_limit_applies_first_n_in_order_and_defers_rest(self):
        plans = self.seven_plans()
        tasks = {t['ticketNumber']: t for t, _ in plans}
        facts = {t['ticketNumber']: f for t, f in plans}
        moved = []
        pulls = {key: [] for key in tasks}
        with patch.object(r, 'api', self.fake_board(moved, tasks)), patch.object(r, 'run'), \
                patch.object(r, 'collect', side_effect=lambda t, *a, **k: facts[t['ticketNumber']]), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.apply_plan(plans, 5, pulls), 0)
        self.assertEqual(moved, ['SOFT-11', 'SOFT-12', 'SOFT-13', 'SOFT-20', 'SOFT-21'])
        deferred = [l for l in out.getvalue().splitlines() if l.startswith('DEFERRED')]
        self.assertEqual([l.split()[1] for l in deferred], ['SOFT-1', 'SOFT-2'])
        self.assertNotIn('REFUSE', out.getvalue())
        # Second run: the five moved tickets now sit in their target column.
        rest = [(t, f) for t, f in plans if t['ticketNumber'] in ('SOFT-1', 'SOFT-2')]
        moved.clear()
        with patch.object(r, 'api', self.fake_board(moved, tasks)), patch.object(r, 'run'), \
                patch.object(r, 'collect', side_effect=lambda t, *a, **k: facts[t['ticketNumber']]), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.apply_plan(rest, 5, pulls), 0)
        self.assertEqual(moved, ['SOFT-1', 'SOFT-2'])
        self.assertNotIn('DEFERRED', out.getvalue())

    def test_unknown_applies_nothing(self):
        plans = self.seven_plans()
        calls = []
        with patch.object(r, 'api', side_effect=lambda *a: calls.append(a)), patch.object(r, 'run', side_effect=lambda *a: calls.append(a)), \
                patch.object(r, 'tickets', return_value=[t for t, _ in plans] + [dict(task(), ticketNumber='BROKEN')]), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'discover', return_value={t['ticketNumber']: [] for t, _ in plans}), \
                patch.object(r, 'apply_plan') as apply_plan, \
                patch.object(r, 'live_lease', return_value=False), \
                patch.object(r.sys, 'argv', ['reconcile', '--apply']), \
                patch.dict(os.environ, {'SHIP_SESSION_NAME': 'Poteto', 'HOME': tempfile.mkdtemp()}), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), True)
        self.assertIn('UNKNOWN BROKEN', out.getvalue())
        apply_plan.assert_not_called()
        self.assertEqual(calls, [])

    def test_apply_rechecks_changed_ticket_before_writes(self):
        plans = [(task(), r.Facts('Doing', 8000))]
        with patch.object(r, 'api', return_value={'tasks': [task('Not now')]}), \
                patch.object(r, 'collect') as collect, patch.object(r, 'reconcile') as reconcile, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r.apply_plan(plans, 5, {'SOFT-1': []}), 0)
            collect.assert_not_called()
            reconcile.assert_not_called()

    def test_apply_writes_only_the_preflighted_move(self):
        plans = [(task(), r.Facts('Doing', 8000))]
        with patch.object(r, 'api', return_value={'tasks': [task()]}) as api, \
                patch.object(r, 'discover', return_value={'SOFT-1': []}), \
                patch.object(r, 'collect', return_value=r.Facts('Doing', 8000)), \
                patch.object(r, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r.apply_plan(plans, 5, {'SOFT-1': []}), 0)
            self.assertEqual(api.call_args_list[-1].args, ('task', 'move', 'SOFT-1', '--section', 'Todo'))
            self.assertEqual(run.call_count, 1)

    def test_parked_during_preflight_never_moves(self):
        plans = [(task(), r.Facts('Doing', 8000))]
        with patch.object(r, 'api', side_effect=[{'tasks': [task()]}, {'tasks': [task('Not now')]}]), \
                patch.object(r, 'discover', return_value={'SOFT-1': []}), \
                patch.object(r, 'collect', return_value=r.Facts('Doing', 8000)), \
                patch.object(r, 'reconcile') as reconcile, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r.apply_plan(plans, 5, {'SOFT-1': []}), 0)
            reconcile.assert_not_called()

    def test_malformed_ticket_does_not_abort_remaining_board(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile']), \
                patch.object(r, 'tickets', return_value=[dict(task(), ticketNumber='BROKEN'), task()]), \
                patch.object(r.time, 'time', return_value=NOW), \
                patch.object(r, 'discover', return_value={'BROKEN': [], 'SOFT-1': []}), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'live_lease', return_value=False), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 1)
            self.assertIn('UNKNOWN BROKEN | invalid board-2060 ticket key', out.getvalue())
            self.assertIn('PLAN SOFT-1 Doing -> Todo', out.getvalue())

    def test_fresh_managed_ticket_still_reads_prs_and_lease(self):
        fresh = {**task(), 'updatedAt': NOW}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile']), \
                patch.object(r.time, 'time', return_value=NOW), \
                patch.object(r, 'tickets', return_value=[fresh]), \
                patch.object(r, 'discover', return_value={'SOFT-1': []}), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'collect', return_value=r.Facts('Doing', 0, alive=True)) as collect, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 0)
            collect.assert_called_once()
            self.assertIn('KEEP SOFT-1 Doing -> Doing | live lease', out.getvalue())

    def test_overlap_is_a_clean_skip(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile']), \
                patch.object(r.fcntl, 'flock', side_effect=BlockingIOError()), \
                patch.object(r, 'tickets') as tickets, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 0)
            self.assertIn('SKIP', out.getvalue())
            tickets.assert_not_called()

    def test_idle_doing_returns_todo(self):
        self.assertEqual(r.target(r.Facts('Doing', 7201)), ('Todo', 'no live lease and no PR'))

    def test_table(self):
        cases = [
            (r.Facts('Todo', 8000, True), 'Doing'),
            (r.Facts('Doing', 8000, True), 'Doing'),
            (r.Facts('Doing', 8000, True, (pull(checks='red'),)), 'Checks'),
            (r.Facts('Doing', 8000, True, (pull(),)), 'AI Review'),
            (r.Facts('Doing', 8000, False, (pull(checks='running'),)), 'Checks'),
            (r.Facts('Doing', 8000, False, (pull(checks='red'),)), 'Checks'),
            (r.Facts('Doing', 8000, False, (pull(checks='missing'),)), 'Checks'),
            (r.Facts('Doing', 8000, False, (pull(),)), 'AI Review'),
            (r.Facts('Checks', 8000, False, (pull(passed=True),)), 'AI Review'),
            (r.Facts('Doing', 8000, False, (pull('MERGED', passed=True),)), 'AI Review'),
            (r.Facts('Doing', 8000, False, (pull('MERGED'),)), 'AI Review'),
            (r.Facts('Doing', 8000, False, (pull('MERGED', passed=True), pull(checks='red'))), 'Checks'),
            (r.Facts('Doing', 7199), 'Doing'),
            (r.Facts('Doing', 7200), 'Todo'),
            (r.Facts('Valentin Review', 8000, True), 'Valentin Review'),
            (r.Facts('Done', 8000, True), 'Done'),
        ]
        for facts, expected in cases:
            with self.subTest(facts=facts):
                self.assertEqual(r.target(facts)[0], expected)

    def test_pr_stage_wins_over_grace_and_live_worker(self):
        self.assertEqual(r.target(r.Facts('Doing', 100, True, (pull(),)))[0], 'AI Review')
        self.assertEqual(r.target(r.Facts('Doing', 100, True, (pull(checks='red'),)))[0], 'Checks')
        self.assertEqual(r.target(r.Facts('Doing', 7199, False, (pull('MERGED', passed=True),)))[0], 'AI Review')

    def test_waiting_or_blocked_ticket_stays_put(self):
        for facts in (r.Facts('Doing', 8000, True, waiting=True),
                      r.Facts('Doing', 8000, True, blocked=True)):
            with self.subTest(facts=facts):
                self.assertEqual(r.target(facts), ('Doing', 'waiting or blocked; kept'))

    def test_renamed_columns_resolve_one_family_at_a_time(self):
        self.assertEqual(r.target(r.Facts('Building', 8000, True))[0], 'Building')
        self.assertEqual(r.target(r.Facts('Building', 8000, False, (pull(),)))[0], 'AI Review')
        self.assertEqual(r.target(r.Facts('Verifier', 8000, False, (pull(checks='red'),)))[0], 'Checks')
        self.assertEqual(r.target(r.Facts('Verifier', 8000, True))[0], 'Doing')
        names = r.stage_names(sections={'Todo', 'Building', 'Verifier'})
        self.assertEqual(r.target(r.Facts('Todo', 8000, True), names=names)[0], 'Building')
        half = r.stage_names(sections={'Todo', 'Doing', 'Checks', 'Verifier'})
        self.assertEqual(r.target(r.Facts('Todo', 8000, True), names=half)[0], 'Doing')
        self.assertEqual(r.target(r.Facts('Checks', 8000, False, (pull(),)), names=half)[0], 'Verifier')

    def test_empty_renamed_board_column_is_read_not_inferred(self):
        with patch.object(r, 'api', return_value={'sections': [
                {'section_title': 'Todo'}, {'section_title': 'Building'}]}):
            self.assertEqual(r.read_sections(), {'Todo', 'Building'})
            self.assertEqual(r.target(r.Facts('Todo', 8000, True), names=r.stage_names(
                sections=r.read_sections()))[0], 'Building')

    def test_section_read_failure_falls_back_to_ticket_sections(self):
        with patch.object(r, 'api', side_effect=RuntimeError('down')):
            self.assertEqual(r.read_sections(), set())

    def test_no_writes_by_default_then_one_move_and_log(self):
        t = task()
        facts = r.Facts('Doing', 8000)
        with patch.object(r, 'api') as api, patch.object(r, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r.reconcile(t, facts), 'Todo')
            api.assert_not_called()
            run.assert_not_called()
            r.reconcile(t, facts, apply=True)
            api.assert_called_once_with('task', 'move', 'SOFT-1', '--section', 'Todo')
            self.assertEqual(run.call_count, 1)
            self.assertIn('no live lease and no PR', run.call_args.args[-1])
            self.assertEqual(t['assignees'], [{'displayName': 'Runner 9'}])
            api.reset_mock()
            run.reset_mock()
            r.reconcile(task('Todo'), r.Facts('Todo', 8000), apply=True)
            api.assert_not_called()
            run.assert_not_called()

    def test_other_board_refused(self):
        with self.assertRaisesRegex(ValueError, 'outside board'):
            r.reconcile({**task(), 'projectId': 15}, r.Facts('Doing', 8000), True)

    def test_check_rollup(self):
        self.assertEqual(r.check_state([]), 'missing')
        self.assertEqual(r.check_state([{'status': 'IN_PROGRESS', 'conclusion': ''}]), 'running')
        self.assertEqual(r.check_state([{'status': 'COMPLETED', 'conclusion': 'FAILURE'}]), 'red')
        self.assertEqual(r.check_state([{'status': 'COMPLETED', 'conclusion': 'CANCELLED'}]), 'red')
        self.assertEqual(r.check_state([{'status': 'COMPLETED', 'conclusion': 'SUCCESS'}, {'state': 'SUCCESS'}]), 'green')
        self.assertEqual(r.check_state([{'state': 'PENDING'}]), 'running')

    def test_boundary_and_link_ticket_names(self):
        self.assertTrue(r.names_ticket({'title': 'fix SOFT-1', 'body': ''}, 'SOFT-1'))
        self.assertTrue(r.names_ticket({'body': 'https://app.hypertask.ai/detail/project-2060/1'}, 'SOFT-1'))
        self.assertFalse(r.names_ticket({'title': 'SOFT-10 SOFT-1-extra xSOFT-1'}, 'SOFT-1'))
        self.assertFalse(r.names_ticket({'body': 'project-2060/10'}, 'SOFT-1'))

    def test_discovery_other_repository_and_closed_pr(self):
        p = {'title': 'SOFT-1 fix', 'body': '', 'url': pull().url, 'state': 'OPEN',
             'repository': {'nameWithOwner': 'valentinyeo/another-repo'}, 'number': 1}
        result = {'data': {'q0': {'pageInfo': {'hasNextPage': False}, 'nodes': [p, {**p, 'state': 'CLOSED'}, {**p, 'title': 'SOFT-10 fix'}]}}}
        with patch.object(r, 'run', return_value=json.dumps(result)) as run, patch.object(r, 'branch_pulls', return_value=[]):
            self.assertEqual(r.discover(['SOFT-1']), {'SOFT-1': [p]})
            self.assertIn('user:hypertask-ai', run.call_args.args[-1])
        result['data']['q0']['pageInfo']['hasNextPage'] = True
        with patch.object(r, 'run', return_value=json.dumps(result)), self.assertRaisesRegex(ValueError, 'truncated'):
            r.discover(['SOFT-1'])

    def test_branch_only_pr_is_discovered(self):
        pr = {'url': pull().url, 'state': 'OPEN', 'headRefName': 'feature/soft-1-work',
              'number': 1, 'repository': {'nameWithOwner': 'valentinyeo/another-repo'}}
        result = {'data': {'q0': {'pageInfo': {'hasNextPage': False}, 'nodes': []}}}
        with patch.object(r, 'run', return_value=json.dumps(result)), patch.object(r, 'branch_pulls', return_value=[pr]):
            self.assertEqual(r.discover(['SOFT-1']), {'SOFT-1': [pr]})

    def test_branch_search_splits_over_limit_and_paginates(self):
        pr = {'url': pull().url, 'state': 'OPEN', 'headRefName': 'fix/soft-1',
              'number': 1, 'repository': {'nameWithOwner': 'valentinyeo/another-repo'}}
        def page(count, nodes=(), more=False, cursor=None):
            return json.dumps({'data': {'search': {'issueCount': count, 'nodes': list(nodes),
                'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}}})
        responses = [page(1001), page(101, [pr], True, 'next'), page(101), page(0)]
        with patch.object(r, 'run', side_effect=responses) as run:
            self.assertEqual(list(r.branch_pulls()), [pr])
            self.assertIn('after:"next"', run.call_args_list[2].args[-1])
            self.assertEqual(run.call_count, 4)

    def test_unknown_column_bypasses_discovery_and_lease(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile']), \
                patch.object(r, 'tickets', return_value=[task('Future')]), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'discover', return_value={}) as discover, \
                patch.object(r, 'collect') as collect, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 0)
            discover.assert_called_once_with([])
            collect.assert_not_called()
            self.assertIn('KEEP SOFT-1 Future -> Future | unknown column; kept', out.getvalue())

    def test_board_paginates_server_clamped_pages(self):
        with patch.object(r, 'api', side_effect=[{'tasks': [task()], 'total': 2, 'nextCursor': 'next'},
                                               {'tasks': [{**task(), 'ticketNumber': 'SOFT-2'}], 'total': 2, 'nextCursor': None}]) as api:
            self.assertEqual(len(r.tickets()), 2)
            self.assertIn('--cursor', api.call_args.args)
        with patch.object(r, 'api', return_value={'tasks': [task()], 'total': 2}), self.assertRaisesRegex(ValueError, 'incomplete'):
            r.tickets()

    def test_current_head_cross_family_actions_verdict(self):
        workflow = {'head_sha': HEAD, 'status': 'completed', 'conclusion': 'success',
                    'path': '.github/workflows/pstack-verifier.yml'}
        jobs = [{'jobs': [{'runner_name': 'GitHub Actions 7', 'labels': ['ubuntu-latest']}]}]
        with patch.object(r, 'run', side_effect=[json.dumps(workflow), json.dumps(jobs)]):
            self.assertTrue(r.pass_on_head([comment()], HEAD, 'writer', 'valentinyeo/another-repo', POLICY))
        for comments, policy in [([comment(head='b' * 40)], POLICY),
                                 ([comment(), comment('FAIL', when='2026-02-01', number=2)], POLICY),
                                 ([comment()], {}),
                                 ([comment()], {**POLICY, 'authors': {'writer': 'anthropic'}}),
                                 ([{'user': {'login': 'verifier'}, 'body': 'PASS ' + HEAD}], POLICY)]:
            with self.subTest(comments=comments, policy=policy), patch.object(r, 'run') as run:
                self.assertFalse(r.pass_on_head(comments, HEAD, 'writer', 'valentinyeo/another-repo', policy))
                run.assert_not_called()
        for bad in [{**workflow, 'head_sha': 'b' * 40}, {**workflow, 'path': '.github/workflows/verify-gate.yml'}]:
            with patch.object(r, 'run', return_value=json.dumps(bad)):
                self.assertFalse(r.pass_on_head([comment()], HEAD, 'writer', 'valentinyeo/another-repo', POLICY))
        jobs[0]['jobs'][0]['labels'] = ['self-hosted']
        with patch.object(r, 'run', side_effect=[json.dumps(workflow), json.dumps(jobs)]):
            self.assertFalse(r.pass_on_head([comment()], HEAD, 'writer', 'valentinyeo/another-repo', POLICY))


class Board15Test(unittest.TestCase):
    def target(self, column, age=8000, alive=False, pulls=()):
        return r.target(r.Facts(column, age, alive, pulls), board=r.BOARDS[15])[0]

    def test_service_path_finds_agent_cli_before_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            executable = home / '.local/bin/hypertask'
            executable.parent.mkdir(parents=True)
            executable.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
assert os.environ['HT_TOKEN'] == 'service-agent-token'
args = sys.argv[1:]
if args == ['--json', 'context']:
    print(json.dumps({'connected_agent': {'id': 'agent', 'displayName': 'HT Product Lead'}}))
elif args[:3] == ['--json', 'task', 'list']:
    print(json.dumps({'tasks': [], 'total': 0}))
else:
    raise SystemExit('unexpected command: ' + repr(args))
''')
            executable.chmod(0o755)
            result = subprocess.run([sys.executable, str(ROOT / 'skills/hypertask-work/reconcile'), '--board', '15', '--apply'],
                                    env={'HOME': directory, 'PATH': '/usr/bin:/bin', 'HT_TOKEN': 'service-agent-token'},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PREVIEW board=15 tickets=0 unknown=0', result.stdout)

    def test_live_worker_moves_to_in_progress(self):
        self.assertEqual(self.target('Backlog', alive=True), 'In Progress')
        self.assertEqual(self.target('AI Review', alive=True, pulls=(pull(),)), 'In Progress')

    def test_open_pr_moves_to_ai_review(self):
        for checks in ('green', 'red', 'running', 'missing'):
            with self.subTest(checks=checks):
                self.assertEqual(self.target('In Progress', pulls=(pull(checks=checks),)), 'AI Review')
                self.assertEqual(self.target('Backlog', pulls=(pull(checks=checks),)), 'AI Review')

    def test_never_returns_to_backlog(self):
        for column in ('In Progress', 'AI Review'):
            for pulls in ((), (pull('MERGED'),), (pull('CLOSED'),)):
                with self.subTest(column=column, pulls=pulls):
                    self.assertEqual(self.target(column, pulls=pulls), column)

    def test_protected_columns_never_move(self):
        for column in ('UX needed', 'UX Sign-off', 'Agent Blocked (Infra)', 'Valentin Review',
                       'QA', 'Flag: Only Me + QA', 'Flag: Everyone', 'Flag: Off', 'No Flag',
                       'Flag: Future', 'Future column'):
            with self.subTest(column=column):
                self.assertEqual(self.target(column, alive=True, pulls=(pull(checks='red'),)), column)

    def test_two_hour_grace(self):
        self.assertEqual(self.target('Backlog', age=7199, alive=True), 'Backlog')
        self.assertEqual(self.target('Backlog', age=7200, alive=True), 'In Progress')

    def test_five_move_cap(self):
        plans = [({'ticketNumber': f'HTPR-{i}', 'section': 'Backlog', 'projectId': 15, 'updatedAt': 1},
                  r.Facts('Backlog', 8000, True)) for i in range(1, 7)]
        moved = []

        def api(*args):
            if args[:2] == ('task', 'get'):
                return {'tasks': [{'ticketNumber': args[2], 'section': 'Backlog', 'projectId': 15, 'updatedAt': 1}]}
            moved.append(args[2])
            return {}
        with patch.object(r, 'api', api), patch.object(r, 'run'), patch.object(r, 'require_board15_agent'), \
                patch.object(r, 'collect', return_value=r.Facts('Backlog', 8000, True)), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.apply_plan(plans, 99, {f'HTPR-{i}': [] for i in range(1, 7)}, board=r.BOARDS[15]), 0)
        self.assertEqual(moved, [f'HTPR-{i}' for i in range(1, 6)])
        self.assertIn('DEFERRED HTPR-6', out.getvalue())
        self.assertIn('limit=5', out.getvalue())

    def test_board15_accepts_only_its_ticket_keys_and_urls(self):
        board = r.BOARDS[15]
        self.assertEqual(r.ticket_index('HTPR-19', board=board), '19')
        self.assertTrue(r.names_ticket({'body': 'https://app.hypertask.ai/detail/project-15/19'}, 'HTPR-19', board=board))
        self.assertFalse(r.names_ticket({'body': 'https://app.hypertask.ai/detail/project-2060/19'}, 'HTPR-19', board=board))
        with self.assertRaises(ValueError):
            r.ticket_index('SOFT-19', board=board)

    def test_board15_prs_only_come_from_hypertask_repository(self):
        pr = {'title': 'HTPR-1 fix', 'url': 'https://github.com/hypertask-ai/hypertask/pull/1',
              'state': 'OPEN', 'repository': {'nameWithOwner': 'hypertask-ai/hypertask'}, 'number': 1}
        wrong = {**pr, 'repository': {'nameWithOwner': 'valentinyeo/another-repo'}}
        data = {'data': {'q0': {'pageInfo': {'hasNextPage': False}, 'nodes': [pr, wrong]}}}
        with patch.object(r, 'run', return_value=json.dumps(data)) as run, patch.object(r, 'branch_pulls', return_value=[]):
            self.assertEqual(r.discover(['HTPR-1'], board=r.BOARDS[15]), {'HTPR-1': [pr]})
            self.assertIn('repo:hypertask-ai/hypertask', run.call_args.args[-1])

    def test_closed_pr_during_preflight_never_moves(self):
        t = {'ticketNumber': 'HTPR-1', 'section': 'In Progress', 'projectId': 15,
             'updatedAt': NOW - 8000}
        pr = {'url': 'https://github.com/hypertask-ai/hypertask/pull/1', 'state': 'OPEN',
              'number': 1, 'repository': {'nameWithOwner': 'hypertask-ai/hypertask'}}
        plans = [(t, r.Facts('In Progress', 8000, False, (pull(),)))]
        with patch.object(r, 'api', return_value={'tasks': [t]}), \
                patch.object(r, 'live_product_worker', return_value=False), \
                patch.object(r, 'run', return_value=json.dumps({'url': pr['url'], 'state': 'CLOSED'})) as run, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.apply_plan(plans, 5, {'HTPR-1': [pr]}, board=r.BOARDS[15]), 0)
            self.assertIn('facts changed since preview', out.getvalue())
            self.assertEqual(run.call_args.args[:3], ('gh', 'pr', 'view'))

    def test_board15_requires_explicit_agent_token(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(r, 'api') as api:
            with self.assertRaises(ValueError):
                r.require_board15_agent()
            api.assert_not_called()

    def test_board15_refuses_personal_token_and_wrong_agent(self):
        for identity in (None, {'displayName': 'Valentin Yeo'}, {'id': 'runner', 'displayName': 'Other Runner'}):
            with self.subTest(identity=identity), patch.dict(os.environ, {'HT_TOKEN': 'token'}), \
                    patch.object(r, 'api', return_value={'connected_agent': identity}):
                with self.assertRaises(ValueError):
                    r.require_board15_agent()

    def test_board15_accepts_vcc_and_product_lead_agent(self):
        for name in ('Valentins Claude Code', 'HT Product Lead'):
            with self.subTest(name=name), patch.dict(os.environ, {'HT_TOKEN': 'token'}), \
                    patch.object(r, 'api', return_value={'connected_agent': {'id': 'agent', 'displayName': name}}):
                r.require_board15_agent()


class ProductWorkerTest(unittest.TestCase):
    def setUp(self):
        r.product_workers.cache_clear()

    def test_queue_requires_active_service_and_recent_ticket_work(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'hypertask-test'
            state.mkdir()
            with contextlib.closing(sqlite3.connect(state / 'queue.sqlite3')) as db, db:
                db.execute('CREATE TABLE deliveries (project_id INTEGER,ticket TEXT,state TEXT,event TEXT,progress_at REAL,started_at REAL)')
                for key, board, status, age, event in (
                    ('HTPR-1', 15, 'running', 1, 'task.assigned'),
                    ('HTPR-2', 15, 'running', 901, 'task.assigned'),
                    ('HTPR-3', 2060, 'running', 1, 'task.assigned'),
                    ('HTPR-4', 15, 'pending', 1, 'task.assigned'),
                    ('HTPR-5', 15, 'running', 1, 'chat.message'),
                    ('HTPR-6', 15, 'claiming', 1, 'comment.mention'),
                    ('HTPR-7', 15, 'launching', 1, 'scope.discovery')):
                    db.execute('INSERT INTO deliveries VALUES (?,?,?,?,?,?)', (board,key,status,event,NOW-age,NOW-age))
            listed = 'hypertask-agent-worker@test.service loaded active running test worker'
            shown = 'MainPID=1234\nActiveState=active\n'
            with patch.object(r, 'run', side_effect=[listed, shown]), \
                    patch.object(r, 'pid_alive', return_value=True), \
                    patch.object(r, 'worker_state_directory', return_value=state):
                self.assertEqual(r.product_workers(NOW), {'HTPR-1', 'HTPR-6', 'HTPR-7'})
            with patch.object(r, 'run', side_effect=[listed, shown]), \
                    patch.object(r, 'pid_alive', return_value=False):
                self.assertEqual(r.product_workers(NOW + 1), set())

    def test_active_worker_missing_queue_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r, 'run', side_effect=['hypertask-agent-worker@test.service loaded active running test', 'MainPID=1234\nActiveState=active']), \
                patch.object(r, 'pid_alive', return_value=True), \
                patch.object(r, 'worker_state_directory', return_value=Path(directory)):
            with self.assertRaises((ValueError, sqlite3.Error)):
                r.product_workers(NOW)

    def test_service_read_failure_fails_closed(self):
        with patch.object(r, 'run', side_effect=RuntimeError('systemctl failed')):
            with self.assertRaises(RuntimeError):
                r.product_workers(NOW)


class LeaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.path = self.directory / 'SOFT-1.json'

    def seed(self, **overrides):
        value = dict(pid=os.getpid(), host=socket.gethostname(), started=NOW - 100, last_beat=NOW)
        self.path.write_text(json.dumps({**value, **overrides}))

    def test_live_stale_crashed_and_foreign(self):
        self.assertFalse(r.live_lease('SOFT-1', NOW, self.directory))
        self.seed()
        self.assertTrue(r.live_lease('SOFT-1', NOW, self.directory))
        self.seed(last_beat=NOW - 900)
        self.assertFalse(r.live_lease('SOFT-1', NOW, self.directory))
        self.seed(pid=999999999)
        self.assertFalse(r.live_lease('SOFT-1', NOW, self.directory))
        self.seed(host='other-host')
        with self.assertRaisesRegex(ValueError, 'another host'):
            r.live_lease('SOFT-1', NOW, self.directory)
        self.seed(host='other-host', last_beat=NOW - 900)
        self.assertFalse(r.live_lease('SOFT-1', NOW, self.directory))
        self.seed(last_beat=NOW + 1)
        self.assertFalse(r.live_lease('SOFT-1', NOW, self.directory))

    def test_running_process_with_lease_reads_live(self):
        worker = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            lease.write('SOFT-1', 'start', worker.pid, self.directory, NOW)
            self.assertTrue(r.live_lease('SOFT-1', NOW, self.directory))
        finally:
            worker.terminate()
            worker.wait(timeout=10)

    def test_dead_pid_with_lease_reads_not_live(self):
        worker = subprocess.Popen([sys.executable, '-c', 'pass'])
        worker.wait(timeout=10)
        self.seed(pid=worker.pid)
        self.assertFalse(r.live_lease('SOFT-1', NOW, self.directory))

    def test_start_beat_end_atomic_and_idempotent(self):
        pid = os.getpid()
        lease.write('SOFT-1', 'start', pid, self.directory, NOW)
        lease.write('SOFT-1', 'start', pid, self.directory, NOW + 1)
        lease.write('SOFT-1', 'beat', pid, self.directory, NOW + 2)
        record = json.loads(self.path.read_text())
        self.assertEqual(record['started'], NOW)
        self.assertEqual(record['last_beat'], NOW + 2)
        lease.write('SOFT-1', 'end', pid + 1, self.directory, NOW + 3)
        self.assertTrue(self.path.exists())
        lease.write('SOFT-1', 'end', pid, self.directory, NOW + 3)
        lease.write('SOFT-1', 'end', pid, self.directory, NOW + 3)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.directory.glob('SOFT-1.*')), [self.directory / 'SOFT-1.lock'])

    def test_other_worker_cannot_overwrite_live_lease(self):
        self.seed(host='other-host')
        with self.assertRaisesRegex(ValueError, 'another live worker'):
            lease.write('SOFT-1', 'start', os.getpid(), self.directory, NOW)
        self.assertEqual(json.loads(self.path.read_text())['host'], 'other-host')
        self.seed(pid=999999999)
        lease.write('SOFT-1', 'start', os.getpid(), self.directory, NOW)
        self.assertEqual(json.loads(self.path.read_text())['pid'], os.getpid())

    def test_wrapper_fast_command_and_exit_status(self):
        env = {**os.environ, 'FLEET_LEASE_DIR': str(self.directory)}
        for code in (0, 7):
            result = subprocess.run([str(ROOT / 'skills/hypertask-work/lease'), 'SOFT-1', 'run', '--', sys.executable, '-c', f'raise SystemExit({code})'], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertFalse(self.path.exists())

    def test_child_exits_between_spawn_and_first_lease(self):
        child = Mock(pid=999999999, returncode=0)
        child.poll.return_value = 0
        with patch.object(sys, 'argv', ['lease', 'SOFT-1', 'run', '--', 'true']), \
                patch.object(lease.subprocess, 'Popen', return_value=child), \
                patch.object(lease, 'write', side_effect=[ValueError('worker PID does not exist'), None]):
            self.assertEqual(lease.main(), 0)
        child.terminate.assert_not_called()

    def test_child_exits_between_poll_and_beat(self):
        child = Mock(pid=999999999, returncode=0)
        child.poll.side_effect = [None, 0]
        with patch.object(sys, 'argv', ['lease', 'SOFT-1', 'run', '--', 'true']), \
                patch.object(lease.subprocess, 'Popen', return_value=child), \
                patch.object(lease, 'write', side_effect=[None, ValueError('worker PID does not exist'), None]):
            self.assertEqual(lease.main(), 0)
        child.terminate.assert_not_called()

    def test_wrapper_registers_running_child(self):
        env = {**os.environ, 'FLEET_LEASE_DIR': str(self.directory)}
        code = "import json,os,pathlib; p=pathlib.Path(os.environ['FLEET_LEASE_DIR'])/'SOFT-1.json'; import time; time.sleep(.2); d=json.loads(p.read_text()); assert d['pid']==os.getpid()"
        result = subprocess.run([str(ROOT / 'skills/hypertask-work/lease'), 'SOFT-1', 'run', '--', sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
