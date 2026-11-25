import base64
import importlib.machinery
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LINT = ROOT / 'skills/hypertask-work/board-lint'
FIXTURES = ROOT / 'tests/fixtures/board-lint'
BOARD = 99001


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def fake_token(agent_id):
    """A token shaped like the CLI's: its payload carries the agent id."""
    payload = base64.urlsafe_b64encode(json.dumps({'agentId': agent_id}).encode()).decode()
    return f'header.{payload.rstrip("=")}.signature'


def roster_path(temp, text):
    path = Path(temp) / 'roster.txt'
    path.write_text(text or 'Board Drain Loop (live-a, claude, /tmp)\n')
    return path


def load_board_lint():
    loader = importlib.machinery.SourceFileLoader('board_lint_module', str(LINT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class BoardLintTests(unittest.TestCase):
    def run_lint(self, fixture, board=BOARD, extra_env=None, roster_text=None, label=None):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, BOARD_DRAIN_STATE_DIR=temp)
            if extra_env:
                env.update(extra_env)
            roster = roster_path(temp, roster_text)
            args = [str(LINT), '--board', str(board), '--fixture', str(FIXTURES / fixture),
                    '--roster', str(roster), '--skip-comments']
            if label:
                args += ['--label', label]
            return subprocess.run(args, capture_output=True, text=True, env=env)

    def assert_rule(self, output, rule, present=True):
        hit = any(f'| {rule} |' in line for line in output.splitlines())
        self.assertEqual(hit, present, output)

    def test_true_column_uses_merge_time_and_section_entry(self):
        data = json.loads((FIXTURES / 'clean.json').read_text())
        card = data['tasks'][0]
        key = card['ticketNumber']
        data['workers'] = {key: False}
        data['pulls'] = {key: [{'url': 'https://github.com/example/x/pull/1',
                               'state': 'MERGED', 'number': 1, 'passed': True,
                               'repository': {'nameWithOwner': 'example/x'}}]}
        for merged_at, should_move in (('2025-11-20T10:00:00Z', False),
                                       ('2025-11-21T11:00:00Z', True)):
            data['pulls'][key][0]['mergedAt'] = merged_at
            with self.subTest(merged_at=merged_at), tempfile.TemporaryDirectory() as temp:
                fixture = Path(temp) / 'merged.json'
                fixture.write_text(json.dumps(data))
                result = self.run_lint(fixture)
                self.assertNotEqual(result.returncode, 2, result.stderr)
                self.assert_rule(result.stdout, 'true-column', present=should_move)

    def test_clean_fixture_exits_zero(self):
        result = self.run_lint('clean.json')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('board-lint: clean', result.stdout)

    def test_stale_agent_from_board_sample(self):
        result = self.run_lint('stale-agent.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')

    def test_agent_assignee_accepts_closed_chat(self):
        result = self.run_lint('agent-closed-chat.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee', present=False)

    def test_own_agent_under_another_name_is_accepted(self):
        # Real case: chat "Multi Bot Android Features" uses the agent "Multiprompt
        # Android Dev". Only the owner renames an agent, so its login settles it.
        result = self.run_lint('agent-own-login.json', label='Multi Bot Android Features')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee', present=False)
        self.assert_rule(result.stdout, 'label-assignee', present=False)

    def test_own_agent_under_another_name_breaks_without_its_login(self):
        # The same card as main read it: no agent id, so the name mismatch stands.
        data = json.loads((FIXTURES / 'agent-own-login.json').read_text())
        data.pop('own_agent_id')
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / 'no-login.json'
            fixture.write_text(json.dumps(data))
            result = self.run_lint(fixture)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assert_rule(result.stdout, 'label-assignee')

    def test_own_agent_under_another_name_still_breaks_when_revoked(self):
        # Its own login does not make a revoked agent a live board member.
        data = json.loads((FIXTURES / 'agent-own-login.json').read_text())
        data['agents'] = []
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / 'revoked-own.json'
            fixture.write_text(json.dumps(data))
            result = self.run_lint(fixture, label='Multi Bot Android Features')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assertIn('revoked', result.stdout)

    def test_another_agent_with_the_same_name_mismatch_still_breaks(self):
        result = self.run_lint('agent-other-login.json', label='Multi Bot Android Features')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assert_rule(result.stdout, 'label-assignee')

    def test_the_own_agent_id_comes_from_the_chats_own_token(self):
        login = load_board_lint().session_login
        chat = 'Multi Bot Android Features'
        agent = '7e61b4e1-c796-4dd9-a851-62bb1ff32341'
        with tempfile.TemporaryDirectory() as temp:
            path = login.token_path(temp, chat)
            path.parent.mkdir(parents=True)
            path.write_text(fake_token(agent))
            self.assertEqual(login.own_agent_id(chat, {'HOME': temp}), agent)
            # Another chat's name never borrows this token.
            self.assertEqual(login.own_agent_id('Board Drain Loop', {'HOME': temp}), '')
            # With no token file of its own, the chat's exported token answers.
            env = {'HOME': temp, 'HT_TOKEN': fake_token(agent)}
            self.assertEqual(login.own_agent_id('Board Drain Loop', env), agent)

    def test_agent_assignee_flags_name_no_chat_ever_had(self):
        result = self.run_lint('agent-unknown-chat.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assertIn('matches no Multibot chat ever', result.stdout)

    def test_agent_assignee_flags_revoked_agent(self):
        result = self.run_lint('agent-revoked.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assertIn('revoked', result.stdout)

    def test_agent_assignee_flags_person(self):
        result = self.run_lint('agent-person.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assertIn('is a person, not an agent', result.stdout)

    def test_agent_assignee_flags_doing_without_worker(self):
        result = self.run_lint('agent-doing-no-worker.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee')
        self.assertIn('Doing with no live worker', result.stdout)

    def test_agent_assignee_accepts_doing_with_worker(self):
        result = self.run_lint('agent-doing-with-worker.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'agent-assignee', present=False)

    def test_wrong_view_label_assignee(self):
        roster = ('Multi Bot Features (live-d, claude, /tmp)\n'
                  'Board Drain Loop (live-a, claude, /tmp)\n')
        result = self.run_lint('wrong-view.json', roster_text=roster)
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'label-assignee')

    def test_app_label_does_not_trigger_label_assignee(self):
        roster = 'Multi Bot Android Verifiy (live-v, claude, /tmp)\n'
        result = self.run_lint('app-label-ok.json', roster_text=roster)
        self.assert_rule(result.stdout, 'label-assignee', present=False)

    def test_waiting_ticket_skips_stale_agent(self):
        result = self.run_lint('waiting-skip-agent.json')
        self.assert_rule(result.stdout, 'agent-assignee', present=False)

    def test_unlinked_open_pr(self):
        result = self.run_lint('unlinked-pr.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'unlinked-work')

    def test_no_owner_label_todo(self):
        result = self.run_lint('no-label-todo.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'no-owner-label')

    def test_the_label_the_chat_armed_with_owns_its_cards(self):
        """Triage is generic, yet a chat armed with it still owns its Triage cards (VSTA-291)."""
        result = self.run_lint('armed-generic-label.json', label='Triage')
        self.assertNotIn('SOFT-3068 | no-owner-label', result.stdout)
        self.assertNotIn('SOFT-3074 | no-owner-label', result.stdout)
        self.assertIn('SOFT-3079 | no-owner-label', result.stdout)

    def test_unnamed_identity(self):
        result = self.run_lint('unnamed-identity.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'unnamed-identity')

    def test_true_column_flags_plan(self):
        result = self.run_lint('wrong-column.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'true-column', present=True)
        self.assertNotIn('FACT-20 | true-column', result.stdout)

    def test_done_without_proof(self):
        result = self.run_lint('done-no-proof.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'done-proof')

    def test_done_with_merged_pass_pr_is_proof(self):
        """A PASS verdict runs before the merge, so merged with PASS is Done proof."""
        fixture = json.loads((FIXTURES / 'done-with-proof.json').read_text())
        fixture.pop('comments', None)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'done-merged-only.json'
            path.write_text(json.dumps(fixture))
            roster = roster_path(temp, 'Board Drain Loop (live-a, claude, /tmp)\n')
            result = subprocess.run(
                [str(LINT), '--board', str(BOARD), '--fixture', str(path),
                 '--roster', str(roster), '--skip-comments'],
                capture_output=True, text=True,
                env=dict(os.environ, BOARD_DRAIN_STATE_DIR=temp))
            self.assert_rule(result.stdout, 'done-proof', present=False)

    def test_done_with_an_unproven_merge_still_needs_proof(self):
        fixture = json.loads((FIXTURES / 'done-with-proof.json').read_text())
        fixture.pop('comments', None)
        fixture['pulls']['FACT-31'][0]['passed'] = False
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'done-merged-unproven.json'
            path.write_text(json.dumps(fixture))
            roster = roster_path(temp, 'Board Drain Loop (live-a, claude, /tmp)\n')
            result = subprocess.run(
                [str(LINT), '--board', str(BOARD), '--fixture', str(path),
                 '--roster', str(roster), '--skip-comments'],
                capture_output=True, text=True,
                env=dict(os.environ, BOARD_DRAIN_STATE_DIR=temp))
            self.assertEqual(result.returncode, 1)
            self.assert_rule(result.stdout, 'done-proof')

    def test_a_merged_pr_without_pass_warns_its_owner(self):
        """The drain-check warning line for a merge nobody verified."""
        fixture = json.loads((FIXTURES / 'clean.json').read_text())
        card = fixture['tasks'][0]
        card['section'] = 'AI Review'
        key = card['ticketNumber']
        fixture['pulls'] = {key: [{'url': 'https://github.com/example/x/pull/1',
                                  'state': 'MERGED', 'number': 1, 'passed': False,
                                  'mergedAt': '2025-11-21T11:00:00Z',
                                  'repository': {'nameWithOwner': 'example/x'}}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'merged-no-pass.json'
            path.write_text(json.dumps(fixture))
            roster = roster_path(temp, 'Board Drain Loop (live-a, claude, /tmp)\n')
            result = subprocess.run(
                [str(LINT), '--board', str(BOARD), '--fixture', str(path),
                 '--roster', str(roster), '--skip-comments'],
                capture_output=True, text=True,
                env=dict(os.environ, BOARD_DRAIN_STATE_DIR=temp))
            self.assertEqual(result.returncode, 1)
            self.assert_rule(result.stdout, 'merged-no-pass')

    def test_merged_verdict_fixtures_accept_pass_shapes_and_flag_fail(self):
        for fixture in ('merged-pass.json', 'merged-pass-notes.json',
                        'merged-pstack-pass-notes.json'):
            with self.subTest(fixture=fixture):
                result = self.run_lint(fixture)
                self.assertNotEqual(result.returncode, 2, result.stderr)
                self.assert_rule(result.stdout, 'merged-no-pass', present=False)
                self.assertIn('merged with PASS', result.stdout)
        failed = self.run_lint('merged-fail.json')
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assert_rule(failed.stdout, 'merged-no-pass', present=True)
        self.assertIn('merged without PASS', failed.stdout)

    def test_merged_no_pass_respects_verifier_cutoff_and_newer_unmerged_pr(self):
        """VSTA-255: pre-cutoff merges (HTPR-7742) and newer open/parked PRs (HTPR-7799) are not breaks."""
        module = load_board_lint()
        now = module.reconcile.stamp('2026-11-24T22:30:00Z')
        hyper = {'nameWithOwner': 'hypertask-ai/hypertask'}
        other = {'nameWithOwner': 'example/unconfigured'}

        def pr(number, state, created, merged=None, passed=False, repo=hyper):
            owner = repo['nameWithOwner']
            return {'url': f'https://github.com/{owner}/pull/{number}',
                    'number': number, 'state': state, 'passed': passed,
                    'createdAt': created, 'mergedAt': merged, 'repository': repo}

        cases = (
            ('HTPR-7799 old merges + newer closed PR', 'HTPR-7799', 'Backlog', [
                pr(2078, 'MERGED', '2026-10-24T14:33:34Z', '2026-10-25T02:15:40Z'),
                pr(3325, 'MERGED', '2026-11-11T05:46:58Z', '2026-11-11T08:07:40Z'),
                pr(3736, 'CLOSED', '2026-11-20T10:58:07Z', None),
            ], False),
            ('HTPR-7742 only merges before cutoff', 'HTPR-7742', 'Backlog', [
                pr(2086, 'MERGED', '2026-10-24T15:47:24Z', '2026-10-24T16:11:07Z'),
                pr(3352, 'MERGED', '2026-11-11T09:10:26Z', '2026-11-11T09:45:11Z'),
                pr(3357, 'MERGED', '2026-11-11T10:14:07Z', '2026-11-11T10:24:28Z'),
            ], False),
            ('post-cutoff merge without PASS still flagged', 'HTPR-9901', 'QA', [
                pr(3800, 'MERGED', '2026-11-20T09:00:00Z', '2026-11-20T10:00:00Z'),
            ], True),
            ('post-cutoff merge + newer open PR skipped', 'HTPR-9902', 'AI Review', [
                pr(3800, 'MERGED', '2026-11-20T09:00:00Z', '2026-11-20T10:00:00Z'),
                pr(3810, 'OPEN', '2026-11-21T09:00:00Z', None),
            ], False),
            ('post-cutoff merge + newer closed-unmerged PR skipped', 'HTPR-9903', 'Backlog', [
                pr(3800, 'MERGED', '2026-11-20T09:00:00Z', '2026-11-20T10:00:00Z'),
                pr(3811, 'CLOSED', '2026-11-21T09:00:00Z', None),
            ], False),
            ('older closed PR + newer post-cutoff merge still flagged', 'HTPR-9904', 'QA', [
                pr(3790, 'CLOSED', '2026-11-18T09:00:00Z', None),
                pr(3800, 'MERGED', '2026-11-20T09:00:00Z', '2026-11-20T10:00:00Z'),
            ], True),
            ('repo with no cutoff entry keeps flagging old merges', 'HTPR-9905', 'QA', [
                pr(12, 'MERGED', '2026-10-24T10:00:00Z', '2026-10-25T10:00:00Z', repo=other),
            ], True),
        )
        for label, key, section, ticket_pulls, flagged in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                fixture = {
                    'now': now,
                    'roster': 'HT Product Lead (live-h, claude, /tmp)\n',
                    'tasks': [{
                        'ticketNumber': key,
                        'projectId': 15,
                        'section': section,
                        'title': label,
                        'updatedAt': '2026-11-24T22:00:00Z',
                        'staleness': {'sectionChangedAt': '2026-10-20T00:00:00Z'},
                        'labels': [{'name': 'HT Product Lead'}],
                        'assignees': [{'type': 'agent', 'displayName': 'HT Product Lead'}],
                    }],
                    'pulls': {key: ticket_pulls},
                }
                path = Path(temp) / f'{key}.json'
                path.write_text(json.dumps(fixture))
                result = self.run_lint(path, board=15,
                                       roster_text='HT Product Lead (live-h, claude, /tmp)\n')
                self.assertNotEqual(result.returncode, 2, result.stderr)
                self.assert_rule(result.stdout, 'merged-no-pass', present=flagged)

    def test_live_saved_pull_facts_clear_merged_no_pass_without_passed_on_search_row(self):
        module = load_board_lint()
        board = module.reconcile.DEFAULT
        now = 1800000000
        task = {
            'ticketNumber': 'SOFT-95', 'projectId': board.id, 'section': 'AI Review',
            'title': 'Merged with saved PASS fact', 'updatedAt': now - 60,
            'staleness': {'sectionChangedAt': now - 3600},
            'labels': [{'name': 'Board Drain Loop'}],
            'assignees': [{'type': 'agent', 'displayName': 'Board Drain Loop'}],
        }
        pull_row = {
            'url': 'https://github.com/valentinyeo/multiprompt/pull/1117',
            'state': 'MERGED', 'number': 1117,
            'mergedAt': '2026-11-24T10:00:00Z', 'createdAt': '2026-11-24T09:00:00Z',
            'repository': {'nameWithOwner': 'valentinyeo/multiprompt'},
        }
        for passed, flagged in ((True, False), (False, True)):
            with self.subTest(passed=passed):
                saved = {
                    'at': now - 60, 'probe_since': '2026-11-24T10:00:00Z', 'repos': [],
                    'tickets': {'SOFT-95': {
                        'at': now - 60, 'updated_at': task['updatedAt'],
                        'pulls': [pull_row],
                        'facts': {'valentinyeo/multiprompt#1117': {
                            'url': pull_row['url'], 'state': 'MERGED', 'checks': 'green',
                            'passed': passed, 'merged_at': now - 120, 'created_at': now - 300,
                        }},
                    }},
                }
                module.reconcile.PULLS.clear()
                args = type('Args', (), {
                    'board': board.id, 'label': 'Board Drain Loop', 'fixture': None,
                    'roster': None, 'skip_comments': True, 'json': False,
                })()
                shared = {
                    'board': board, 'tasks': [task], 'data': {}, 'now': now,
                    'probe_only': True, 'fixture_pulls': None, 'pull_rules': True,
                }
                with mock.patch.object(module.reconcile, 'read_board_facts', return_value=saved), \
                        mock.patch.object(module.reconcile, 'probe_items', return_value=()), \
                        mock.patch.object(module.reconcile, 'read_sections', return_value=set()), \
                        mock.patch.object(module.reconcile, 'worker_alive', return_value=False), \
                        mock.patch.object(module, 'live_names', return_value={'board drain loop'}), \
                        mock.patch.object(module.owners, 'owned_labels', return_value=set()), \
                        mock.patch.object(module, 'known_chats', return_value={'board drain loop'}), \
                        mock.patch.object(module, 'member_agents', return_value=None), \
                        mock.patch.object(module, 'read_views', return_value={}), \
                        mock.patch.object(module, 'read_label_ids', return_value={}), \
                        mock.patch.object(module, 'chat_naming_labels', return_value=set()), \
                        mock.patch.object(module, 'own_agent', return_value=''), \
                        mock.patch.object(module, 'armed_chats', return_value=[]):
                    breaks = module.lint(args, shared=shared)
                rules = [b.rule for b in breaks]
                self.assertEqual('merged-no-pass' in rules, flagged, breaks)

    def test_done_proof_reads_passed_from_reconcile_pulls_when_search_row_omits_it(self):
        module = load_board_lint()
        board = module.reconcile.DEFAULT
        task = {'ticketNumber': 'SOFT-96', 'section': 'Done', 'labels': [{'name': 'Board Drain Loop'}]}
        pull_row = {
            'url': 'https://github.com/valentinyeo/multiprompt/pull/1117',
            'state': 'MERGED', 'number': 1117,
            'repository': {'nameWithOwner': 'valentinyeo/multiprompt'},
        }
        module.reconcile.PULLS.clear()
        module.reconcile.PULLS[('valentinyeo/multiprompt', 1117)] = module.reconcile.Pull(
            pull_row['url'], 'MERGED', 'green', True)
        breaks = []
        module.check_done_proof(task, {'SOFT-96': [pull_row]}, {}, board, breaks)
        self.assertEqual(breaks, [])

    def test_done_with_merged_pr_and_comment_clean(self):
        result = self.run_lint('done-with-proof.json')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assert_rule(result.stdout, 'done-proof', present=False)

    def test_duplicate_title_suggestion(self):
        result = self.run_lint('duplicate-title.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'duplicate-title')

    def test_stale_idle_uses_section_changed_at(self):
        result = self.run_lint('stale-todo.json')
        self.assertEqual(result.returncode, 1)
        self.assert_rule(result.stdout, 'stale-idle')
        self.assertIn('section change', result.stdout)

    def test_stale_idle_skips_waiting_on_valentin(self):
        result = self.run_lint('waiting-stale.json')
        self.assert_rule(result.stdout, 'stale-idle', present=False)

    def test_caller_login_wins_over_reconciler(self):
        module = load_board_lint()
        with tempfile.TemporaryDirectory() as temp:
            sessions = Path(temp) / '.config/hypertask-agents/credentials/sessions'
            sessions.mkdir(parents=True)
            (sessions / 'my-chat-agent-token').write_text('CHAT-TOKEN')
            (sessions / 'hypertask-reconciler-agent-token').write_text('RECONCILER-TOKEN')
            with mock.patch.dict(os.environ, {'HOME': temp, 'SHIP_SESSION_NAME': 'My Chat'}):
                os.environ.pop('HT_TOKEN', None)
                os.environ.pop('MULTIPROMPT_TAB', None)
                module.ensure_token()
                self.assertEqual(os.environ.get('HT_TOKEN'), 'CHAT-TOKEN')

    def test_reconciler_login_only_when_caller_has_none(self):
        module = load_board_lint()
        with tempfile.TemporaryDirectory() as temp:
            sessions = Path(temp) / '.config/hypertask-agents/credentials/sessions'
            sessions.mkdir(parents=True)
            (sessions / 'hypertask-reconciler-agent-token').write_text('RECONCILER-TOKEN')
            with mock.patch.dict(os.environ, {'HOME': temp}):
                os.environ.pop('HT_TOKEN', None)
                os.environ.pop('SHIP_SESSION_NAME', None)
                os.environ.pop('MULTIPROMPT_TAB', None)
                module.ensure_token()
                self.assertEqual(os.environ.get('HT_TOKEN'), 'RECONCILER-TOKEN')

    def test_expired_loop_not_armed_for_sync(self):
        with tempfile.TemporaryDirectory() as temp:
            state = {'name': 'Board Drain Loop', 'board': BOARD, 'label': 'Board Drain Loop',
                     'armed_at': '2020-01-01T00:00:00Z', 'expires_at': '2020-01-02T00:00:00Z',
                     'owner_pid': os.getpid(), 'host': socket.gethostname(),
                     'last_sync': {'at': '2020-01-01T00:00:00Z', 'ok': True, 'reason': ''}}
            states = Path(temp)
            (states / 'board-drain-loop.json').write_text(json.dumps(state))
            roster = roster_path(temp, 'Board Drain Loop (live-a, claude, /tmp)\n')
            env = dict(os.environ, BOARD_DRAIN_STATE_DIR=temp)
            result = subprocess.run(
                [str(LINT), '--board', str(BOARD), '--fixture', str(FIXTURES / 'clean.json'),
                 '--roster', str(roster), '--skip-comments'],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assert_rule(result.stdout, 'sync-record', present=False)

    def test_sync_stale_record(self):
        with tempfile.TemporaryDirectory() as temp:
            state = {'name': 'Board Drain Loop', 'board': BOARD, 'label': 'Board Drain Loop',
                     'armed_at': '2026-01-01T00:00:00Z', 'expires_at': '2099-01-01T00:00:00Z',
                     'owner_pid': os.getpid(), 'host': socket.gethostname(),
                     'last_sync': {'at': '2020-01-01T00:00:00Z', 'ok': True, 'reason': ''}}
            states = Path(temp)
            (states / 'board-drain-loop.json').write_text(json.dumps(state))
            roster = roster_path(temp, 'Board Drain Loop (live-a, claude, /tmp)\n')
            env = dict(os.environ, BOARD_DRAIN_STATE_DIR=temp)
            result = subprocess.run(
                [str(LINT), '--board', str(BOARD), '--fixture', str(FIXTURES / 'sync-stale.json'),
                 '--roster', str(roster), '--skip-comments'],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assert_rule(result.stdout, 'sync-record')

    VIEW_ROSTER = ('Multi Bot Features (live-f, claude, /tmp)\n'
                   'Board Drain Loop (live-a, claude, /tmp)\n')

    def run_view_lint(self, fixture):
        return self.run_lint(fixture, roster_text=self.VIEW_ROSTER)

    def test_view_filter_flags_missing_view(self):
        result = self.run_view_lint('view-missing.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-filter')
        self.assertIn('hypertask view create', result.stdout)

    def test_view_filter_flags_view_without_label_filter(self):
        result = self.run_view_lint('view-no-filter.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-filter')
        self.assertIn('no label filter', result.stdout)
        self.assertIn('hypertask view update v-empty --label "Multi Bot Features"', result.stdout)

    def test_view_filter_flags_filter_on_another_label(self):
        result = self.run_view_lint('view-other-label.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-filter')
        self.assertIn('another label', result.stdout)

    def test_view_filter_and_owner_clean(self):
        result = self.run_view_lint('view-ok.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'view-filter', present=False)
        self.assert_rule(result.stdout, 'view-owner', present=False)

    SILENT_NOW = 1763800800

    def silent_fixture(self, section, entered, last_comment=None):
        stale = {'sectionChangedAt': iso(entered)}
        if last_comment is not None:
            stale['lastCommentAt'] = iso(last_comment)
        task = {'ticketNumber': 'FACT-77', 'projectId': BOARD, 'section': section,
                'title': 'A ticket a person can follow', 'updatedAt': iso(entered),
                'labels': [{'name': 'Board Drain Loop'}],
                'assignees': [{'type': 'agent', 'displayName': 'Board Drain Loop'}],
                'staleness': stale}
        return {'now': self.SILENT_NOW, 'tasks': [task]}

    def run_silent_lint(self, section, entered, last_comment=None):
        data = self.silent_fixture(section, entered, last_comment)
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / 'silent.json'
            fixture.write_text(json.dumps(data))
            return self.run_lint(fixture)

    def test_silent_ticket_names_a_working_card_with_no_comment(self):
        result = self.run_silent_lint('Doing', self.SILENT_NOW - 2 * 3600)
        self.assert_rule(result.stdout, 'silent-ticket')
        self.assertIn('no comment since it entered Doing', result.stdout)
        self.assertIn('hypertask comment add <ticket> --kind qa', result.stdout)

    def test_silent_ticket_skips_a_card_commented_since_it_entered(self):
        result = self.run_silent_lint('Checks', self.SILENT_NOW - 2 * 3600,
                                      self.SILENT_NOW - 3600)
        self.assert_rule(result.stdout, 'silent-ticket', present=False)

    def test_silent_ticket_flags_a_comment_from_before_the_move(self):
        result = self.run_silent_lint('AI Review', self.SILENT_NOW - 2 * 3600,
                                      self.SILENT_NOW - 5 * 3600)
        self.assert_rule(result.stdout, 'silent-ticket')

    def test_silent_ticket_flags_a_card_moved_to_done_today(self):
        result = self.run_silent_lint('Done', self.SILENT_NOW - 3 * 3600)
        self.assert_rule(result.stdout, 'silent-ticket')
        self.assertIn('moved to Done with no Done comment', result.stdout)
        self.assertIn('--kind done', result.stdout)

    def test_silent_ticket_leaves_a_long_done_card_alone(self):
        result = self.run_silent_lint('Done', self.SILENT_NOW - 3 * 86400)
        self.assert_rule(result.stdout, 'silent-ticket', present=False)

    def test_silent_ticket_leaves_a_todo_card_alone(self):
        result = self.run_silent_lint('Todo', self.SILENT_NOW - 2 * 3600)
        self.assert_rule(result.stdout, 'silent-ticket', present=False)

    def test_view_owner_flags_person_owned_view(self):
        result = self.run_view_lint('view-owner-person.json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-owner')
        self.assertIn('not the chat agent', result.stdout)
        self.assert_rule(result.stdout, 'view-filter', present=False)

    def test_view_owner_accepts_human_owner_when_title_matches_label(self):
        result = self.run_lint(
            'view-owner-human-match.json',
            board=13734,
            roster_text='Seamless Session Transitioning (live-s, claude, /tmp)\n',
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_rule(result.stdout, 'view-owner', present=False)
        self.assert_rule(result.stdout, 'view-filter', present=False)

    def test_view_owner_flags_other_owner_even_when_title_matches(self):
        data = json.loads((FIXTURES / 'view-ok.json').read_text())
        data['views'][0]['owner'] = {
            'id': 'a-other',
            'type': 'agent',
            'displayName': 'Board Drain Loop',
        }
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / 'view-other-owner.json'
            fixture.write_text(json.dumps(data))
            result = self.run_view_lint(fixture)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-owner')

    def test_view_owner_flags_fallback_agent_even_when_title_matches(self):
        data = json.loads((FIXTURES / 'view-ok.json').read_text())
        data['views'][0]['owner'] = {
            'id': 'a-cli',
            'type': 'agent',
            'displayName': 'Valentins Claude Code CLI',
        }
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / 'view-fallback-owner.json'
            fixture.write_text(json.dumps(data))
            result = self.run_view_lint(fixture)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_rule(result.stdout, 'view-owner')

    def test_human_board_write_on_board_15(self):
        fixture = {
            'now': 1763800800,
            'tasks': [{
                'ticketNumber': 'HTPR-9',
                'projectId': 15,
                'section': 'Backlog',
                'title': 'Sample product card',
                'updatedAt': '2025-11-22T00:00:00.000Z',
                'labels': [{'name': 'brain-medium'}],
            }],
            'comments': {
                'HTPR-9': [{
                    'kind': 'qa',
                    'text': 'Valentin typed this',
                    'creator': {'displayName': 'Valentin Yeo'},
                }]
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'board.json'
            path.write_text(json.dumps(fixture))
            roster = roster_path(temp, 'HT Product Lead (live-h, claude, /tmp)\n')
            result = subprocess.run(
                [str(LINT), '--board', '15', '--fixture', str(path), '--roster', str(roster),
                 '--skip-comments'],
                capture_output=True, text=True,
                env=dict(os.environ, BOARD_DRAIN_STATE_DIR=temp))
            self.assertEqual(result.returncode, 1)
            self.assert_rule(result.stdout, 'human-board-write')


class PullFactsTest(unittest.TestCase):
    """A live run reuses saved board facts and never pays for a whole board read."""

    NOW = 1800000000
    TASK = {'ticketNumber': 'FACT-9', 'projectId': 99001, 'section': 'Checks',
            'updatedAt': 1700000000, 'labels': [{'name': 'Board Drain Loop'}]}

    def saved(self):
        return {'at': self.NOW - 60, 'probe_since': '2027-01-01T00:00:00Z', 'repos': [],
                'tickets': {'FACT-9': {'at': self.NOW - 60, 'updated_at': self.TASK['updatedAt'],
                                       'pulls': [{'url': 'https://github.com/org/repo/pull/1',
                                                  'state': 'MERGED', 'number': 1,
                                                  'mergedAt': '2027-01-01T00:00:00Z',
                                                  'createdAt': '2026-12-31T00:00:00Z',
                                                  'repository': {'nameWithOwner': 'org/repo'}}],
                                       'facts': {}}}}

    def load(self, saved, probe_only):
        module = load_board_lint()
        board = module.reconcile.BOARDS[99001] if 99001 in module.reconcile.BOARDS else \
            module.reconcile.DEFAULT
        calls = []

        def fake_run(*args, **kwargs):
            calls.append(args)
            return json.dumps({'items': [], 'total_count': 0})

        with mock.patch.object(module.reconcile, 'read_board_facts', return_value=saved), \
                mock.patch.object(module.reconcile, 'run', side_effect=fake_run):
            pulls = module.load_pulls(board, [self.TASK], probe_only=probe_only)
        return pulls, calls

    def test_a_quiet_run_reuses_saved_facts_behind_one_probe(self):
        pulls, calls = self.load(self.saved(), probe_only=False)
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual([pull['url'] for pull in pulls['FACT-9']],
                         ['https://github.com/org/repo/pull/1'])

    def test_probe_only_reads_one_call_and_keeps_saved_facts(self):
        pulls, calls = self.load(self.saved(), probe_only=True)
        self.assertEqual(len(calls), 1, calls)
        self.assertIn('FACT-9', pulls)

    def test_probe_only_is_quiet_when_no_facts_are_saved(self):
        # A cold cache is unknown, not "no PR": the caller keeps its pull rules quiet.
        pulls, calls = self.load(None, probe_only=True)
        self.assertIsNone(pulls)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()