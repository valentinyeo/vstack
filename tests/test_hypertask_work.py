import base64
import contextlib
import fcntl
import re
from datetime import date, datetime, timedelta, timezone
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
import re
import tempfile
import threading
import time
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


# Tests never touch the real ~/.cache: every cached answer has its own file here.
TEST_CACHE = Path(tempfile.mkdtemp(prefix='reconcile-cache-')) / 'cache.json'
os.environ['RECONCILE_CACHE'] = str(TEST_CACHE)

r = load('fleet_reconcile', ROOT / 'skills/hypertask-work/reconcile')
lease = load('fleet_lease', ROOT / 'skills/hypertask-work/lease')
NOW = 1800000000
HEAD = 'a' * 40


def clear_cache():
    TEST_CACHE.unlink(missing_ok=True)


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
    def setUp(self):
        clear_cache()
        r.PULLS.clear()
        r.FAILED.clear()
        r.FAILED_REPOS.clear()
        r.reset_github_count()
        self.addCleanup(r.PULLS.clear)
        for patcher in (
                patch.object(r, 'process_tickets', return_value=set()),
                patch.object(r, 'product_workers', return_value=set())):
            patcher.start()
            self.addCleanup(patcher.stop)

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
                   {'body': 'Ticket: https://app.hypertask.ai/detail/project-2060/1'}):
            with self.subTest(pr=pr):
                self.assertTrue(r.names_ticket(pr, 'SOFT-1'))
        for pr in ({'body': 'Since SOFT-1 this works'}, {'body': 'Not Ticket: SOFT-1'},
                   {'body': 'Ticket: SOFT-10'}, {'body': 'https://evil.test/project-2060/1'},
                   {'body': 'https://app.hypertask.ai/detail/project-2060/10'},
                   {'body': 'https://app.hypertask.ai/detail/project-2061/1'},
                   {'body': 'https://app.hypertask.ai/detail/project-2060/1-extra'},
                   {'body': 'See https://app.hypertask.ai/detail/project-2060/1'},
                   {'title': 'SOFT-10', 'headRefName': 'fix/soft-10'}):
            with self.subTest(pr=pr):
                self.assertFalse(r.names_ticket(pr, 'SOFT-1'))

    def test_body_url_only_counts_on_the_ticket_line(self):
        board = r.BoardConfig(13556, 'VSTA', frozenset(), frozenset(), (), 'valentinyeo/vstack')
        pull = json.loads((ROOT / 'tests/fixtures/reconcile' / 'vstack-200.json').read_text())
        with self.subTest('a prose url in the real PR is not evidence'):
            self.assertFalse(r.names_ticket(pull, 'VSTA-53', board=board))
        with self.subTest('the same PR owns the ticket on its own ticket line'):
            self.assertTrue(r.names_ticket(pull, 'VSTA-42', board=board))
        with self.subTest('a ticket line url for the mentioned ticket is evidence'):
            self.assertTrue(r.names_ticket(
                {'body': 'Ticket: https://app.hypertask.ai/detail/project-13556/53'}, 'VSTA-53', board=board))
        with self.subTest('title and branch still name the ticket'):
            for pr in ({'title': 'VSTA-53: fix'}, {'title': '- VSTA-53 fix'},
                       {'headRefName': 'vsta-53-fix'}, {'headRefName': 'fix/vsta-53'}):
                self.assertTrue(r.names_ticket(pr, 'VSTA-53', board=board))

    def test_closing_keywords_on_their_own_line_name_tickets(self):
        pr = json.loads((ROOT / 'tests/fixtures/reconcile' / 'multiprompt-1140.json').read_text())
        with self.subTest('multiprompt PR 1140 links both closed tickets'):
            self.assertTrue(r.names_ticket(pr, 'SOFT-2946'))
            self.assertTrue(r.names_ticket(pr, 'SOFT-2929'))
        with self.subTest('several keys on one closes line'):
            body = 'Closes SOFT-1, SOFT-2 and SOFT-3'
            for key in ('SOFT-1', 'SOFT-2', 'SOFT-3'):
                self.assertTrue(r.names_ticket({'body': body}, key))
        for pr in ({'body': '**Closes** SOFT-1'}, {'body': '- Fixes SOFT-1'},
                   {'body': 'resolved SOFT-1'}, {'body': 'Ticket: SOFT-10\nCloses SOFT-1'}):
            with self.subTest(pr=pr):
                self.assertTrue(r.names_ticket(pr, 'SOFT-1'))
        for pr in ({'body': 'This closes SOFT-1 in prose'},
                   {'body': 'See SOFT-1 in the changelog\nCloses SOFT-10'}):
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
        self.assertEqual([c for c in calls if c[1:2] != ('api',)], [])

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
            self.assertIn('KEEP SOFT-1 Doing -> Doing | live worker: lease or process', out.getvalue())

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
        self.assertEqual(r.target(r.Facts('Doing', 7201)), ('Todo', 'no live worker and no PR'))

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

    def test_labelled_verification_ticket_moves_to_its_backlog(self):
        for age in (60, 7199, 8000):
            with self.subTest(age=age):
                self.assertEqual(r.target(r.Facts('Todo', age, verification=True)),
                                 ('Verification Backlog', 'verification ticket'))

    def test_verification_backlog_without_the_label_returns_todo(self):
        for age in (60, 7199, 8000):
            with self.subTest(age=age):
                self.assertEqual(r.target(r.Facts('Verification Backlog', age)),
                                 ('Todo', 'not a verification ticket'))

    def test_labelled_verification_follows_normal_rules_once_work_starts(self):
        cases = [
            (r.Facts('Doing', 8000, True, verification=True), 'Doing'),
            (r.Facts('Todo', 8000, False, (pull(checks='red'),), verification=True), 'Checks'),
            (r.Facts('Todo', 8000, True, verification=True), 'Doing'),
            (r.Facts('Verification Backlog', 8000, False, (pull(),), verification=True), 'AI Review'),
            (r.Facts('Verification Backlog', 8000, False, (pull('MERGED', passed=True),), verification=True), 'AI Review'),
            (r.Facts('Verification Backlog', 8000, True, verification=True), 'Doing'),
            (r.Facts('Todo', 8000, verification=True, waiting=True), 'Todo'),
            (r.Facts('Verification Backlog', 8000, verification=True), 'Verification Backlog'),
            (r.Facts('Valentin Review', 8000, verification=True), 'Valentin Review'),
        ]
        for facts, expected in cases:
            with self.subTest(facts=facts):
                self.assertEqual(r.target(facts)[0], expected)

    def test_verification_label_is_read_from_the_ticket(self):
        labelled = {**task('Todo'), 'labels': [{'id': '1', 'name': 'verification'}]}
        miscased = {**task('Todo'), 'labels': [{'id': '1', 'name': 'Verification'}]}
        plain = {**task('Todo'), 'labels': [{'id': '2', 'name': 'Bug'}], 'labelCount': 1}
        with patch.object(r, 'worker_alive', return_value=False):
            self.assertTrue(r.collect(labelled, [], NOW).verification)
            self.assertTrue(r.collect(miscased, [], NOW).verification)
            self.assertFalse(r.collect(plain, [], NOW).verification)
            self.assertFalse(r.collect(task('Todo'), [], NOW).verification)

    def test_board_without_the_column_keeps_verification_tickets_put(self):
        self.assertNotIn('Verification Backlog', r.BOARDS[15].managed)
        self.assertEqual(r.target(r.Facts('Backlog', 8000, verification=True), board=r.BOARDS[15])[0],
                         'Backlog')
        self.assertIn('Verification Backlog', r.BOARDS[2060].managed)

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
            self.assertIn('no live worker and no PR', run.call_args.args[-1])
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
        self.assertTrue(r.names_ticket({'body': 'Ticket: https://app.hypertask.ai/detail/project-2060/1'}, 'SOFT-1'))
        self.assertFalse(r.names_ticket({'body': 'https://app.hypertask.ai/detail/project-2060/1'}, 'SOFT-1'))
        self.assertFalse(r.names_ticket({'title': 'SOFT-10 SOFT-1-extra xSOFT-1'}, 'SOFT-1'))
        self.assertFalse(r.names_ticket({'body': 'project-2060/10'}, 'SOFT-1'))

    def test_discovery_other_repository_and_closed_pr(self):
        p = {'title': 'SOFT-1 fix', 'body': '', 'url': pull().url, 'state': 'OPEN',
             'repository': {'nameWithOwner': 'valentinyeo/another-repo'}, 'number': 1}
        result = {'data': {'q0': {'pageInfo': {'hasNextPage': False}, 'nodes': [p, {**p, 'state': 'CLOSED'}, {**p, 'title': 'SOFT-10 fix'}]}}}
        with patch.object(r, 'run', return_value=json.dumps(result)) as run, patch.object(r, 'branch_pulls', return_value=[]), patch.object(r, 'head_pulls', return_value=[]):
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
            self.assertEqual(r.scan_window(r.DEFAULT, 'is:open', 'created', date(2026, 1, 1), date(2026, 1, 8)), [pr])
            self.assertIn('after:"next"', run.call_args_list[2].args[-1])
            self.assertEqual(run.call_count, 4)

    def merged_pr(self, number, merged='2026-11-17T10:00:00Z'):
        return {'url': f'https://github.com/valentinyeo/another-repo/pull/{number}', 'state': 'MERGED',
                'headRefName': f'soft-{number}-work', 'number': number, 'mergedAt': merged,
                'repository': {'nameWithOwner': 'valentinyeo/another-repo'}}

    def scan(self, merged=(), today=date(2026, 11, 18), since=date(2026, 11, 16), opened=()):
        queries = []

        def search(*args):
            query = next(a for a in args if 'search(query' in a)
            queries.append(query)
            nodes = list(opened) if 'is:open' in query else list(merged)
            return json.dumps({'data': {'search': {'issueCount': len(nodes), 'nodes': nodes,
                                                    'pageInfo': {'hasNextPage': False, 'endCursor': None}}}})
        with patch.object(r, 'run', side_effect=search), patch.object(r, 'today', return_value=today):
            return r.branch_pulls(r.DEFAULT, since), queries

    def test_branch_scan_is_one_open_search_and_one_merged_search(self):
        found, queries = self.scan(since=date(2026, 10, 20))
        self.assertEqual(found, [])
        self.assertEqual(len(queries), 2)
        self.assertEqual(sum('is:open' in q for q in queries), 1)
        self.assertEqual(sum('merged:2026-10-20..2026-11-18' in q.replace('\\', '') for q in queries), 1)

    def test_merged_prs_are_cached_between_runs(self):
        pr = self.merged_pr(5)
        found, first = self.scan(merged=[pr])
        self.assertEqual([p['url'] for p in found], [pr['url']])
        self.assertEqual(len(first), 2)
        found, second = self.scan(today=date(2026, 11, 18))
        self.assertEqual([p['url'] for p in found], [pr['url']])
        self.assertEqual(len(second), 2)
        merged_queries = [q for q in second if 'is:merged' in q]
        self.assertEqual(len(merged_queries), 1)
        self.assertIn('merged:2026-11-17..2026-11-18', merged_queries[0].replace('\\', ''))

    def test_cache_reaches_back_only_when_an_older_ticket_needs_it(self):
        self.scan(since=date(2026, 11, 10))
        found, queries = self.scan(since=date(2026, 11, 5), today=date(2026, 11, 19))
        merged = sorted(q.split('merged:')[1].split(',')[0].split(')')[0].replace('\\', '').strip('"')
                        for q in queries if 'is:merged' in q)
        self.assertEqual(merged, ['2026-11-05..2026-11-10', '2026-11-17..2026-11-19'])

    def test_cache_forgets_prs_that_left_the_window(self):
        old = self.merged_pr(1, '2026-09-01T00:00:00Z')
        self.scan(merged=[old], since=date(2026, 8, 1), today=date(2026, 11, 18))
        found, _ = self.scan(since=date(2026, 10, 25), today=date(2026, 11, 18))
        self.assertEqual(found, [])

    def test_unreadable_cache_means_one_full_search(self):
        self.scan()
        TEST_CACHE.write_text('{not json')
        _, queries = self.scan(since=date(2026, 11, 1))
        self.assertEqual(len(queries), 2)
        self.assertIn('merged:2026-11-01..2026-11-18', [q for q in queries if 'is:merged' in q][0].replace('\\', ''))

    def test_failed_search_keeps_the_cache(self):
        self.scan(merged=[self.merged_pr(5)])
        before = TEST_CACHE.read_text()
        with patch.object(r, 'run', side_effect=RuntimeError('rate limited')), \
                patch.object(r, 'today', return_value=date(2026, 11, 19)), self.assertRaises(RuntimeError):
            r.branch_pulls(r.DEFAULT, date(2026, 11, 16))
        self.assertEqual(TEST_CACHE.read_text(), before)

    def test_github_reads_run_one_after_another(self):
        active, most, threads = [0], [0], set()
        guard = threading.Lock()

        def search(*args):
            with guard:
                active[0] += 1
                most[0] = max(most[0], active[0])
                threads.add(threading.get_ident())
            time.sleep(0.01)
            with guard:
                active[0] -= 1
            fields = [m for m in re.findall(r'q\d+:search', next(a for a in args if 'search(query' in a))]
            data = {f'q{n}': {'pageInfo': {'hasNextPage': False}, 'nodes': []} for n in range(len(fields))}
            return json.dumps({'data': data})
        keys = [f'SOFT-{n}' for n in range(1, 60)]
        with patch.object(r, 'run', side_effect=search), patch.object(r, 'branch_pulls', return_value=[]), \
                patch.object(r, 'head_pulls', return_value=[]):
            r.discover(keys)
        self.assertEqual(most[0], 1)
        self.assertEqual(threads, {threading.get_ident()})

    def test_scan_window_starts_at_oldest_ticket_or_thirty_days(self):
        today = date(2026, 11, 18)
        since, old = r.scan_plan({'SOFT-1': '2026-05-01T00:00:00Z', 'SOFT-2': '2026-11-10T00:00:00Z',
                                  'SOFT-3': None}, today=today)
        self.assertEqual(since, date(2026, 10, 19))
        self.assertEqual(old, ['SOFT-1', 'SOFT-3'])
        since, old = r.scan_plan({'SOFT-2': '2026-11-10T08:00:00Z'}, today=today)
        self.assertEqual((since, old), (date(2026, 11, 10), []))

    def test_unparsable_created_at_keeps_full_history_for_that_ticket(self):
        today = date(2026, 11, 18)
        since, old = r.scan_plan({'SOFT-1': 'not a date', 'SOFT-2': '2026-11-10T00:00:00Z',
                                  'SOFT-3': '2026-10-02T09:00:00', 'SOFT-4': 0}, today=today)
        self.assertEqual(since, date(2026, 10, 19))
        self.assertEqual(sorted(old), ['SOFT-1', 'SOFT-3', 'SOFT-4'])

    def test_bad_created_at_costs_only_its_own_ticket(self):
        broken = {**task(), 'ticketNumber': 'SOFT-2', 'createdAt': 'yesterday'}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile']), \
                patch.object(r.time, 'time', return_value=NOW), \
                patch.object(r, 'tickets', return_value=[broken, task()]), \
                patch.object(r, 'discover', return_value={'SOFT-2': [], 'SOFT-1': []}) as discover, \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'live_lease', return_value=False), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 0)
            discover.assert_called_once_with(['SOFT-2', 'SOFT-1'], created={'SOFT-2': None, 'SOFT-1': None})
            self.assertIn("NOTE SOFT-2 | unparsable createdAt 'yesterday'", out.getvalue())
            self.assertIn('PLAN SOFT-1 Doing -> Todo', out.getvalue())

    def test_ticket_with_pr_merged_long_ago_still_owned(self):
        merged = {'url': 'https://github.com/valentinyeo/another-repo/pull/7', 'state': 'MERGED',
                  'title': 'SOFT-1 old fix', 'body': '', 'headRefName': 'feat/old', 'number': 7,
                  'repository': {'nameWithOwner': 'valentinyeo/another-repo'}}
        prefixed = {'url': 'https://github.com/valentinyeo/another-repo/pull/8', 'state': 'MERGED',
                    'headRefName': 'soft-1-branch-only', 'number': 8,
                    'repository': {'nameWithOwner': 'valentinyeo/another-repo'}}
        def search(*args):
            query = next(a for a in args if 'search(query' in a)
            nodes = [prefixed] if 'head:SOFT-1' in query else [merged]
            return json.dumps({'data': {'q0': {'pageInfo': {'hasNextPage': False}, 'nodes': nodes}}})
        with patch.object(r, 'run', side_effect=search), patch.object(r, 'branch_pulls', return_value=[]):
            found = r.discover(['SOFT-1'], created={'SOFT-1': '2026-05-01T00:00:00Z'})
        self.assertEqual({p['url'] for p in found['SOFT-1']}, {merged['url'], prefixed['url']})

    def test_failed_pr_read_in_prefetch_leaves_the_error_to_its_ticket(self):
        pulls = {'SOFT-1': [{'repository': {'nameWithOwner': 'valentinyeo/another-repo'}, 'number': 1, 'state': 'MERGED'}]}
        with patch.object(r, 'read_pull_batch', side_effect=RuntimeError('boom')) as read:
            r.prefetch(pulls)
        read.assert_called_once_with([('valentinyeo/another-repo', 1)])

    def test_unknown_column_bypasses_discovery_and_lease(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile']), \
                patch.object(r, 'tickets', return_value=[task('Future')]), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'discover', return_value={}) as discover, \
                patch.object(r, 'collect') as collect, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 0)
            discover.assert_called_once_with([], created={})
            collect.assert_not_called()
            self.assertIn('KEEP SOFT-1 Future -> Future | unknown column; kept', out.getvalue())

    def test_board_paginates_server_clamped_pages(self):
        with patch.object(r, 'api', side_effect=[{'tasks': [task()], 'total': 2, 'nextCursor': 'next'},
                                               {'tasks': [{**task(), 'ticketNumber': 'SOFT-2'}], 'total': 2, 'nextCursor': None}]) as api:
            self.assertEqual(len(r.tickets()), 2)
            self.assertIn('--cursor', api.call_args.args)
        with patch.object(r, 'api', return_value={'tasks': [task()], 'total': 2}), self.assertRaisesRegex(ValueError, 'incomplete'):
            r.tickets()

    def test_open_pr_read_is_one_call_without_comments_or_policy(self):
        node = {'url': 'https://github.com/valentinyeo/another-repo/pull/1', 'state': 'OPEN',
                'headRefOid': HEAD, 'baseRefOid': 'c' * 40, 'author': {'login': 'writer'},
                'statusCheckRollup': {'contexts': {'pageInfo': {'hasNextPage': False}, 'nodes': [
                    {'__typename': 'CheckRun', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}]}},
                'comments': {'totalCount': 0, 'nodes': []}}
        with patch.object(r, 'run', return_value=json.dumps({'data': {'p0': {'pullRequest': node}}})) as run, \
                patch.object(r, 'verifier_policy', return_value=POLICY):
            got = r.read_pull('valentinyeo/another-repo', 1)
        run.assert_called_once()
        self.assertNotIn('comments?per_page', run.call_args.args[-1])
        self.assertEqual((got.state, got.checks, got.passed), ('OPEN', 'green', False))

    def test_github_calls_are_counted_by_kind(self):
        ok = subprocess.CompletedProcess([], 0, '{}', '')
        with patch.object(r.subprocess, 'run', return_value=ok):
            r.run('gh', 'api', 'graphql', '-f', 'query=x')
            r.run('gh', 'pr', 'view', '1')
            r.run('gh', 'api', '--paginate', 'repos/a/b/issues/1/comments')
            r.run('hypertask', '--json', 'task', 'list')
        self.assertEqual(r.github_calls(), (2, 1))
        self.assertEqual(r.github_summary(), 'reconcile: github calls=3 (graphql=2, rest=1)')

    def test_every_run_prints_its_github_call_count(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile']), \
                patch.object(r.time, 'time', return_value=NOW), \
                patch.object(r, 'tickets', return_value=[task()]), \
                patch.object(r, 'discover', side_effect=lambda *a, **k: (r.run('gh', 'api', 'graphql') and {})
                              or {'SOFT-1': []}), \
                patch.object(r.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{}', '')), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'live_lease', return_value=False), \
                patch.object(r, 'process_tickets', return_value=set()), \
                contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r.main(), 0)
        self.assertIn('reconcile: github calls=1 (graphql=1, rest=0)', err.getvalue())

    def labelled_board(self):
        return [{**task('Doing'), 'ticketNumber': 'SOFT-1', 'labels': [{'id': '1', 'name': 'SOFT-2807'}]},
                {**task('Doing'), 'ticketNumber': 'SOFT-2', 'labels': [{'id': '2', 'name': 'Bug'}]},
                {**task('Doing'), 'ticketNumber': 'SOFT-3', 'labels': [{'id': '3', 'name': 'soft-2807'}]},
                {**task('Doing'), 'ticketNumber': 'SOFT-4'}]

    def test_label_filters_before_any_github_lookup(self):
        tasks = self.labelled_board()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile', '--label', 'Soft-2807']), \
                patch.object(r.time, 'time', return_value=NOW), \
                patch.object(r, 'tickets', return_value=tasks), \
                patch.object(r, 'discover', return_value={t['ticketNumber']: [] for t in tasks}) as discover, \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'live_lease', return_value=False), \
                patch.object(r, 'process_tickets', return_value=set()), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 0)
        self.assertEqual(discover.call_args.args[0], ['SOFT-1', 'SOFT-3'])
        printed = out.getvalue()
        for kept in ('SOFT-1', 'SOFT-3'):
            self.assertIn(f'PLAN {kept}', printed)
        for skipped in ('SOFT-2', 'SOFT-4'):
            self.assertNotIn(skipped, printed)

    def test_labelled_apply_moves_only_labelled_tickets(self):
        tasks = {t['ticketNumber']: t for t in self.labelled_board()}
        moved = []

        def api(*args):
            return {'tasks': [tasks[args[2]]]} if args[:2] == ('task', 'get') else moved.append(args[2]) or {}

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile', '--apply', '--label', 'SOFT-2807']), \
                patch.object(r.time, 'time', return_value=NOW), \
                patch.object(r, 'tickets', return_value=list(tasks.values())), \
                patch.object(r, 'discover', return_value={key: [] for key in tasks}), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'live_lease', return_value=False), \
                patch.object(r, 'process_tickets', return_value=set()), \
                patch.object(r, 'api', api), patch.object(r, 'run', return_value=''), \
                patch.dict(os.environ, {'SHIP_SESSION_NAME': 'Poteto'}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r.main(), 0)
        self.assertEqual(moved, ['SOFT-1', 'SOFT-3'])

    def fixture_github(self, tasks):
        """A fixture board's GitHub: one open PR per ticket, no other searches."""
        pulls = {t['ticketNumber']: {'title': f'{t["ticketNumber"]} work', 'body': '',
                                     'headRefName': f'{t["ticketNumber"].lower()}-work', 'state': 'OPEN',
                                     'number': r.ticket_index(t['ticketNumber']),
                                     'url': 'https://github.com/valentinyeo/another-repo/pull/1',
                                     'repository': {'nameWithOwner': 'valentinyeo/another-repo'}}
                 for t in tasks}

        def respond(args, **kwargs):
            call = ' '.join(args)
            if 'is:open' in call or 'is:merged' in call:
                page = {'issueCount': 0, 'nodes': [], 'pageInfo': {'hasNextPage': False, 'endCursor': None}}
                body = {'data': {'search': page}}
            elif 'repository(owner:' in call:
                keys = list(dict.fromkeys(re.findall(r'p(\d+):repository', call)))
                body = {'data': {f'p{n}': {'pullRequest': {
                    'url': 'https://github.com/valentinyeo/another-repo/pull/1', 'state': 'OPEN',
                    'headRefOid': HEAD, 'baseRefOid': 'c' * 40, 'author': {'login': 'writer'},
                    'statusCheckRollup': {'contexts': {'pageInfo': {'hasNextPage': False}, 'nodes': [
                        {'__typename': 'CheckRun', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}]}},
                    'comments': {'totalCount': 0, 'nodes': []}}} for n in keys}}
            elif '/contents/.verify/policy.json' in call:
                body = {'content': base64.b64encode(b'{}').decode()}
            else:
                keys = list(dict.fromkeys(re.findall(r'SOFT-\d+', call)))
                body = {'data': {f'q{n}': {'pageInfo': {'hasNextPage': False}, 'nodes': [pulls[key]]}
                                 for n, key in enumerate(keys)}}
            return subprocess.CompletedProcess([], 0, json.dumps(body), '')
        return respond

    def github_calls_for(self, tasks, argv, ticket=None):
        clear_cache()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile', *argv]), \
                patch.object(r.time, 'time', return_value=NOW), \
                patch.object(r, 'tickets', return_value=tasks), \
                patch.object(r, 'read_ticket', return_value=ticket), \
                patch.object(r, 'product_workers', return_value=set()), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'live_lease', return_value=False), \
                patch.object(r, 'process_tickets', return_value=set()), \
                patch.object(r.subprocess, 'run', side_effect=self.fixture_github(tasks)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r.main(), 0)
        return sum(r.github_calls())

    def test_a_labelled_run_costs_fewer_github_calls_on_a_fixture_board(self):
        created = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat() + 'T10:00:00Z'
        templates = self.labelled_board() + [dict(task('Doing'), ticketNumber=f'SOFT-{n}')
                                            for n in range(5, 27)]
        tasks = [{**t, 'createdAt': created} if t.get('labels') else
                 {**t, 'createdAt': created, 'labels': [{'id': '9', 'name': 'Bug'}]} for t in templates]
        whole = self.github_calls_for(tasks, [])
        labelled = self.github_calls_for(tasks, ['--label', 'SOFT-2807'])
        self.assertEqual((whole, labelled), (8, 5),
                         'whole board: 3 searches + 2 branch scans + 2 pull batches + 1 policy; '
                         '2 labelled tickets: 1 + 2 + 1 + 1')

    def test_a_label_nobody_carries_costs_no_github_calls(self):
        tasks = [{**t, 'createdAt': '2026-11-18T10:00:00Z'} for t in self.labelled_board()]
        self.assertEqual(self.github_calls_for(tasks, ['--label', 'nobody-uses-this']), 0)

    def ticket_run(self, argv, one, api=None, env=None, home=None):
        """Run one --ticket run against one ticket: (code, stdout, calls)."""
        calls = {'discover': [], 'moves': []}

        def default_api(*args):
            if args[:2] == ('task', 'get'):
                return {'tasks': [one]}
            if args[:2] == ('task', 'move'):
                calls['moves'].append(args[2])
                return {}
            raise AssertionError(f'unexpected hypertask call {args!r}')

        def discover(keys, **kwargs):
            calls['discover'].append(keys)
            return {key: [] for key in keys}

        environment = {'SHIP_SESSION_NAME': 'Poteto', **(env or {})}
        if home is None:
            temp = tempfile.TemporaryDirectory()
            self.addCleanup(temp.cleanup)
            home = Path(temp.name)
        with patch.object(r.Path, 'home', return_value=Path(home)), \
                patch.object(sys, 'argv', ['reconcile', *argv]), \
                patch.object(r.time, 'time', return_value=NOW), \
                patch.object(r, 'discover', side_effect=discover), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'live_lease', return_value=False), \
                patch.object(r, 'product_workers', return_value=set()), \
                patch.object(r, 'process_tickets', return_value=set()), \
                patch.object(r, 'run', return_value=''), \
                patch.dict(os.environ, environment), \
                patch.object(r, 'api', side_effect=api or default_api), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            code = r.main()
        return code, out.getvalue(), calls

    def test_a_ticket_run_moves_its_own_card_and_leaves_the_others_alone(self):
        code, printed, calls = self.ticket_run(['--ticket', 'SOFT-1'], task('Doing'))
        self.assertEqual(code, 0)
        self.assertIn('PLAN SOFT-1 Doing -> Todo | no live worker and no PR', printed)
        self.assertEqual(calls['discover'], [['SOFT-1']], 'one ticket costs one lookup')
        self.assertNotIn('SOFT-2', printed)
        self.assertNotIn('SOFT-3', printed)
        self.assertEqual(calls['moves'], [], 'a plan run moves nothing')

    def test_a_ticket_run_applies_only_its_own_move(self):
        code, printed, calls = self.ticket_run(['--ticket', 'SOFT-1', '--apply', '--limit', '1'],
                                               task('Doing'))
        self.assertEqual(code, 0)
        self.assertIn('MOVE SOFT-1 Doing -> Todo', printed)
        self.assertEqual(calls['moves'], ['SOFT-1'])

    def test_a_ticket_run_reads_its_board_from_the_ticket(self):
        other = {'ticketNumber': 'HTPR-7', 'section': 'In Progress', 'projectId': 15,
                 'updatedAt': NOW - 8000, 'labels': []}
        with patch.object(r, 'board_config', wraps=r.board_config) as config:
            code, printed, calls = self.ticket_run(['--ticket', 'HTPR-7'], other)
        self.assertEqual(code, 0, printed)
        self.assertIn('PLAN HTPR-7 In Progress -> Backlog', printed)
        self.assertIn(15, [call.args[0] for call in config.call_args_list])
        self.assertEqual(calls['discover'], [['HTPR-7']])

    def test_a_ticket_run_refuses_an_unreadable_ticket(self):
        def api(*args):
            raise ValueError('Hypertask request failed')

        code, printed, calls = self.ticket_run(['--ticket', 'SOFT-1'], task(), api=api)
        self.assertEqual(code, 1)
        self.assertIn('UNKNOWN SOFT-1 | Hypertask request failed', printed)
        self.assertEqual(calls['discover'], [], 'nothing is read from GitHub')

    def test_a_ticket_run_refuses_a_key_from_another_board(self):
        crossed = {'ticketNumber': 'SOFT-9', 'section': 'In Progress', 'projectId': 15,
                   'updatedAt': NOW - 8000, 'labels': []}
        code, printed, calls = self.ticket_run(['--ticket', 'SOFT-9'], crossed)
        self.assertEqual(code, 1)
        self.assertIn('UNKNOWN SOFT-9', printed)
        self.assertEqual(calls['discover'], [])

    def test_a_second_run_of_the_same_ticket_is_a_clean_skip(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.object(r.Path, 'home', return_value=Path(temp.name)):
            r.lock_path(r.DEFAULT).parent.mkdir(parents=True, exist_ok=True)
            lock = r.ticket_lock_path(r.DEFAULT, 'SOFT-1').open('a')
            self.addCleanup(lock.close)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIsNone(r.acquire_locks(r.DEFAULT, None, 'SOFT-1'),
                              'the same ticket waits for the running sync')
            self.assertIsNotNone(r.acquire_locks(r.DEFAULT, None, 'SOFT-2'),
                                 'a different ticket still syncs')
            self.assertEqual(r.ticket_lock_path(r.DEFAULT, 'SOFT-1').name,
                             'reconcile-ticket-soft-1.lock')

    def test_an_unreadable_ticket_leaves_a_failure_line_for_the_owner(self):
        def api(*args):
            raise ValueError('Hypertask request failed')

        environment = {'RECONCILE_CARD_PHASE': 'end', 'SHIP_SESSION_NAME': 'Matt Live Stream'}
        home = Path(tempfile.mkdtemp())
        code, printed, _calls = self.ticket_run(['--ticket', 'SOFT-1'], task(), api=api,
                                                env=environment, home=home)
        self.assertEqual(code, 1)
        lines = r.session.read_failures(home)
        self.assertEqual(len(lines), 1, 'the owner sees a card sync that could not read its ticket')
        self.assertEqual(lines[0]['ticket'], 'SOFT-1')
        self.assertEqual(lines[0]['session_name'], 'Matt Live Stream')
        self.assertEqual(lines[0]['summary'], 'Hypertask request failed')
        self.assertFalse(r.session.card_record_path(home, 2060, 'SOFT-1', 'end').exists(),
                         'no record claims a board the run never read')

    def test_a_ticket_run_costs_a_handful_of_github_calls(self):
        created = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat() + 'T10:00:00Z'
        templates = self.labelled_board() + [dict(task('Doing'), ticketNumber=f'SOFT-{n}')
                                            for n in range(5, 27)]
        tasks = [{**t, 'createdAt': created} for t in templates]
        whole = self.github_calls_for(tasks, [])
        clear_cache()
        card = self.github_calls_for(tasks, ['--ticket', 'SOFT-2'], ticket=tasks[1])
        self.assertLessEqual(card, 6, 'a card sync costs a handful of GitHub calls')
        self.assertLess(card, whole)

    def test_reconcile_auto_dry_drops_apply(self):
        code, printed, calls = self.ticket_run(
            ['--ticket', 'SOFT-1', '--apply', '--limit', '1'], task('Doing'),
            env={'RECONCILE_AUTO_DRY': '1'})
        self.assertEqual(code, 0)
        self.assertIn('DRY RUN board=2060 tickets=1 unknown=0', printed)
        self.assertEqual(calls['moves'], [], 'the dry switch moves nothing')

    def test_a_card_sync_writes_its_own_status_record(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.dict(os.environ, {'RECONCILE_CARD_PHASE': 'start'}):
            code, printed, _calls = self.ticket_run(['--ticket', 'SOFT-1'], task('Doing'),
                                                    home=Path(temp.name))
            record = json.loads(r.session.card_record_path(
                Path(temp.name), 2060, 'SOFT-1', 'start').read_text())
            log = r.session.card_log_path(Path(temp.name), 2060, 'SOFT-1', 'start').read_text()
        self.assertEqual(code, 0)
        self.assertEqual((record['board'], record['ticket'], record['phase']),
                         (2060, 'SOFT-1', 'start'))
        self.assertEqual(record['exit'], 0)
        self.assertEqual(record['summary_line'], 'DRY RUN board=2060 tickets=1 unknown=0')
        self.assertIn('PLAN SOFT-1 Doing -> Todo', log)
        self.assertEqual(record['log'], str(r.session.card_log_path(
            Path(temp.name), 2060, 'SOFT-1', 'start')))
        self.assertEqual(record['session_name'], 'Poteto')

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
    CREATED = '2026-11-20T09:51:00Z'

    def target(self, column, age=8000, alive=False, pulls=()):
        return r.target(r.Facts(column, age, alive, pulls), board=r.BOARDS[15])[0]

    def card(self, key, column, updated, pulls=()):
        return {'ticketNumber': key, 'section': column, 'projectId': 15,
                'createdAt': self.CREATED, 'updatedAt': updated,
                'assignees': [], 'labels': [], 'pulls': list(pulls)}

    def product_pull(self, number, state):
        return {'number': number, 'state': state,
                'url': f'https://github.com/hypertask-ai/hypertask/pull/{number}',
                'repository': {'nameWithOwner': 'hypertask-ai/hypertask'}}

    def facts(self, card, now, alive=False):
        """The facts a board-15 read gives, from the pulls its search already returned."""
        with patch.object(r, 'worker_alive', return_value=alive):
            return r.collect(card, card['pulls'], now, board=r.BOARDS[15])

    def board15_tasks(self, count=4, column='Backlog'):
        """Cards created today, so no ticket needs the old-head lookup."""
        created = datetime.now(timezone.utc).isoformat()
        return [{**self.card(f'HTPR-{n}', column, NOW - 8000), 'createdAt': created}
                for n in range(1, count + 1)]

    def fixture_github15(self, tasks):
        """A board-15 fixture's GitHub: one open PR per ticket, nothing else."""
        pulls = {t['ticketNumber']: {'title': f'{t["ticketNumber"]} work', 'body': '',
                                     'headRefName': f'{t["ticketNumber"].lower()}-work',
                                     'state': 'OPEN',
                                     'number': r.ticket_index(t['ticketNumber'], r.BOARDS[15]),
                                     'url': 'https://github.com/hypertask-ai/hypertask/pull/' + str(n),
                                     'repository': {'nameWithOwner': 'hypertask-ai/hypertask'}}
                 for n, t in enumerate(tasks, 1)}

        def respond(args, **kwargs):
            call = ' '.join(args)
            if 'is:open' in call or 'is:merged' in call:
                page = {'issueCount': 0, 'nodes': [], 'pageInfo': {'hasNextPage': False, 'endCursor': None}}
                return subprocess.CompletedProcess([], 0, json.dumps({'data': {'search': page}}), '')
            if args[1:3] == ('pr', 'view'):
                # A per-PR read is what this board must not need on a dry run.
                return subprocess.CompletedProcess([], 0, json.dumps({
                    'url': f'https://github.com/hypertask-ai/hypertask/pull/{args[3]}', 'state': 'OPEN'}), '')
            keys = list(dict.fromkeys(re.findall(r'HTPR-\d+', call)))
            body = {'data': {f'q{n}': {'pageInfo': {'hasNextPage': False}, 'nodes': [pulls[key]]}
                             for n, key in enumerate(keys)}}
            return subprocess.CompletedProcess([], 0, json.dumps(body), '')
        return respond

    def board15_run(self, tasks, workers=None, respond=None):
        """(exit code, stdout, github calls) for one whole board-15 dry run."""
        r.PULLS.clear()
        r.reset_github_count()
        read_workers = workers or (lambda now: set())
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile', '--board', '15']), \
                patch.object(r.time, 'time', return_value=NOW), \
                patch.object(r, 'tickets', return_value=tasks), \
                patch.object(r, 'product_workers', side_effect=read_workers), \
                patch.object(r, 'live_lease', return_value=False), \
                patch.object(r, 'process_tickets', return_value=set()), \
                patch.object(r.subprocess, 'run', side_effect=respond or self.fixture_github15(tasks)), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            code = r.main()
        return code, out.getvalue(), sum(r.github_calls())

    def test_a_missing_bus_gets_defaults_before_worker_facts(self):
        uid = os.getuid()
        seen = {}

        def workers(now):
            seen.update(os.environ)
            return set()

        with patch.dict(os.environ, {}, clear=True):
            code, printed, _calls = self.board15_run(self.board15_tasks(), workers=workers)
            self.assertEqual(seen.get('XDG_RUNTIME_DIR'), f'/run/user/{uid}')
            self.assertEqual(seen.get('DBUS_SESSION_BUS_ADDRESS'), f'unix:path=/run/user/{uid}/bus')
            self.assertEqual(os.environ.get('XDG_RUNTIME_DIR'), f'/run/user/{uid}',
                             'the default is left in place for the child processes')
        self.assertEqual(code, 0, printed)
        self.assertIn('unknown=0', printed)

    def test_unreadable_worker_facts_print_one_line_and_plan_nothing(self):
        def broken(now):
            raise RuntimeError('systemctl --user failed: Failed to connect to bus: No medium found')

        code, printed, _calls = self.board15_run(self.board15_tasks(), workers=broken)
        self.assertEqual(code, 1)
        self.assertEqual(printed.strip().splitlines(), [
            'reconcile: worker facts unreadable: systemctl --user failed: '
            'Failed to connect to bus: No medium found; nothing moved'])
        for line in ('UNKNOWN', 'PLAN', 'KEEP', 'DRY RUN'):
            self.assertNotIn(line, printed)

    def test_a_board_15_fixture_run_costs_no_more_than_its_pulls(self):
        tasks = self.board15_tasks()
        code, printed, calls = self.board15_run(tasks)
        self.assertEqual(code, 0, printed)
        self.assertIn('DRY RUN board=15 tickets=4 unknown=0', printed)
        self.assertIn('PLAN HTPR-1 Backlog -> AI Review | open PR', printed)
        # One search page and the two branch scans. The four open PRs cost nothing
        # more, because the search result already carries their state.
        self.assertLessEqual(calls, len(tasks), f'{len(tasks)} open PRs cost {calls} github calls')

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
        self.assertEqual(self.target('In Progress', alive=True, pulls=(pull(),)), 'AI Review')

    def test_open_pr_moves_to_ai_review(self):
        for checks in ('green', 'red', 'running', 'missing'):
            with self.subTest(checks=checks):
                self.assertEqual(self.target('In Progress', pulls=(pull(checks=checks),)), 'AI Review')
                self.assertEqual(self.target('Backlog', pulls=(pull(checks=checks),)), 'AI Review')

    def test_backlog_stays_and_ai_review_never_demotes(self):
        for pulls in ((), (pull('MERGED'),), (pull('CLOSED'),)):
            with self.subTest(pulls=pulls):
                self.assertEqual(self.target('Backlog', pulls=pulls), 'Backlog')
                self.assertEqual(self.target('AI Review', pulls=pulls), 'AI Review')

    def test_stale_in_progress_cards_move_to_backlog(self):
        now = r.stamp(self.CREATED) + 3 * 3600
        for key in ('HTPR-9514', 'HTPR-9511'):
            with self.subTest(ticket=key):
                idle = self.card(key, 'In Progress', now - 3 * 3600)
                self.assertEqual(r.target(self.facts(idle, now), board=r.BOARDS[15]),
                                 ('Backlog', 'idle In Progress; no live worker or open PR'))
                moved = self.card(key, 'Verification Backlog', now - 60)
                self.assertEqual(r.target(self.facts(moved, now), board=r.BOARDS[15])[0],
                                 'Verification Backlog')

    def test_open_pr_moves_a_card_inside_the_grace(self):
        now = r.stamp(self.CREATED) + 600
        card = self.card('HTPR-9387', 'Backlog', now - 120,
                         (self.product_pull(3646, 'OPEN'), self.product_pull(3594, 'CLOSED')))
        self.assertEqual(r.target(self.facts(card, now), board=r.BOARDS[15]), ('AI Review', 'open PR'))

    def test_open_pr_outranks_a_live_worker(self):
        now = r.stamp(self.CREATED) + 3 * 3600
        card = self.card('HTPR-7742', 'In Progress', now - 3 * 3600, (self.product_pull(3735, 'OPEN'),))
        self.assertEqual(r.target(self.facts(card, now, alive=True), board=r.BOARDS[15]),
                         ('AI Review', 'open PR'))

    def test_lease_or_process_is_a_live_worker(self):
        with patch.object(r, 'live_product_worker', return_value=False), \
                patch.object(r, 'live_lease', return_value=True):
            self.assertTrue(r.worker_alive('HTPR-9514', NOW, r.BOARDS[15]))
        with patch.object(r, 'live_product_worker', return_value=False), \
                patch.object(r, 'live_lease', return_value=False), \
                patch.object(r, 'process_tickets', return_value={'HTPR-9514'}):
            self.assertTrue(r.worker_alive('HTPR-9514', NOW, r.BOARDS[15]))
        now = r.stamp(self.CREATED) + 3 * 3600
        card = self.card('HTPR-9514', 'In Progress', now - 3 * 3600)
        self.assertEqual(r.target(self.facts(card, now, alive=True), board=r.BOARDS[15]),
                         ('In Progress', 'live worker'))
        with patch.object(r, 'live_product_worker', side_effect=ValueError('worker facts unreadable')):
            with self.assertRaises(ValueError):
                r.collect(card, [], NOW, board=r.BOARDS[15])

    def test_protected_columns_never_move(self):
        for column in ('UX needed', 'UX Sign-off', 'Agent Blocked (Infra)', 'Valentin Review',
                       'QA', 'Flag: Only Me + QA', 'Flag: Everyone', 'Flag: Off', 'No Flag',
                       'Flag: Future', 'Future column'):
            with self.subTest(column=column):
                self.assertEqual(self.target(column, alive=True, pulls=(pull(checks='red'),)), column)

    def test_two_hour_grace_only_protects_idle_demotion(self):
        self.assertEqual(self.target('In Progress', age=7199), 'In Progress')
        self.assertEqual(self.target('Backlog', age=7199, alive=True), 'In Progress')
        self.assertEqual(self.target('In Progress', age=7200), 'Backlog')
        self.assertEqual(self.target('In Progress', age=7200, alive=True), 'In Progress')

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
        self.assertTrue(r.names_ticket({'body': 'Ticket: https://app.hypertask.ai/detail/project-15/19'}, 'HTPR-19', board=board))
        self.assertFalse(r.names_ticket({'body': 'https://app.hypertask.ai/detail/project-15/19'}, 'HTPR-19', board=board))
        self.assertFalse(r.names_ticket({'body': 'https://app.hypertask.ai/detail/project-2060/19'}, 'HTPR-19', board=board))
        with self.assertRaises(ValueError):
            r.ticket_index('SOFT-19', board=board)

    def test_board15_prs_only_come_from_hypertask_repository(self):
        pr = {'title': 'HTPR-1 fix', 'url': 'https://github.com/hypertask-ai/hypertask/pull/1',
              'state': 'OPEN', 'repository': {'nameWithOwner': 'hypertask-ai/hypertask'}, 'number': 1}
        wrong = {**pr, 'repository': {'nameWithOwner': 'valentinyeo/another-repo'}}
        data = {'data': {'q0': {'pageInfo': {'hasNextPage': False}, 'nodes': [pr, wrong]}}}
        with patch.object(r, 'run', return_value=json.dumps(data)) as run, patch.object(r, 'branch_pulls', return_value=[]), patch.object(r, 'head_pulls', return_value=[]):
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


class AnyBoardTest(unittest.TestCase):
    """Any board a project names: its own prefix and columns, 2060's safe rules."""

    SECTIONS = ('Backlog', 'Todo', 'Doing', 'Review', 'Done')

    def setUp(self):
        clear_cache()
        r.board_config.cache_clear()
        self.addCleanup(r.board_config.cache_clear)

    def project(self, sections=SECTIONS, prefix='TEST', board_id=9999):
        return {'project': {'id': board_id, 'uniqueIdentifier': prefix,
                            'sections': [{'id': n, 'section_title': name}
                                         for n, name in enumerate(sections)]}}

    def config(self, **project):
        with patch.object(r, 'api', return_value=self.project(**project)):
            r.board_config.cache_clear()
            return r.board_config(9999)

    def test_third_board_parses_and_plans_only_between_its_matching_columns(self):
        tasks = [{'ticketNumber': f'TEST-{n}', 'section': column, 'projectId': 9999,
                  'updatedAt': NOW - 8000}
                 for n, column in enumerate(self.SECTIONS, 1)]
        facts = {'TEST-2': r.Facts('Todo', 8000, True),
                 'TEST-3': r.Facts('Doing', 8000, False, (pull(checks='red'),))}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(r.sys, 'argv', ['reconcile', '--board', '9999']), \
                patch.object(r, 'api', return_value=self.project()), \
                patch.object(r, 'tickets', return_value=tasks), \
                patch.object(r, 'discover', return_value={'TEST-2': [], 'TEST-3': []}), \
                patch.object(r, 'prefetch'), \
                patch.object(r, 'collect', side_effect=lambda t, *a, **k: facts[t['ticketNumber']]), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 0)
            board = r.board_config(9999)
            self.assertEqual(board.prefix, 'TEST')
            self.assertEqual(board.managed, frozenset({'Todo', 'Doing'}))
            self.assertEqual(board.protected, frozenset({'Backlog', 'Review', 'Done'}))
        printed = out.getvalue()
        self.assertIn('PLAN TEST-2 Todo -> Doing | live worker: lease or process', printed)
        self.assertIn('KEEP TEST-1 Backlog -> Backlog | protected column', printed)
        # The board has no AI Review column, so an open PR moves nothing.
        self.assertIn('KEEP TEST-3 Doing -> Doing | target column missing; kept', printed)
        self.assertIn('KEEP TEST-4 Review -> Review | protected column', printed)
        self.assertIn('KEEP TEST-5 Done -> Done | protected column', printed)
        self.assertNotIn('AI Review', printed)
        self.assertIn('DRY RUN board=9999 tickets=5 unknown=0', printed)

    def test_third_board_keeps_a_verification_ticket_while_it_lacks_that_column(self):
        self.assertEqual(r.target(r.Facts('Todo', 8000, verification=True),
                                  board=self.config())[0], 'Todo')
        self.assertEqual(r.target(r.Facts('Todo', 8000, verification=True), board=self.config(
            sections=self.SECTIONS + ('Verification Backlog',)))[0], 'Verification Backlog')

    def test_unknown_board_apply_requires_an_agent_login(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(r.sys, 'argv', ['reconcile', '--board', '9999', '--apply']), \
                patch.object(r, 'api', return_value=self.project()), \
                patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as stop:
                r.main()
        self.assertEqual(stop.exception.code, 2)
        self.assertIn('SHIP_SESSION_NAME', err.getvalue())

    def test_zero_board_is_refused_before_any_read(self):
        with patch.object(r.sys, 'argv', ['reconcile', '--board', '0']), \
                patch.object(r, 'api') as api, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stop:
                r.main()
        self.assertEqual(stop.exception.code, 2)
        api.assert_not_called()

    def test_known_boards_keep_their_own_configs(self):
        self.assertIs(r.board_config(2060), r.BOARDS[2060])
        self.assertIs(r.board_config(15), r.BOARDS[15])
        self.assertEqual(r.board_config(2060).rules, r.RULES)
        self.assertEqual((r.board_config(2060).prefix, r.board_config(2060).managed),
                         ('SOFT', frozenset(r.MANAGED)))
        self.assertEqual((r.board_config(15).prefix, r.board_config(15).rules),
                         ('HTPR', r.PRODUCT_RULES))


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


class ProcessLivenessTest(unittest.TestCase):
    """A worker started without the lease wrapper still holds its ticket."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.proc = Path(self.temp.name)
        self.lease_dir = self.proc / 'leases'
        self.lease_dir.mkdir()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(r, 'PROC', self.proc)
        patcher.start()
        self.addCleanup(patcher.stop)
        lease_patcher = patch.object(r, 'LEASES', self.lease_dir)
        lease_patcher.start()
        self.addCleanup(lease_patcher.stop)
        r.process_tickets.cache_clear()
        self.addCleanup(r.process_tickets.cache_clear)

    def proc_clear(self):
        for entry in self.proc.iterdir():
            for part in entry.iterdir():
                part.unlink()
            entry.rmdir()
        r.process_tickets.cache_clear()

    def spawn(self, pid, argv, ppid=1):
        directory = self.proc / str(pid)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'stat').write_text(f'{pid} (cmd) S {ppid} {ppid} {ppid}\n')
        (directory / 'cmdline').write_bytes(b'\0'.join(os.fsencode(word) for word in argv) + b'\0')

    def write_lease(self, key, pid, now=None):
        now = time.time() if now is None else now
        payload = {'pid': pid, 'host': socket.gethostname(),
                   'started': now, 'last_beat': now}
        (self.lease_dir / f'{key}.json').write_text(json.dumps(payload))

    def test_url_marks_its_ticket_live(self):
        self.spawn(4001, ['hax', '-p', '--model=gpt-6.1-sol',
                          'https://app.hypertask.ai/detail/project-2060/2730'])
        self.assertEqual(r.process_tickets(), {'SOFT-2730'})

    def test_neighbouring_ticket_numbers_stay_apart(self):
        self.spawn(4001, ['hax', '-p', 'https://app.hypertask.ai/detail/project-2060/2730'])
        found = r.process_tickets()
        self.assertIn('SOFT-2730', found)
        self.assertNotIn('SOFT-273', found)
        self.assertNotIn('SOFT-27', found)

    def test_short_ticket_url_does_not_prove_the_longer_ticket(self):
        self.spawn(4002, ['pi', '-p', 'https://app.hypertask.ai/detail/project-2060/27'])
        self.assertEqual(r.process_tickets(), {'SOFT-27'})

    def test_ticket_key_token_marks_the_ticket_live(self):
        self.spawn(4001, ['codex', 'exec', 'SOFT-2730 fix the release gate'])
        self.assertEqual(r.process_tickets(), {'SOFT-2730'})

    def test_partial_key_tokens_do_not_count(self):
        self.spawn(4001, ['cursor-agent', 'fix', 'SOFT-2730b', 'and', 'ASOFT-2730', 'SOFT-2730-extra'])
        self.assertEqual(r.process_tickets(), set())

    def test_other_board_url_does_not_count(self):
        self.spawn(4001, ['claude', '-p', 'https://app.hypertask.ai/detail/project-15/2730'])
        self.assertEqual(r.process_tickets(), set())

    def test_own_process_and_its_parents_are_ignored(self):
        self.spawn(os.getpid(), ['python3', 'reconcile', '--section', 'Doing',
                                 'https://app.hypertask.ai/detail/project-2060/2730'], ppid=4009)
        self.spawn(4009, ['zsh', '-c', 'reconcile SOFT-2730'], ppid=1)
        self.spawn(4001, ['hax', '-p', 'https://app.hypertask.ai/detail/project-2060/2731'])
        self.assertEqual(r.process_tickets(), {'SOFT-2731'})

    def test_grep_and_ps_only_read_the_ticket(self):
        self.spawn(4001, ['bash', '-c', 'grep -rn SOFT-2730 /tmp/ft-runs'])
        self.spawn(4002, ['ps', 'aux', 'SOFT-2730'])
        self.spawn(4003, ['rg', 'https://app.hypertask.ai/detail/project-2060/2730'])
        self.spawn(4004, ['grep', '-r', 'https://app.hypertask.ai/detail/project-2060/2730', '/tmp'])
        self.spawn(4005, ['pgrep', '-af', 'SOFT-2730'])
        self.assertEqual(r.process_tickets(), set())

    def test_lease_wrapper_counts_as_a_worker(self):
        self.spawn(4001, ['/usr/bin/python3', '/home/v/.local/share/vstack/skills/hypertask-work/lease',
                          'SOFT-2730', 'run', '--', 'pi', '-p', 'fix the release gate'])
        self.spawn(4002, ['bash', '-c', 'cd /tmp && pi -p https://app.hypertask.ai/detail/project-2060/2731'])
        self.assertEqual(r.process_tickets(), {'SOFT-2730', 'SOFT-2731'})

    def test_leased_agent_argv_for_another_key_does_not_count(self):
        now = time.time()
        self.write_lease('SOFT-2730', 4001, now)
        self.spawn(4001, ['python3', '/skills/hypertask-work/lease', 'SOFT-2730', 'run', '--',
                          'plan-pick', '--run'], ppid=1)
        self.spawn(4002, ['cursor-agent', '-p', 'SOFT-2731 fix board sync'], ppid=4001)
        with patch.object(r, 'pid_alive', return_value=True):
            self.assertEqual(r.process_tickets(), set())
            self.assertTrue(r.live_lease('SOFT-2730', now, self.lease_dir))
            self.assertFalse(r.worker_alive('SOFT-2731', now))

    def test_unleased_agent_still_counts_from_argv(self):
        self.spawn(4100, ['cursor-agent', '-p', 'SOFT-2732 work'])
        self.assertEqual(r.process_tickets(), {'SOFT-2732'})

    def test_leased_grandchild_agent_is_skipped(self):
        now = time.time()
        self.write_lease('SOFT-2733', 5001, now)
        self.spawn(5001, ['lease', 'SOFT-2733', 'run', '--', 'bash'], ppid=1)
        self.spawn(5002, ['bash', '-c', 'cursor-agent'], ppid=5001)
        self.spawn(5003, ['cursor-agent', '-p', 'SOFT-2734'], ppid=5002)
        with patch.object(r, 'pid_alive', return_value=True):
            self.assertEqual(r.process_tickets(), set())
            self.assertFalse(r.worker_alive('SOFT-2734', now))

    def test_lease_without_a_run_does_not_count(self):
        self.spawn(4001, ['bash', '-c', 'lease SOFT-2730 watch --pid 4001'])
        self.spawn(4002, ['python3', '/x/skills/hypertask-work/lease', 'SOFT-2730', 'beat'])
        self.assertEqual(r.process_tickets(), set())

    def test_commands_that_only_name_a_ticket_are_not_workers(self):
        for argv in (['hypertask', 'task', 'search', 'SOFT-2730'],
                     ['hypertask', '--json', 'task', 'get', 'SOFT-2730'],
                     ['gh', 'search', 'prs', 'SOFT-2730'],
                     ['gh', 'pr', 'list', '--search', 'SOFT-2730'],
                     ['git', 'log', '--grep=SOFT-2730'],
                     ['git', 'checkout', '-b', 'SOFT-2730-fix'],
                     ['python3', '-c', 'print("SOFT-2730")'],
                     ['python3', '-u', '/tmp/watch.py', 'SOFT-2730'],
                     ['node', 'server.js', 'SOFT-2730'],
                     ['vim', 'notes-SOFT-2730.md'],
                     ['tail', '-f', '/tmp/SOFT-2730.log'],
                     ['bash', '/home/v/wt/SOFT-2730/tools/preflight.sh', '/home/v/wt/SOFT-2730'],
                     ['bash', '-c', 'source /tmp/snap.sh && export A=1 && gh search prs SOFT-2730'],
                     ['/usr/bin/python3', '-u', '/home/v/.runtime/x.py', '--agent-host', 'claude', 'SOFT-2730'],
                     ['timeout', '60', 'grep', '-rn', 'SOFT-2730', '/tmp'],
                     ['ssh', 'host', 'hax -p SOFT-2730']):
            with self.subTest(argv=argv):
                self.proc_clear()
                self.spawn(4001, argv)
                self.assertEqual(r.process_tickets(), set())

    def test_agent_clis_count_as_workers_behind_wrappers(self):
        for argv in (['hax', '-p', '--model=gpt-6.1-sol', 'SOFT-2730 fix'],
                     ['/home/v/.local/bin/hax', '-p', 'SOFT-2730'],
                     ['timeout', '7200', '/home/v/.npm-global/bin/pi', '-p', '--model', 'x', 'Ticket SOFT-2730'],
                     ['nohup', 'env', 'A=1', 'codex', 'exec', 'SOFT-2730'],
                     ['/home/v/.local/bin/cursor-agent', '--use-system-ca', '/v/index.js', '-p', 'SOFT-2730'],
                     ['claude', '-p', 'https://app.hypertask.ai/detail/project-2060/2730'],
                     ['node', '/usr/lib/node_modules/pi/bin/pi', '-p', 'SOFT-2730'],
                     ['bash', '-c', 'hax -p SOFT-2730 > /tmp/out'],
                     ['setsid', 'hax', '-p', 'SOFT-2730'],
                     ['env', '-u', 'HOME', 'hax', '-p', 'SOFT-2730'],
                     ['timeout', '-s', 'KILL', '60', 'hax', '-p', 'SOFT-2730'],
                     ['timeout', '3h', 'hax', '-p', 'SOFT-2730']):
            with self.subTest(argv=argv):
                self.proc_clear()
                self.spawn(4001, argv)
                self.assertEqual(r.process_tickets(), {'SOFT-2730'})

    def test_a_search_naming_a_ticket_does_not_move_it_to_doing(self):
        self.spawn(4001, ['hypertask', 'task', 'search', 'SOFT-1'])
        self.spawn(4002, ['gh', 'search', 'prs', 'SOFT-1'])
        with patch.object(r, 'live_lease', return_value=False):
            alive = r.worker_alive('SOFT-1', NOW)
        self.assertFalse(alive)
        self.assertEqual(r.target(r.Facts('Todo', 8000, alive)), ('Todo', 'no live worker and no PR'))

    def test_unreadable_proc_adds_no_liveness(self):
        with patch.object(r, 'PROC', self.proc / 'missing'):
            self.assertEqual(r.process_tickets(r.BOARDS[15]), set())

    def test_process_liveness_only_adds_to_the_lease(self):
        self.spawn(4001, ['hax', '-p', 'SOFT-2730'])
        with patch.object(r, 'live_lease', return_value=False):
            self.assertTrue(r.worker_alive('SOFT-2730', NOW))
            self.assertFalse(r.worker_alive('SOFT-1', NOW))
        with patch.object(r, 'live_lease', return_value=True) as live:
            self.assertTrue(r.worker_alive('SOFT-1', NOW))
            live.assert_called_once()

    def test_live_process_keeps_doing(self):
        self.spawn(4001, ['hax', '-p', 'SOFT-1'])
        with patch.object(r, 'live_lease', return_value=False):
            self.assertEqual(r.target(r.Facts('Doing', 8000, r.worker_alive('SOFT-1', NOW))),
                             ('Doing', 'live worker: lease or process'))


class LeaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.path = self.directory / 'SOFT-1.json'
        self.spawned = []
        for patcher in (
                patch.object(lease.reconcile, 'LEASES', self.directory),
                patch.object(lease.session, 'login_for_session',
                              return_value=self.login()),
                patch.object(lease, 'spawn_card',
                             side_effect=lambda command, env: self.spawned.append(
                                 (command, dict(env))))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def login(self):
        token = self.directory / 'test-chat-agent-token'
        token.write_text('secret\n')
        return ('Test Chat', token)

    @staticmethod
    def write_start_fails_child_gone():
        """Model child dead before the first lease write; end still clears."""
        def fake(key, action, pid, directory=None, now=None):
            if action == 'start':
                raise ValueError('worker PID does not exist')
        return fake

    @staticmethod
    def write_child_gone_before_beat():
        """Start and end succeed; every beat sees a dead worker (race-safe under load)."""
        def fake(key, action, pid, directory=None, now=None):
            if action == 'start':
                return
            if action == 'beat':
                raise ValueError('worker PID does not exist')
            if action == 'end':
                return
            raise AssertionError(f'unexpected lease write {action!r}')
        return fake

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
        env = {**os.environ, 'MULTIPROMPT_TAB': '', 'FLEET_LEASE_DIR': str(self.directory)}
        for code in (0, 7):
            result = subprocess.run([str(ROOT / 'skills/hypertask-work/lease'), 'SOFT-1', 'run', '--', sys.executable, '-c', f'raise SystemExit({code})'], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertFalse(self.path.exists())

    def test_child_exits_between_spawn_and_first_lease(self):
        child = Mock(pid=999999999, returncode=0)
        child.poll.return_value = 0
        with patch.object(sys, 'argv', ['lease', 'SOFT-1', 'run', '--', 'true']), \
                patch.object(lease.subprocess, 'Popen', return_value=child), \
                patch.object(lease, 'sync_card'), \
                patch.object(lease, 'write', side_effect=self.write_start_fails_child_gone()):
            self.assertEqual(lease.main(), 0)
        child.terminate.assert_not_called()

    def test_child_exits_between_poll_and_beat(self):
        child = Mock(pid=999999999, returncode=0)
        child.poll.side_effect = [None, 0]
        with patch.object(sys, 'argv', ['lease', 'SOFT-1', 'run', '--', 'true']), \
                patch.object(lease.subprocess, 'Popen', return_value=child), \
                patch.object(lease, 'sync_card'), \
                patch.object(lease, 'write', side_effect=self.write_child_gone_before_beat()):
            self.assertEqual(lease.main(), 0)
        child.terminate.assert_not_called()

    def lease_main(self, argv):
        """Run one lease action in this process, with its card sync caught, not started."""
        with patch.object(sys, 'argv', ['lease', *argv]):
            return lease.main()

    def test_start_and_end_each_spawn_one_card_sync(self):
        self.spawned = []
        self.assertEqual(self.lease_main(['SOFT-1', 'start', '--pid', str(os.getpid())]), 0)
        self.assertTrue(self.path.is_file(), 'start still writes the lease')
        self.assertEqual(self.lease_main(['SOFT-1', 'end', '--pid', str(os.getpid())]), 0)
        self.assertFalse(self.path.is_file(), 'end still removes the lease')
        self.assertEqual([env['RECONCILE_CARD_PHASE'] for _command, env in self.spawned],
                         ['start', 'end'])
        for command, env in self.spawned:
            self.assertEqual(command[1:], [str(ROOT / 'skills/hypertask-work/reconcile'),
                                           '--ticket', 'SOFT-1', '--apply', '--limit', '1'])
            self.assertEqual(env['HT_TOKEN'], 'secret')
            self.assertEqual(env['SHIP_SESSION_NAME'], 'Test Chat')
            self.assertEqual(env['XDG_RUNTIME_DIR'], f'/run/user/{os.getuid()}')
            self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'],
                             f'unix:path=/run/user/{os.getuid()}/bus')

    def test_run_and_watch_sync_at_their_own_start_and_end(self):
        self.spawned = []
        self.assertEqual(self.lease_main(['SOFT-1', 'run', '--', sys.executable, '-c', 'pass']), 0)
        self.assertEqual([env['RECONCILE_CARD_PHASE'] for _command, env in self.spawned],
                         ['start', 'end'])
        self.spawned = []
        with patch.object(lease.reconcile, 'pid_alive', side_effect=[True, False]):
            self.assertEqual(self.lease_main(['SOFT-1', 'watch', '--pid', '12345']), 0)
        self.assertEqual([env['RECONCILE_CARD_PHASE'] for _command, env in self.spawned],
                         ['start', 'end'])

    def sync_start(self, assignees, take_code=0):
        """Run one start action with the board CLI faked; return its calls."""
        calls = []

        def fake(command, **kwargs):
            calls.append((command, kwargs.get('env', {})))
            if command[1:3] == ['--json', 'task']:
                return subprocess.CompletedProcess(
                    command, 0,
                    json.dumps({'tasks': [{'projectId': 2060, 'assignees': assignees}]}), '')
            return subprocess.CompletedProcess(command, take_code, '', '')

        with patch.object(lease.shutil, 'which', return_value='/bin/hypertask'), \
                patch.object(lease.subprocess, 'run', side_effect=fake), \
                patch.object(sys, 'argv', ['lease', 'SOFT-1', 'start', '--pid', str(os.getpid())]):
            self.assertEqual(lease.main(), 0)
        return calls

    def test_start_sync_takes_the_ticket_when_it_has_no_agent(self):
        for assignees in ([], [{'id': 6, 'agent': None}]):
            with self.subTest(assignees=assignees):
                calls = self.sync_start(assignees)
                take = [command for command, _env in calls
                        if command[1:3] == ['agent', 'take']]
                self.assertEqual(take, [['/bin/hypertask', 'agent', 'take', 'SOFT-1',
                                         '--project', '2060']])
                for _command, env in calls:
                    self.assertEqual(env['SHIP_SESSION_NAME'], 'Test Chat')
                    self.assertEqual(env['HYPERTASKS_JWT_TOKEN'], 'secret')

    def test_start_sync_never_replaces_an_existing_agent(self):
        calls = self.sync_start([{'id': 6, 'agent': {'id': 'agent-1'}}])
        self.assertFalse([command for command, _env in calls
                          if command[1:3] == ['agent', 'take']])

    def test_a_failed_take_never_fails_the_lease(self):
        calls = self.sync_start([], take_code=1)
        self.assertTrue([command for command, _env in calls
                         if command[1:3] == ['agent', 'take']])
        self.assertTrue(self.path.is_file(), 'the lease is still written')

    def test_no_login_spawns_nothing_and_the_lease_still_works(self):
        self.spawned = []
        with patch.object(lease.session, 'login_for_session', return_value=None), \
                patch.object(sys, 'argv', ['lease', 'SOFT-1', 'start', '--pid', str(os.getpid())]):
            self.assertEqual(lease.main(), 0)
        self.assertTrue(self.path.is_file(), 'a missing login never stops the lease')
        self.assertEqual(self.spawned, [])
        with patch.object(lease.session, 'login_for_session', return_value=None):
            self.assertFalse(lease.sync_card('SOFT-1', 'start', {'HOME': str(self.directory)}))

    def test_a_failed_spawn_never_fails_the_lease(self):
        with patch.object(lease, 'spawn_card', side_effect=OSError('no fork')), \
                patch.object(sys, 'argv', ['lease', 'SOFT-1', 'start', '--pid', str(os.getpid())]):
            self.assertEqual(lease.main(), 0)
        self.assertTrue(self.path.is_file())

    def test_a_missing_token_spawns_nothing(self):
        self.spawned = []
        missing = ('Test Chat', self.directory / 'absent-agent-token')
        with patch.object(lease.session, 'login_for_session', return_value=missing):
            self.assertFalse(lease.sync_card('SOFT-1', 'start', {
                'HOME': str(self.directory), 'MULTIPROMPT_TAB': 'live-test'}))
        self.assertEqual(self.spawned, [])

    def test_wrapper_registers_running_child(self):
        env = {**os.environ, 'MULTIPROMPT_TAB': '', 'FLEET_LEASE_DIR': str(self.directory)}
        code = "import json,os,pathlib; p=pathlib.Path(os.environ['FLEET_LEASE_DIR'])/'SOFT-1.json'; import time; time.sleep(.2); d=json.loads(p.read_text()); assert d['pid']==os.getpid()"
        result = subprocess.run([str(ROOT / 'skills/hypertask-work/lease'), 'SOFT-1', 'run', '--', sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.path.exists())


RESET = 1900003600
RESET_TEXT = datetime.fromtimestamp(RESET, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def fake_path(home, gh, hypertask=None, log=None):
    """A HOME whose bin holds the fake tools the run calls first on PATH."""
    bin = Path(home) / '.local/bin'
    bin.mkdir(parents=True)
    if hypertask is not None:
        (bin / 'hypertask').write_text(f'#!{sys.executable}\n' + hypertask)
        (bin / 'hypertask').chmod(0o755)
    if gh is not None:
        (bin / 'gh').write_text(f'#!{sys.executable}\n' + gh)
        (bin / 'gh').chmod(0o755)
    return bin


GH_FAKE = f'''import json, os, sys
remaining = int(os.environ.get('GH_BUDGET', '4000'))
if sys.argv[1:] == ['api', 'rate_limit']:
    print(json.dumps({{'resources': {{'core': {{'remaining': 4000, 'reset': {RESET}}},
                                     'graphql': {{'remaining': remaining, 'reset': {RESET}}}}}}}))
    raise SystemExit(0)
if sys.argv[1:3] == ['api', 'graphql']:
    sys.stderr.write(os.environ.get('GH_FAILURE', 'unexpected gh call'))
    raise SystemExit(1)
raise SystemExit('unexpected gh command: ' + repr(sys.argv[1:]))
'''

HYPER_BOARD_2060 = '''import json, os, sys, pathlib
args = sys.argv[1:]
log = pathlib.Path(os.environ['HYPER_LOG'])
log.write_text(log.read_text() + ' '.join(args) + '\\n')
if args == ['--json', 'project', 'sections', '--project', '2060']:
    print(json.dumps({'sections': [{'section_title': 'Doing'}]}))
elif args[:3] == ['--json', 'task', 'list']:
    print(json.dumps({'tasks': [{'ticketNumber': 'SOFT-1', 'section': 'Doing', 'projectId': 2060,
                                'updatedAt': %d}], 'total': 1}))
else:
    raise SystemExit('unexpected hypertask command: ' + repr(args))
''' % NOW


class RateLimitTest(unittest.TestCase):
    """A spent GitHub budget stops the run at once, cleanly, with no moves."""

    def run_cli(self, gh, env=None):
        home = tempfile.mkdtemp()
        log = Path(home) / 'hypertask.log'
        log.write_text('')
        fake_path(home, gh, HYPER_BOARD_2060)
        environment = {'HOME': home, 'PATH': '/usr/bin:/bin', 'SHIP_SESSION_NAME': 'Poteto',
                       'HYPER_LOG': str(log), **(env or {})}
        result = subprocess.run([sys.executable, str(ROOT / 'skills/hypertask-work/reconcile'), '--apply'],
                                env=environment, capture_output=True, text=True, timeout=60)
        return result, log.read_text()

    def test_only_error_text_counts_as_a_rate_limit(self):
        for text in ('gh: API rate limit exceeded for user ID 1. (HTTP 403)',
                     'You have exceeded a secondary rate limit. (HTTP 429)',
                     '{\"errors\": [{\"type\": \"RATE_LIMITED\"}]}'):
            with self.subTest(text=text):
                self.assertTrue(r.rate_limited(text))
        for text in ('gh: Not Found (HTTP 404)',
                     'gh: Could not resolve to a Repository',
                     '{\"body\": \"we hit a secondary rate limit yesterday\"}'):
            with self.subTest(text=text):
                self.assertFalse(r.RATE_LIMIT_TYPE.search(text))

    def test_a_failed_batch_quoting_a_rate_limit_in_data_is_not_one(self):
        partial = json.dumps({'data': {'p0': {'pullRequest': {'comments': {'nodes': [
            {'body': 'journal: gh api failed: API rate limit exceeded (HTTP 403)'}]}}}}})
        done = subprocess.CompletedProcess(['gh'], 1, stdout=partial,
                                           stderr='gh: Could not resolve to a Repository')
        with patch.object(r.subprocess, 'run', return_value=done):
            with self.assertRaises(RuntimeError):
                r.run('gh', 'api', 'graphql', '-f', 'query=x')

    def test_a_failed_call_that_names_a_rate_limit_stops_the_run(self):
        done = subprocess.CompletedProcess(['gh'], 1, stdout='',
                                           stderr='gh: API rate limit exceeded for user ID 1. (HTTP 403)\n')
        with patch.object(r.subprocess, 'run', return_value=done), \
                patch.object(r, 'budget_reset', return_value='2026-01-01T00:00:00Z'):
            with self.assertRaises(r.RateLimit) as raised:
                r.run('gh', 'api', 'graphql', '-f', 'query=x')
        self.assertEqual(raised.exception.reset, '2026-01-01T00:00:00Z')

    def test_rate_limit_stops_the_run_at_once_with_one_clean_line(self):
        result, hyper = self.run_cli(GH_FAKE, {'GH_FAILURE': 'gh: API rate limit exceeded for user ID 1. (HTTP 403)\n'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'reconcile: GitHub rate limit; reset {RESET_TEXT}; no moves applied', result.stdout)
        self.assertEqual([l for l in result.stdout.splitlines() if l.startswith('reconcile:')].count(
            f'reconcile: GitHub rate limit; reset {RESET_TEXT}; no moves applied'), 1)
        self.assertNotIn('UNKNOWN', result.stdout)
        # It stopped on the first GraphQL call, not one per ticket.
        self.assertEqual(result.stderr.count('API rate limit'), 0)
        self.assertNotIn('task move', hyper)

    def test_a_403_that_is_not_a_rate_limit_still_fails_loudly(self):
        result, _ = self.run_cli(GH_FAKE, {'GH_FAILURE': 'gh: Resource not accessible by integration (HTTP 403)\n'})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn('GitHub rate limit', result.stdout)
        self.assertIn('Resource not accessible by integration', result.stdout + result.stderr)

    def test_spent_budget_skips_the_run_before_reading_the_board(self):
        result, hyper = self.run_cli(GH_FAKE, {'GH_BUDGET': '0'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'reconcile: GitHub rate limit; reset {RESET_TEXT}; no moves applied', result.stdout)
        self.assertEqual(hyper, '')

    def test_rate_limit_while_reading_facts_is_fatal_not_unknown(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(r.Path, 'home', return_value=Path(directory)), \
                patch.object(sys, 'argv', ['reconcile']), \
                patch.object(r, 'tickets', return_value=[task()]), \
                patch.object(r, 'discover', return_value={'SOFT-1': []}), \
                patch.object(r, 'read_sections', return_value=set()), \
                patch.object(r, 'collect', side_effect=r.RateLimit(RESET_TEXT)), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 0)
        self.assertNotIn('UNKNOWN', out.getvalue())
        self.assertIn('GitHub rate limit', out.getvalue())


class CallBudgetTest(unittest.TestCase):
    """Fewer GitHub calls for the same PLAN and KEEP outcomes."""

    def setUp(self):
        TEST_CACHE.unlink(missing_ok=True)
        r.PULLS.clear()
        r.FAILED.clear()
        r.FAILED_REPOS.clear()

    def node(self, number=1, total=None, comments=(), checks=None, more=False):
        return {'url': f'https://github.com/valentinyeo/another-repo/pull/{number}', 'state': 'OPEN',
                'headRefOid': HEAD, 'baseRefOid': 'b' * 40, 'author': {'login': 'writer'},
                'statusCheckRollup': {'contexts': {'pageInfo': {'hasNextPage': more}, 'nodes': checks if checks is not None else [
                    {'__typename': 'CheckRun', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}]}},
                'comments': {'totalCount': len(comments) if total is None else total,
                             'nodes': list(comments)}}

    def graphql_comment(self, verdict=None, login='verifier', when='2026-01-01T00:00:00Z', number=9):
        body = '' if verdict is None else '```verify-verdict\n' + json.dumps(verdict) + '\n```'
        return {'databaseId': number, 'body': body, 'updatedAt': when, 'author': {'login': login}}

    def verdict(self, status='PASS', head=HEAD):
        return {'status': status, 'head_sha': head,
                'run_url': 'https://github.com/valentinyeo/another-repo/actions/runs/9'}

    def test_prefetch_reads_prs_in_batches(self):
        pulls = {f'SOFT-{n}': [{'repository': {'nameWithOwner': 'valentinyeo/another-repo'},
                                'number': n, 'state': 'OPEN'}] for n in range(30)}
        with patch.object(r, 'read_pull_batch', return_value={}) as batch:
            r.prefetch(pulls)
        self.assertEqual(batch.call_count, 2)
        self.assertEqual(sorted(len(c.args[0]) for c in batch.call_args_list), [5, 25])

    def test_one_graphql_call_reads_many_prs(self):
        data = {'data': {'p0': {'pullRequest': self.node(1)}, 'p1': {'pullRequest': self.node(2)}}}
        with patch.object(r, 'run', return_value=json.dumps(data)) as run, \
                patch.object(r, 'verifier_policy', return_value=POLICY):
            found = r.read_pull_batch([('valentinyeo/another-repo', 1), ('valentinyeo/another-repo', 2)])
        self.assertEqual(run.call_count, 1)
        self.assertIn('pullRequest(number:1)', run.call_args.args[-1])
        self.assertEqual(found[('valentinyeo/another-repo', 2)], r.Pull(
            'https://github.com/valentinyeo/another-repo/pull/2', 'OPEN', 'green', False))

    def test_graphql_comments_reach_the_verdict_reader_in_the_same_shape(self):
        data = {'data': {'p0': {'pullRequest': self.node(comments=[
            self.graphql_comment(self.verdict(), number=9), self.graphql_comment(number=10)])}}}
        with patch.object(r, 'run', return_value=json.dumps(data)), \
                patch.object(r, 'verifier_policy', return_value=POLICY), \
                patch.object(r, 'pass_on_head', return_value=True) as verdict:
            found = r.read_pull_batch([('valentinyeo/another-repo', 1)])
        self.assertTrue(found[('valentinyeo/another-repo', 1)].passed)
        comments = verdict.call_args.args[0]
        self.assertEqual(comments[0]['user'], {'login': 'verifier'})
        self.assertEqual(comments[0]['id'], 9)
        self.assertEqual(comments[0]['updated_at'], '2026-01-01T00:00:00Z')
        self.assertIn('verify-verdict', comments[0]['body'])
        self.assertEqual(verdict.call_args.args[1], HEAD)

    def test_verdict_older_than_the_newest_hundred_is_still_found(self):
        older = [{'user': {'login': 'verifier'}, 'body': '```verify-verdict\n' + json.dumps(self.verdict()) + '\n```',
                  'updated_at': '2025-06-01T00:00:00Z', 'id': 4}]
        data = {'data': {'p0': {'pullRequest': self.node(comments=[self.graphql_comment(number=8)], total=150)}}}
        with patch.object(r, 'run', side_effect=[json.dumps(data), json.dumps([older])]) as run, \
                patch.object(r, 'verifier_policy', return_value=POLICY), \
                patch.object(r, 'pass_on_head', side_effect=[False, True]) as verdict:
            found = r.read_pull_batch([('valentinyeo/another-repo', 1)])
        self.assertTrue(found[('valentinyeo/another-repo', 1)].passed)
        self.assertEqual(verdict.call_count, 2)
        self.assertIn('comments?per_page=100', run.call_args_list[-1].args[-1])

    def test_over_a_hundred_checks_use_git_hubs_own_summary(self):
        for summary, expected in (('SUCCESS', 'green'), ('PENDING', 'running'),
                                  ('FAILURE', 'red'), ('EXPECTED', 'running')):
            node = self.node(more=True)
            node['statusCheckRollup']['state'] = summary
            with self.subTest(summary=summary), \
                    patch.object(r, 'run', return_value=json.dumps({'data': {'p0': {'pullRequest': node}}})), \
                    patch.object(r, 'verifier_policy', return_value=POLICY):
                found = r.read_pull_batch([('valentinyeo/another-repo', 1)])
            self.assertEqual(found[('valentinyeo/another-repo', 1)].checks, expected)

    def test_a_refused_batch_splits_so_one_repository_hides_nothing(self):
        broken = 'valentinyeo/broken-repo'

        def call(*args):
            query = args[-1]
            if '"broken-repo"' in query:
                raise RuntimeError('gh api graphql failed: Could not resolve to a Repository')
            nodes = {}
            for n, number in enumerate(re.findall(r'pullRequest\(number:(\d+)\)', query)):
                nodes[f'p{n}'] = {'pullRequest': self.node(int(number))}
            return json.dumps({'data': nodes})
        refs = [(broken, 1), ('valentinyeo/another-repo', 2),
                ('valentinyeo/another-repo', 3), ('valentinyeo/another-repo', 4)]
        with patch.object(r, 'run', side_effect=call), \
                patch.object(r, 'verifier_policy', return_value=POLICY):
            found = r.read_pull_batch(refs)
        self.assertEqual(sorted(found), [('valentinyeo/another-repo', 2), ('valentinyeo/another-repo', 3),
                                         ('valentinyeo/another-repo', 4)])
        self.assertIn(broken, r.FAILED_REPOS)
        # The known-bad repository costs no further calls this run.
        with patch.object(r, 'run') as run:
            with self.assertRaises(ValueError):
                r.read_pull(broken, 1)
            run.assert_not_called()

    def test_policy_is_cached_on_disk_and_counted(self):
        payload = json.dumps({'content': base64.b64encode(json.dumps(POLICY).encode()).decode()})
        with tempfile.TemporaryDirectory() as home, \
                patch.object(r.Path, 'home', return_value=Path(home)), \
                patch.object(r, 'run', return_value=payload) as run:
            self.assertEqual(r.verifier_policy('valentinyeo/another-repo', HEAD), POLICY)
            self.assertEqual(r.verifier_policy('valentinyeo/another-repo', HEAD), POLICY)
        self.assertEqual(run.call_count, 1)
        self.assertIn('repos/valentinyeo/another-repo/contents/.verify/policy.json?ref=' + HEAD,
                      run.call_args.args[-1])

    def test_missing_policy_is_cached_too(self):
        with tempfile.TemporaryDirectory() as home, \
                patch.object(r.Path, 'home', return_value=Path(home)), \
                patch.object(r, 'run', side_effect=RuntimeError('gh api failed: gh: Not Found (HTTP 404)')) as run:
            self.assertEqual(r.verifier_policy('valentinyeo/another-repo', HEAD), {})
            self.assertEqual(r.verifier_policy('valentinyeo/another-repo', HEAD), {})
        self.assertEqual(run.call_count, 1)


class LabelLockTest(unittest.TestCase):
    """Two sessions sync different labels on one board at once."""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patcher = patch.object(r.Path, 'home', return_value=Path(self.home.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.held = []
        self.addCleanup(self.release)

    def release(self):
        for handles in self.held:
            for handle in handles:
                handle.close()
        self.held.clear()

    def hold(self, label=None):
        handles = r.acquire_locks(r.DEFAULT, label)
        if handles is not None:
            self.held.append(handles)
        return handles

    def test_two_labels_hold_the_board_at_once(self):
        self.assertIsNotNone(self.hold('SOFT-2807'))
        self.assertIsNotNone(self.hold('SOFT-2808'))

    def test_the_same_label_twice_skips(self):
        self.assertIsNotNone(self.hold('SOFT-2807'))
        self.assertIsNone(self.hold('SOFT-2807'))

    def test_the_same_label_in_another_case_or_spacing_skips(self):
        self.assertIsNotNone(self.hold('Verification Backlog'))
        self.assertIsNone(self.hold('verification  backlog'))

    def test_whole_board_and_a_label_exclude_each_other(self):
        self.assertIsNotNone(self.hold())
        self.assertIsNone(self.hold('SOFT-2807'))
        self.release()
        self.assertIsNotNone(self.hold('SOFT-2807'))
        self.assertIsNone(self.hold())

    def test_the_label_lock_sits_beside_the_board_lock(self):
        self.assertIsNotNone(self.hold('Verification Backlog'))
        fleet = Path(self.home.name) / '.local/state/fleet'
        self.assertEqual(r.label_lock_path(r.DEFAULT, 'Verification Backlog'),
                         fleet / 'reconcile-label-verification-backlog.lock')
        self.assertTrue((fleet / 'reconcile.lock').exists())

    def test_a_skipped_labelled_run_names_its_label(self):
        with patch.object(sys, 'argv', ['reconcile', '--label', 'Soft-2807']), \
                patch.object(r.fcntl, 'flock', side_effect=BlockingIOError()), \
                patch.object(r, 'tickets') as tickets, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(r.main(), 0)
        self.assertIn('SKIP board=2060 label=Soft-2807 | reconciliation already running', out.getvalue())
        tickets.assert_not_called()


if __name__ == '__main__':
    unittest.main()
