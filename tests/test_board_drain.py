import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/board-drain'
FIXTURES = ROOT / 'tests/fixtures/board_drain'
NOW = 1800000000


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


drain = load('board_drain_check', SKILL / 'drain-check')
loop = load('board_drain_loop_state', SKILL / 'loop-state')
sync = load('board_drain_sync', SKILL / 'sync')
watch = load('board_drain_watch', SKILL / 'watch')


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


ADD_LINE = 'ADD worker, ADD chat: all gates green'
HOLD_LINE = 'HOLD worker, HOLD chat: load5 30.24 is 1.68x 18 cores, cpu some60 26%'


def snapshot(key):
    """A real ticket and its comments, as `hypertask --json task get` returned them."""
    task = json.loads((FIXTURES / f'{key}.task.json').read_text())['tasks'][0]
    comments = json.loads((FIXTURES / f'{key}.comments.json').read_text())['comments']
    return {'task': task, 'comments': comments}


def todo(key, age=1800, waiting_on=None, blocker=None, comments=(), priority=None):
    task = {'ticketNumber': key, 'projectId': 2060, 'section': 'Todo',
            'labels': [{'name': 'Poteto'}], 'waitingOnUserId': waiting_on,
            'blockerCommentId': blocker, 'updatedAt': iso(NOW - age)}
    if priority is not None:
        task['priority'] = priority
    return {'task': task, 'comments': list(comments)}


def priority_row(index=None, name=None):
    row = {}
    if index is not None:
        row['priority_index'] = index
    if name is not None:
        row['Priority_Value'] = name
    return row


URGENT = priority_row(1, 'Urgent')
HIGH = priority_row(2, 'High')
MEDIUM = priority_row(3, 'Medium')


def agent_assignee(name='Poteto'):
    """The shape `task get` sends for a ticket an agent holds."""
    return {'id': 6, 'email': '', 'displayName': name, 'type': 'agent',
            'agentId': '8658ed82-c372-4e10-8410-0989067bb08f',
            'agent': {'id': '8658ed82-c372-4e10-8410-0989067bb08f', 'displayName': name}}


def doing(key, age=300, section='Doing', assignees=None):
    task = {'ticketNumber': key, 'projectId': 2060, 'section': section,
            'labels': [{'name': 'Poteto'}], 'waitingOnUserId': None,
            'blockerCommentId': None, 'updatedAt': iso(NOW - age),
            'assignees': [agent_assignee()] if assignees is None else assignees}
    return {'task': task, 'comments': []}


def vsta4():
    """VSTA-4 as `hypertask --json task get VSTA-4` sent it: an agent holds it."""
    task = json.loads((FIXTURES / 'VSTA-4.task.json').read_text())['tasks'][0]
    task['updatedAt'] = iso(NOW - 300)
    return {'task': task, 'comments': []}


def vsta(key, section='Todo', age=1800, assignees=None):
    """A board-13556 ticket on the label this check drains."""
    task = {'ticketNumber': key, 'projectId': 13556, 'section': section,
            'labels': [{'name': 'Board Drain Loop'}], 'status': 'Normal',
            'waitingOnUserId': None, 'blockerCommentId': None,
            'updatedAt': iso(NOW - age), 'assignees': assignees or []}
    return {'task': task, 'comments': []}


def blocked_by():
    """VSTA-7's links as `hypertask --json task relations VSTA-7` sent them."""
    return json.loads((FIXTURES / 'VSTA-7.relations.json').read_text())['relations']


def agent_comment(age):
    return {'createdAt': iso(NOW - age), 'creatorId': 6, 'agent': {'id': 'a'},
            'agent_display_name': 'Poteto', 'text': 'working it'}


def human_comment(age):
    return {'createdAt': iso(NOW - age), 'creatorId': 6,
            'creator': {'id': 6, 'displayName': 'Valentin Yeo'}, 'text': 'yes, go'}


# multiprompt-android PR #524 on 23 Nov: open, mergeable, verifier PASS at that head.
PR_524 = {'url': 'https://github.com/valentinyeo/multiprompt-android/pull/524',
          'state': 'OPEN', 'checks': 'green', 'mergeable': True, 'passed': False,
          'mergedAt': None, 'repository': {'nameWithOwner': 'valentinyeo/multiprompt-android'}}


def mubo63(**changes):
    """MUBO-63 as `hypertask --json task get` sent it, the ticket behind PR #524.

    The waiting state is the mistake this rule catches: the chat parked a finished,
    green change in his column or marked it waiting on him.
    """
    row = snapshot('MUBO-63')
    row['task'].update({'projectId': 13734, 'updatedAt': iso(NOW - 600),
                        'labels': [{'name': 'Multiprompt Android'}]})
    row['task'].update(changes)
    return row


def dead_pid():
    """The pid of a process that has already exited."""
    process = subprocess.Popen([sys.executable, '-c', 'pass'])
    process.wait()
    return process.pid


def stuck_card(key='SOFT-2940', age=7200, section='Checks', **task):
    """A card sitting in Checks with an agent on it and nothing else wrong."""
    row = doing(key, age=age, section=section)
    row['task'].update(task)
    return row


def red_pull(pushed=iso(NOW - 2 * 86400), **changes):
    """PR #524 red, with the head push time the board facts never carry."""
    pull = PR_524 | {'checks': 'red'} | changes
    pull.pop('pushedAt', None)
    if pushed is not None:
        pull['pushedAt'] = pushed
    return pull


def checks_payload(row, *pulls):
    """One Checks row with the PR facts a fixture hands drain-check."""
    return {'rows': [row], 'pulls': {row['task']['ticketNumber']: list(pulls)}}


def listed_pull(key='SOFT-2940', checks='red', pushed=iso(NOW - 2 * 86400), **changes):
    """One row of the board's open-PR listing: open, with its checks and last push."""
    row = {'url': PR_524['url'], 'state': 'OPEN', 'title': f'{key}: a card parked in Checks',
           'headRefName': f'{key.lower()}-red-pr', 'checks': checks, 'pushedAt': pushed}
    row.update(changes)
    return row


class Clock:
    """A fake clock: time only moves when the watcher decides to sleep."""

    def __init__(self, moment=NOW):
        self.now = moment
        self.on_sleep = None

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(int((self.now - NOW) // seconds))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        env = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.directory)})
        env.start()
        self.addCleanup(env.stop)
        timer = patch.object(drain.loop_state, 'timer_enabled', return_value=True)
        timer.start()
        self.addCleanup(timer.stop)
        # The board's open-PR listing is one GitHub read: a test never makes it.
        listing = patch.object(drain, 'open_pull_rows', return_value=[])
        listing.start()
        self.addCleanup(listing.stop)

    def run_check(self, rows, *extra, alive=False, board=2060, label='Poteto',
                  probe=(0, ADD_LINE), lane=None):
        fixture = self.directory / 'fixture.json'
        fixture.write_text(json.dumps(rows))
        argv = ['--board', str(board), '--label', label, '--fixture', str(fixture),
                '--now', iso(NOW), *extra]
        out = io.StringIO()
        with patch.object(drain, 'probe_load', return_value=probe), \
                patch.object(drain, 'probe_lane', return_value=lane), \
                patch.object(drain.reconcile, 'worker_alive', return_value=alive), \
                contextlib.redirect_stdout(out):
            code = drain.main(argv)
        return code, out.getvalue()

    def run_payload(self, payload, *extra, alive=False, board=2060, label='Poteto',
                    probe=(0, ADD_LINE), lane=None, fail_rules=frozenset(), now=NOW):
        fixture = self.directory / 'fixture.json'
        fixture.write_text(json.dumps(payload))
        argv = ['--board', str(board), '--label', label, '--fixture', str(fixture),
                '--now', iso(now), *extra]
        out = io.StringIO()
        live = alive if callable(alive) else (lambda *args: alive)
        with patch.object(drain, 'probe_load', return_value=probe), \
                patch.object(drain, 'probe_lane', return_value=lane), \
                patch.object(drain, 'FAIL_RULES', fail_rules), \
                patch.object(drain.reconcile, 'worker_alive', side_effect=live), \
                contextlib.redirect_stdout(out):
            code = drain.main(argv)
        return code, out.getvalue()

    def test_real_case_all_four_unmarked(self):
        # Board 2060 label Poteto this morning, unedited: four real tickets sat
        # unmarked in Todo for hours and nothing was in Doing.
        rows = []
        for key in ('SOFT-2809', 'SOFT-2810', 'SOFT-2813', 'SOFT-2815'):
            row = snapshot(key)
            row['task'].update(section='Todo', waitingOnUserId=None, blockerCommentId=None,
                               labels=[{'name': 'Poteto'}], updatedAt=iso(NOW - 3 * 3600))
            rows.append(row)
        code, out = self.run_check(rows)
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 4 workable Todo, nothing in Doing.', out)
        for key in ('SOFT-2809', 'SOFT-2810', 'SOFT-2813', 'SOFT-2815'):
            self.assertIn(f'stale: {key} workable in Todo for 3h.', out)
            self.assertNotIn(f'waiting: {key}', out)
        self.assertIn('drain-check: FAIL (5 findings)', out)

    def test_real_case_two_marked_variant(self):
        # This morning, marked side: SOFT-2809 and SOFT-2813 sat unmarked in Todo
        # for hours, two other tickets were marked waiting, and nothing was in Doing.
        rows = []
        for key in ('SOFT-2809', 'SOFT-2813'):
            row = snapshot(key)
            row['task'].update(section='Todo', waitingOnUserId=None, blockerCommentId=None,
                               labels=[{'name': 'Poteto'}], updatedAt=iso(NOW - 3 * 3600))
            rows.append(row)
        rows += [todo('SOFT-2801', waiting_on=6), todo('SOFT-2802', waiting_on=6)]
        code, out = self.run_check(rows)
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 2 workable Todo, nothing in Doing.', out)
        self.assertIn('start a worker on SOFT-2809.', out)
        self.assertIn('stale: SOFT-2809 workable in Todo for 3h.', out)
        self.assertIn('stale: SOFT-2813 workable in Todo for 3h.', out)
        self.assertIn('waiting: SOFT-2801 (marked)', out)
        self.assertIn('waiting: SOFT-2802 (marked)', out)
        self.assertIn('drain-check: FAIL (3 findings)', out)

    def test_all_marked_todo_passes(self):
        code, out = self.run_check([todo('SOFT-2901', waiting_on=6),
                                    todo('SOFT-2902', blocker=9001)])
        self.assertEqual(code, 0, out)
        self.assertIn('waiting: SOFT-2901 (marked)', out)
        self.assertIn('waiting: SOFT-2902 (marked)', out)
        self.assertIn('drain-check: PASS', out)

    def test_real_case_a_green_pr_parked_in_his_column_fails(self):
        # multiprompt-android PR #524: finished, open, MERGEABLE and green, held for his yes.
        row = mubo63(section='Valentin Review', waitingOnUserId=6)
        payload = {'rows': [row], 'pulls': {'MUBO-63': [PR_524]}}
        code, out = self.run_payload(payload, board=13734, label='Multiprompt Android')
        self.assertEqual(code, 1, out)
        self.assertIn('wait on merge: MUBO-63 waits on Valentin with open green PR '
                      'https://github.com/valentinyeo/multiprompt-android/pull/524; '
                      'merge it yourself per pstack shipping; ask him only a product question', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_ticket_marked_waiting_on_him_with_a_green_pr_fails(self):
        row = mubo63(section='Checks', waitingOnUserId=6)
        payload = {'rows': [row], 'pulls': {'MUBO-63': [PR_524]}}
        code, out = self.run_payload(payload, board=13734, label='Multiprompt Android')
        self.assertEqual(code, 1, out)
        self.assertIn('wait on merge: MUBO-63', out)

    def test_the_newest_chat_comment_asking_him_to_merge_fails(self):
        row = mubo63(section='Checks', waitingOnUserId=6)
        row['comments'] = [{'createdAt': iso(NOW - 600),
                            'agent_display_name': 'Multiprompt Android Dev',
                            'text': 'Finished and green. Say ship and I will merge '
                                    'https://github.com/valentinyeo/multiprompt-android/pull/524.'}]
        payload = {'rows': [row], 'pulls': {'MUBO-63': [PR_524 | {'checks': 'red'}]}}
        code, out = self.run_payload(payload, board=13734, label='Multiprompt Android')
        self.assertEqual(code, 1, out)
        self.assertIn('its newest chat comment asks him to merge', out)

    def test_a_real_product_question_still_passes(self):
        row = mubo63(section='Checks', waitingOnUserId=6)
        row['comments'] = [{'createdAt': iso(NOW - 600),
                            'agent_display_name': 'Multiprompt Android Dev',
                            'text': 'Should the button be blue or green?'}]
        payload = {'rows': [row], 'pulls': {'MUBO-63': [PR_524 | {'checks': 'red'}]}}
        code, out = self.run_payload(payload, board=13734, label='Multiprompt Android')
        self.assertEqual(code, 0, out)
        self.assertIn('drain-check: PASS', out)
        self.assertNotIn('wait on merge', out)

    def test_a_product_question_about_the_model_shipping_still_passes(self):
        # VSTA-181: HTPR-9457, 9544 and 9545 failed drain-check with "wait on merge" and no PR,
        # because "models ship only on your yes" reads as a merge verb beside "your".
        for text in ('It reached you because models ship only on your yes.',
                     'New models ship only when you say yes.'):
            with self.subTest(text=text):
                row = mubo63(section='Checks', waitingOnUserId=6)
                row['comments'] = [{'createdAt': iso(NOW - 600),
                                    'agent_display_name': 'HT Product Lead',
                                    'text': text}]
                payload = {'rows': [row], 'pulls': {'MUBO-63': [PR_524 | {'checks': 'red'}]}}
                code, out = self.run_payload(payload, board=13734, label='Multiprompt Android')
                self.assertEqual(code, 0, out)
                self.assertNotIn('wait on merge', out)

    def test_a_red_or_conflicting_pr_is_not_finished_work(self):
        for pull in (PR_524 | {'checks': 'red'}, PR_524 | {'mergeable': False},
                     PR_524 | {'state': 'MERGED'}):
            with self.subTest(pull=pull):
                row = mubo63(section='Valentin Review', waitingOnUserId=6)
                payload = {'rows': [row], 'pulls': {'MUBO-63': [pull]}}
                code, out = self.run_payload(payload, board=13734, label='Multiprompt Android')
                self.assertEqual(code, 0, out)
                self.assertNotIn('wait on merge', out)

    def test_a_green_pr_on_a_ticket_that_does_not_wait_on_him_passes(self):
        # Its helper is on the PR, so nothing asks for the merge and nothing is orphaned.
        row = mubo63(section='Checks', waitingOnUserId=None)
        payload = {'rows': [row], 'pulls': {'MUBO-63': [PR_524]}}
        code, out = self.run_payload(payload, board=13734, label='Multiprompt Android',
                                     alive=True)
        self.assertEqual(code, 0, out)
        self.assertNotIn('wait on merge', out)
        self.assertNotIn('orphan PR:', out)

    def test_an_open_pr_with_no_helper_is_an_orphan(self):
        # VSTA-210: the owner carries its PR to merge, so an open PR with no helper is
        # the work it owes before it starts a new ticket.
        code, out = self.run_payload(checks_payload(stuck_card(), PR_524))
        self.assertEqual(code, 1, out)
        self.assertIn('orphan PR: SOFT-2940 https://github.com/valentinyeo/multiprompt-android/'
                      'pull/524 has no live helper; start a helper on this PR before any new '
                      'ticket', out)

    def test_a_live_helper_on_the_pr_means_no_orphan(self):
        live = lambda key, now, board: key == 'SOFT-2940'
        code, out = self.run_payload(checks_payload(stuck_card(), PR_524), alive=live)
        self.assertEqual(code, 0, out)
        self.assertNotIn('orphan PR:', out)

    def test_a_card_blocked_by_work_in_flight_is_not_an_orphan(self):
        # SOFT-2944 waits on SOFT-2945, and SOFT-2945 has a live helper, so its own PR
        # idles on purpose rather than being dropped.
        row = todo('SOFT-2944')
        row['relations'] = [{'relationType': 'BlockedBy', 'direction': 'outgoing',
                             'otherTask': {'ticketNumber': 'SOFT-2945', 'status': 'Normal'}}]
        payload = {'rows': [row, doing('SOFT-2945')],
                   'pulls': {'SOFT-2944': [PR_524]}}
        live = lambda key, now, board: key == 'SOFT-2945'
        code, out = self.run_payload(payload, alive=live)
        self.assertEqual(code, 0, out)
        self.assertIn('blocked: SOFT-2944 by SOFT-2945', out)
        self.assertNotIn('orphan PR:', out)

    def test_an_orphan_pr_outranks_starting_on_a_fresh_todo(self):
        # Valentin's rule: a PR comes first. The advice names the orphan, never the Todo
        # the loop would otherwise pick.
        payload = {'rows': [stuck_card(), todo('SOFT-2946', age=3 * 3600)],
                   'pulls': {'SOFT-2940': [PR_524]}}
        code, out = self.run_payload(payload)
        self.assertEqual(code, 1, out)
        self.assertIn('orphan PR: SOFT-2940', out)
        self.assertNotIn('loop off:', out)
        self.assertNotIn('stale: SOFT-2946', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_human_answer_after_the_agent_fails(self):
        comments = [agent_comment(3600), human_comment(600)]
        code, out = self.run_check([todo('SOFT-2903', waiting_on=6, comments=comments)])
        self.assertEqual(code, 1, out)
        self.assertIn('answered: SOFT-2903 clear the waiting-on mark and work it', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_an_agent_comment_after_the_human_stays_waiting(self):
        comments = [human_comment(3600), agent_comment(600)]
        code, out = self.run_check([todo('SOFT-2904', waiting_on=6, comments=comments)])
        self.assertEqual(code, 0, out)
        self.assertIn('waiting: SOFT-2904 (marked)', out)

    def test_a_fresh_doing_ticket_is_alive(self):
        for section in ('Doing', 'Building'):
            with self.subTest(section=section):
                code, out = self.run_check([doing('SOFT-2905', age=300, section=section)])
                self.assertEqual(code, 0, out)
                self.assertIn('drain-check: PASS', out)

    def test_an_old_doing_ticket_without_a_worker_stalls(self):
        code, out = self.run_check([doing('SOFT-2906', age=7200)], alive=False)
        self.assertEqual(code, 1, out)
        self.assertIn('stalled: SOFT-2906 in Doing with no live worker.', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_live_lease_counts_even_on_an_old_doing_ticket(self):
        code, out = self.run_check([doing('SOFT-2907', age=7200)], alive=True)
        self.assertEqual(code, 0, out)

    def test_a_red_pr_idle_an_hour_with_no_owner_is_stuck(self):
        # VSTA-187, now on the hourly clock (VSTA-208): a card parked in Checks on a red
        # PR that took no push for an hour, with no worker holding it, needs a fresh
        # owner rather than another tick.
        with patch.object(drain, 'read_pull_facts') as read:
            code, out = self.run_payload(checks_payload(stuck_card(), red_pull()))
        self.assertEqual(code, 1, out)
        read.assert_not_called()
        self.assertIn('stuck: SOFT-2940 in Checks, PR '
                      'https://github.com/valentinyeo/multiprompt-android/pull/524 red and idle '
                      'since 2027-01-13 08:00 UTC, no live owner. Start a fresh plan-pick owner '
                      'to fix or close it.', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_green_pr_in_checks_is_not_stuck_and_costs_no_read(self):
        # A helper holds the card, so the day rule never asks GitHub about it.
        with patch.object(drain, 'read_pull_facts') as read:
            code, out = self.run_payload(checks_payload(stuck_card(), PR_524), alive=True)
        self.assertEqual(code, 0, out)
        read.assert_not_called()
        self.assertNotIn('stuck:', out)

    def test_a_push_inside_an_hour_is_not_stuck(self):
        # The window is one hour: a push inside it, or exactly on it, still counts as
        # an owner working the PR.
        for push in (iso(NOW - 60), iso(NOW - 3600)):
            with self.subTest(push=push):
                with patch.object(drain, 'read_pull_facts') as read:
                    code, out = self.run_payload(checks_payload(stuck_card(), red_pull(push)),
                                                alive=True)
                self.assertEqual(code, 0, out)
                read.assert_not_called()
                self.assertNotIn('stuck:', out)
                # A helper aside, the day alone decides: this card is one hour short.
                self.assertIsNone(drain.stuck_finding(
                    stuck_card()['task'], {'SOFT-2940': [red_pull(push)]}, NOW,
                    drain.reconcile.DEFAULT))

    def test_a_live_lease_on_the_card_means_it_is_not_stuck(self):
        code, out = self.run_payload(checks_payload(stuck_card(), red_pull()), alive=True)
        self.assertEqual(code, 0, out)
        self.assertNotIn('stuck:', out)

    def test_a_card_with_no_pr_link_is_matched_to_the_board_listing_by_key(self):
        # VSTA-187 on real data: an idle Checks card carries no PR link and the board's
        # saved facts never cover it, so its open PR comes from the board listing.
        with patch.object(drain, 'open_pull_rows', return_value=[listed_pull()]) as read:
            code, out = self.run_payload({'rows': [stuck_card()]})
        self.assertEqual(code, 1, out)
        read.assert_called_once()
        self.assertIn('stuck: SOFT-2940 in Checks, PR '
                      'https://github.com/valentinyeo/multiprompt-android/pull/524 red and idle '
                      'since 2027-01-13 08:00 UTC, no live owner. Start a fresh plan-pick owner '
                      'to fix or close it.', out)

    def test_a_listed_pr_is_matched_by_branch_name_too(self):
        # A branch written with the key in lower case still names the card.
        pull = listed_pull(title='Fix the pane', headRefName='soft-2940-red-pr')
        with patch.object(drain, 'open_pull_rows', return_value=[pull]):
            code, out = self.run_payload({'rows': [stuck_card()]})
        self.assertEqual(code, 1, out)
        self.assertIn('stuck: SOFT-2940 in Checks', out)

    def test_a_listed_pr_on_another_card_is_not_this_cards_pr(self):
        with patch.object(drain, 'open_pull_rows',
                          return_value=[listed_pull(key='SOFT-294')]):
            code, out = self.run_payload({'rows': [stuck_card()]})
        self.assertEqual(code, 0, out)
        self.assertNotIn('stuck:', out)

    def test_a_listed_pr_pushed_inside_an_hour_is_not_stuck(self):
        pull = listed_pull(pushed=iso(NOW - 60))
        with patch.object(drain, 'open_pull_rows', return_value=[pull]):
            code, out = self.run_payload({'rows': [stuck_card()]})
        self.assertEqual(code, 0, out)
        self.assertNotIn('stuck:', out)

    def test_the_listing_is_read_once_ten_minutes(self):
        listing = [listed_pull()]
        with patch.object(drain, 'open_pull_rows', return_value=listing) as read:
            first = self.run_payload({'rows': [stuck_card()]})
            second = self.run_payload({'rows': [stuck_card()]}, now=NOW + 300)
            third = self.run_payload({'rows': [stuck_card()]}, now=NOW + 601)
        self.assertEqual((first[0], second[0], third[0]), (1, 1, 1), second[1])
        self.assertEqual(read.call_count, 2, 'one read per ten minutes, not one a tick')
        for code, out in (first, second, third):
            self.assertIn('stuck: SOFT-2940 in Checks', out)

    def test_a_listing_taken_before_the_last_push_cannot_mark_a_card_stuck(self):
        # The listing is a snapshot: a push after it was taken is invisible to it, so a
        # card read from it is judged against the moment of the snapshot, not now.
        pull = listed_pull(pushed=iso(NOW - 3000))
        drain.save_listing(drain.reconcile.BOARDS[2060], [pull], NOW - 600)
        code, out = self.run_payload({'rows': [stuck_card()]})
        self.assertEqual(code, 0, out)
        self.assertNotIn('stuck:', out)

    def test_a_listing_that_saw_an_hour_of_silence_marks_the_card_stuck(self):
        pull = listed_pull(pushed=iso(NOW - 2 * 3600))
        drain.save_listing(drain.reconcile.BOARDS[2060], [pull], NOW - 600)
        code, out = self.run_payload({'rows': [stuck_card()]})
        self.assertEqual(code, 1, out)
        self.assertIn('stuck: SOFT-2940 in Checks', out)

    def test_a_failed_listing_read_hides_no_other_finding(self):
        for failure in (RuntimeError('gh down'), KeyError('data'), ValueError('not json')):
            with self.subTest(failure=failure):
                with patch.object(drain, 'open_pull_rows', side_effect=failure):
                    code, out = self.run_payload({'rows': [stuck_card(assignees=[])]})
                self.assertEqual(code, 1, out)
                self.assertNotIn('stuck:', out)
                self.assertIn('unassigned: SOFT-2940 in Checks has no agent assigned.', out)

    def test_a_failed_github_read_hides_no_other_finding(self):
        row = stuck_card(assignees=[])
        for failure in (RuntimeError('gh down'), 'not json'):
            with self.subTest(failure=failure):
                with patch.object(drain.reconcile, 'run', side_effect=failure):
                    code, out = self.run_payload(checks_payload(row, red_pull(pushed=None)))
                self.assertEqual(code, 1, out)
                self.assertNotIn('stuck:', out)
                self.assertIn('unassigned: SOFT-2940 in Checks has no agent assigned.', out)

    def test_a_no_lane_hold_collapses_a_stuck_card(self):
        code, out = self.run_payload(checks_payload(stuck_card(), red_pull()), lane=NOW - 60)
        self.assertEqual(code, 0, out)
        self.assertIn('held: no worker lane since', out)
        self.assertNotIn('stuck:', out)
        self.assertIn('drain-check: PASS', out)

    def test_an_unknown_pr_costs_one_read_and_can_still_be_stuck(self):
        facts = {'state': 'OPEN', 'checks': 'red', 'pushed': NOW - 2 * 86400}
        with patch.object(drain, 'read_pull_facts', return_value=facts) as read:
            code, out = self.run_payload(checks_payload(stuck_card(), {'url': PR_524['url']}))
        self.assertEqual(code, 1, out)
        read.assert_called_once_with(PR_524['url'])
        self.assertIn('stuck: SOFT-2940 in Checks', out)

    def test_the_board_link_alone_names_the_pr_to_read(self):
        row = stuck_card(pullRequests=[{'url': PR_524['url'], 'state': 'OPEN'}])
        facts = {'state': 'OPEN', 'checks': 'red', 'pushed': NOW - 2 * 86400}
        with patch.object(drain, 'read_pull_facts', return_value=facts) as read:
            code, out = self.run_payload({'rows': [row]})
        self.assertEqual(code, 1, out)
        read.assert_called_once_with(PR_524['url'])
        self.assertIn('stuck: SOFT-2940 in Checks', out)

    def test_an_assigned_ticket_in_a_working_column_is_not_flagged(self):
        code, out = self.run_check([vsta4()], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 0, out)
        self.assertNotIn('unassigned:', out)
        self.assertIn('drain-check: PASS', out)

    def test_an_unassigned_ticket_in_a_working_column_is_flagged(self):
        row = vsta4()
        row['task']['assignees'] = []
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertIn('unassigned: VSTA-4 in AI Review has no agent assigned. Assign your own '
                      'agent login to it (task assign VSTA-4 --self, with your token).', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_only_a_human_assignee_still_counts_as_unassigned(self):
        row = vsta4()
        row['task']['assignees'] = [{'id': 6, 'email': 'valentin.yeo@gmail.com',
                                     'displayName': 'Valentin Yeo', 'type': 'user'}]
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertIn('unassigned: VSTA-4 in AI Review has no agent assigned.', out)

    def test_every_working_column_needs_an_agent(self):
        for column in ('Doing', 'Building', 'Checks', 'AI Review', 'Verifier'):
            with self.subTest(column=column):
                row = doing('SOFT-2917', section=column, assignees=[])
                code, out = self.run_check([row])
                self.assertEqual(code, 1, out)
                self.assertIn(f'unassigned: SOFT-2917 in {column} has no agent assigned.', out)

    def test_an_unassigned_todo_ticket_is_not_an_unassigned_finding(self):
        # Todo is where a ticket waits for an owner; only a working column needs one.
        row = todo('SOFT-2918')
        row['task']['assignees'] = []
        code, out = self.run_check([row])
        self.assertNotIn('unassigned:', out)

    def test_a_todo_with_no_timestamp_is_never_stale(self):
        # The API may send updatedAt null; that is not a crash and not an age.
        row = todo('SOFT-2910')
        row['task']['updatedAt'] = None
        code, out = self.run_check([row])
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)
        self.assertIn('start a worker on SOFT-2910.', out)
        self.assertNotIn('stale:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_an_unparsable_timestamp_is_never_fresh(self):
        row = todo('SOFT-2911')
        row['task']['updatedAt'] = 'not a date'
        code, out = self.run_check([row])
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 1 workable Todo', out)
        self.assertNotIn('stale:', out)

    def top(self, rows):
        return drain.top_key(rows, NOW, drain.fixture_board(2060, rows))

    def test_top_key_prefers_an_urgent_ticket_over_an_older_medium_one(self):
        rows = [todo('SOFT-3101', age=3 * 3600, priority=MEDIUM),
                todo('SOFT-3102', age=300, priority=URGENT)]
        self.assertEqual(self.top(rows), 'SOFT-3102')

    def test_top_key_breaks_a_priority_tie_by_age(self):
        rows = [todo('SOFT-3103', age=600, priority=HIGH),
                todo('SOFT-3104', age=3 * 3600, priority=HIGH)]
        self.assertEqual(self.top(rows), 'SOFT-3104')

    def test_top_key_breaks_a_priority_and_age_tie_by_lowest_key(self):
        rows = [todo('SOFT-3106', age=600, priority=MEDIUM),
                todo('SOFT-3105', age=600, priority=MEDIUM)]
        self.assertEqual(self.top(rows), 'SOFT-3105')

    def test_top_key_puts_a_no_priority_card_last_however_old_it_is(self):
        # Hypertask index 0 means No Priority, so it must never outrank a real one.
        rows = [todo('SOFT-3123', age=3 * 3600, priority=priority_row(0, 'No Priority')),
                todo('SOFT-3124', age=300, priority=MEDIUM)]
        self.assertEqual(self.top(rows), 'SOFT-3124')

    def test_priority_reads_the_rank_from_the_index_or_the_name(self):
        self.assertEqual(drain.wip.rank({'priority': URGENT}), 0)
        self.assertEqual(drain.wip.rank({'priority': HIGH}), 1)
        self.assertEqual(drain.wip.rank({'priority': {'Priority_Value': 'Medium'}}), 2)
        self.assertEqual(drain.wip.rank({'priority': 'low'}), 3)
        self.assertEqual(drain.wip.rank({}), drain.wip.NONE_RANK)
        self.assertEqual(drain.wip.rank({'priority': priority_row(0, 'No Priority')}),
                         drain.wip.NONE_RANK)

    def test_a_workable_urgent_ticket_idle_eleven_minutes_fails(self):
        code, out = self.run_check([todo('SOFT-3107', age=11 * 60, priority=URGENT),
                                    doing('SOFT-3108')])
        self.assertEqual(code, 1, out)
        self.assertIn('urgent: SOFT-3107 is urgent and waiting in Todo; start it before any '
                      'other ticket.', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_workable_urgent_ticket_idle_five_minutes_does_not_fail(self):
        code, out = self.run_check([todo('SOFT-3109', age=5 * 60, priority=URGENT),
                                    doing('SOFT-3110')])
        self.assertEqual(code, 0, out)
        self.assertNotIn('urgent:', out)
        self.assertIn('drain-check: PASS', out)

    def test_an_urgent_ticket_waiting_on_valentin_does_not_fail(self):
        code, out = self.run_check([todo('SOFT-3111', age=3600, waiting_on=6, priority=URGENT),
                                    doing('SOFT-3112')])
        self.assertEqual(code, 0, out)
        self.assertNotIn('urgent:', out)
        self.assertIn('waiting: SOFT-3111 (marked)', out)

    def test_an_urgent_ticket_blocked_by_an_open_ticket_does_not_fail(self):
        row = todo('SOFT-3113', age=3600, priority=URGENT)
        row['relations'] = blocked_by()
        code, out = self.run_check([row, doing('SOFT-3114')])
        self.assertEqual(code, 0, out)
        self.assertNotIn('urgent:', out)
        self.assertIn('blocked: SOFT-3113 by VSTA-2, VSTA-3', out)

    def test_a_server_hold_never_hides_an_urgent_ticket(self):
        code, out = self.run_check([todo('SOFT-3115', age=11 * 60, priority=URGENT),
                                    todo('SOFT-3116', age=3 * 3600)], probe=(2, HOLD_LINE))
        self.assertEqual(code, 1, out)
        self.assertIn('urgent: SOFT-3115 is urgent and waiting in Todo;', out)
        self.assertIn(f'held: {HOLD_LINE}; 2 workable Todo wait for the server', out)
        self.assertNotIn('stale:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_no_lane_hold_never_hides_an_urgent_ticket(self):
        code, out = self.run_check([todo('SOFT-3117', age=11 * 60, priority=URGENT),
                                    todo('SOFT-3118', age=3 * 3600)], lane=NOW - 60)
        self.assertEqual(code, 1, out)
        self.assertIn('urgent: SOFT-3117 is urgent and waiting in Todo;', out)
        self.assertIn('held: no worker lane since', out)
        self.assertNotIn('stale:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_loop_off_names_the_urgent_ticket_over_a_much_older_one(self):
        code, out = self.run_check([todo('SOFT-3119', age=3 * 3600, priority=MEDIUM),
                                    todo('SOFT-3120', age=3600, priority=URGENT)])
        self.assertEqual(code, 1, out)
        self.assertIn('start a worker on SOFT-3120.', out)
        self.assertIn('urgent: SOFT-3120', out)

    def test_the_stale_lines_are_ordered_urgent_first(self):
        code, out = self.run_check([todo('SOFT-3121', age=3 * 3600, priority=MEDIUM),
                                    todo('SOFT-3122', age=3 * 3600, priority=URGENT)],
                                   '--no-load')
        self.assertEqual(code, 1, out)
        self.assertLess(out.index('stale: SOFT-3122'), out.index('stale: SOFT-3121'))

    def test_a_marked_todo_with_no_comment_timestamp_does_not_crash(self):
        comments = [dict(agent_comment(3600), createdAt=None)]
        code, out = self.run_check([todo('SOFT-2912', waiting_on=6, comments=comments)])
        self.assertEqual(code, 0, out)
        self.assertIn('waiting: SOFT-2912 (marked)', out)
        self.assertIn('drain-check: PASS', out)

    def test_an_unexpected_error_exits_two_not_one(self):
        with patch.object(drain, 'check', side_effect=AttributeError('boom')), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code = drain.main(['--board', '2060', '--label', 'Poteto', '--now', iso(NOW)])
        self.assertEqual(code, 2, out.getvalue() + err.getvalue())
        self.assertIn('drain-check: error: boom', err.getvalue())

    def test_a_ticket_linked_to_open_blockers_is_not_workable(self):
        # VSTA-7 is BlockedBy VSTA-2 and VSTA-3, both open, so it waits outside the drain.
        rows = [vsta('VSTA-7', age=3 * 3600), vsta('VSTA-2', age=300),
                vsta('VSTA-3', age=300)]
        rows[0]['relations'] = blocked_by()
        for row in rows[1:]:
            row['task'].update(section='Doing', assignees=[agent_assignee()])
        code, out = self.run_check(rows, board=13556, label='Board Drain Loop')
        self.assertEqual(code, 0, out)
        self.assertIn('blocked: VSTA-7 by VSTA-2, VSTA-3', out)
        self.assertNotIn('stale:', out)
        self.assertNotIn('loop off:', out)
        self.assertIn('drain-check: PASS', out)

    def test_a_ticket_whose_blockers_are_done_is_workable(self):
        rows = [vsta('VSTA-7'), vsta('VSTA-2', section='Done'), vsta('VSTA-3', section='Done')]
        rows[0]['relations'] = blocked_by()
        code, out = self.run_check(rows, board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)
        self.assertIn('start a worker on VSTA-7.', out)
        self.assertNotIn('blocked:', out)

    def test_one_open_blocker_among_done_ones_still_blocks(self):
        rows = [vsta('VSTA-7'), vsta('VSTA-2', section='Done'), vsta('VSTA-3')]
        rows[0]['relations'] = blocked_by()
        code, out = self.run_check(rows, board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertIn('blocked: VSTA-7 by VSTA-3', out)
        self.assertNotIn('blocked: VSTA-7 by VSTA-3,', out)
        self.assertIn('loop off: 1 workable Todo', out)

    def test_a_ticket_with_no_links_reads_as_before(self):
        for relations in (None, []):
            with self.subTest(relations=relations):
                row = vsta('VSTA-7')
                if relations is not None:
                    row['relations'] = relations
                code, out = self.run_check([row], board=13556, label='Board Drain Loop')
                self.assertEqual(code, 1, out)
                self.assertIn('loop off: 1 workable Todo', out)
                self.assertNotIn('blocked:', out)

    def test_a_blocker_missing_from_the_board_counts_open(self):
        row = vsta('VSTA-7')
        row['relations'] = [{'relationType': 'BlockedBy', 'direction': 'outgoing',
                             'otherTask': {'ticketNumber': 'SOFT-99', 'status': 'Normal'}}]
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 0, out)
        self.assertIn('blocked: VSTA-7 by SOFT-99', out)
        self.assertIn('drain-check: PASS', out)

    def test_a_missing_blocker_whose_status_says_done_does_not_block(self):
        row = vsta('VSTA-7')
        row['relations'] = [{'relationType': 'BlockedBy', 'direction': 'outgoing',
                             'otherTask': {'ticketNumber': 'SOFT-99', 'status': 'Done'}}]
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertNotIn('blocked:', out)
        self.assertIn('loop off: 1 workable Todo', out)

    def test_incoming_and_blocks_links_never_block(self):
        row = vsta('VSTA-7')
        row['relations'] = [
            {'relationType': 'BlockedBy', 'direction': 'incoming',
             'otherTask': {'ticketNumber': 'VSTA-9', 'status': 'Normal'}},
            {'relationType': 'Blocks', 'direction': 'outgoing',
             'otherTask': {'ticketNumber': 'VSTA-10', 'status': 'Normal'}}]
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 1, out)
        self.assertNotIn('blocked:', out)
        self.assertIn('loop off: 1 workable Todo', out)

    def test_a_marked_ticket_is_never_asked_for_its_links(self):
        # A marked wait already keeps it out of the drain; no links read needed.
        row = vsta('VSTA-8')
        row['task']['waitingOnUserId'] = 6
        row['relations'] = blocked_by()
        code, out = self.run_check([row], board=13556, label='Board Drain Loop')
        self.assertEqual(code, 0, out)
        self.assertIn('waiting: VSTA-8 (marked)', out)
        self.assertNotIn('blocked:', out)

    def test_a_missing_loop_state_fails_when_named(self):
        code, out = self.run_check([todo('SOFT-2908', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('loop state: not armed', out)

    def test_a_dead_watcher_fails_the_check_when_named(self):
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW)
        loop.record_watch('HT Test', dead_pid(), now=NOW)
        code, out = self.run_check([todo('SOFT-2929', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('loop state: watcher dead', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_an_armed_loop_with_a_fresh_sync_passes(self):
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW)
        code, out = self.run_check([todo('SOFT-2913', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 0, out)
        self.assertIn('drain-check: PASS', out)
        self.assertNotIn('sync stale', out)

    def test_a_failed_sync_fails_the_check(self):
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_sync('HT Test', False, 'usage: --apply requires SHIP_SESSION_NAME', now=NOW)
        code, out = self.run_check([todo('SOFT-2914', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('sync failed: usage: --apply requires SHIP_SESSION_NAME. '
                      'Fix it, then run ./sync.', out)

    def test_a_stale_sync_fails_the_check(self):
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW - 3600)
        code, out = self.run_check([todo('SOFT-2915', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('sync stale: last sync 60 min ago.', out)

    def test_a_budget_skip_is_not_a_failed_sync(self):
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW - 600)
        loop.record_sync('HT Test', True, 'sync skipped: gh budget (wait until 14:20 UTC)',
                         now=NOW, skipped=True)
        code, out = self.run_check([todo('SOFT-2917', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 0, out)
        self.assertNotIn('sync failed', out)

    def test_skips_that_outlast_the_window_still_read_stale(self):
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW - 3600)
        loop.record_sync('HT Test', True, 'sync skipped: gh budget (wait until 14:20 UTC)',
                         now=NOW, skipped=True)
        code, out = self.run_check([todo('SOFT-2918', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('sync stale: last sync 60 min ago.', out)

    def test_a_missing_sync_fails_the_check(self):
        loop.arm('HT Test', every='15m', now=NOW)
        code, out = self.run_check([todo('SOFT-2916', waiting_on=6)], '--state-name', 'HT Test')
        self.assertEqual(code, 1, out)
        self.assertIn('sync stale: no sync recorded yet.', out)

    def test_a_server_hold_turns_loop_off_and_stale_into_a_held_line(self):
        # Valentin's rule holds launches while the server is overloaded, so an
        # idle drain on a HOLD server is obeying him, not broken.
        code, out = self.run_check([todo('SOFT-2920', age=3 * 3600),
                                    todo('SOFT-2921', age=3 * 3600)],
                                   probe=(2, HOLD_LINE))
        self.assertEqual(code, 0, out)
        self.assertIn(f'held: {HOLD_LINE}; 2 workable Todo wait for the server', out)
        self.assertNotIn('loop off:', out)
        self.assertNotIn('stale:', out)
        self.assertIn('drain-check: PASS', out)

    def test_a_server_hold_never_hides_a_stalled_ticket(self):
        code, out = self.run_check([doing('SOFT-2922', age=7200)], alive=False,
                                   probe=(2, HOLD_LINE))
        self.assertEqual(code, 1, out)
        self.assertIn('stalled: SOFT-2922 in Doing with no live worker.', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_server_hold_never_hides_an_answered_ticket(self):
        comments = [agent_comment(3600), human_comment(600)]
        code, out = self.run_check([todo('SOFT-2923', waiting_on=6, comments=comments)],
                                   probe=(2, HOLD_LINE))
        self.assertEqual(code, 1, out)
        self.assertIn('answered: SOFT-2923', out)

    def test_an_add_server_still_fails_loop_off(self):
        code, out = self.run_check([todo('SOFT-2924')], probe=(0, ADD_LINE))
        self.assertEqual(code, 1, out)
        self.assertIn('loop off: 1 workable Todo, nothing in Doing.', out)

    def test_a_careful_server_still_fails_loop_off(self):
        code, out = self.run_check([todo('SOFT-2925')],
                                   probe=(1, 'CAREFUL worker, ADD chat: load5 20.0'))
        self.assertEqual(code, 1, out)
        self.assertIn('loop off:', out)

    def test_a_probe_failure_never_hides_a_finding(self):
        code, out = self.run_check([todo('SOFT-2926', age=3 * 3600)], probe=(3, ''))
        self.assertEqual(code, 1, out)
        self.assertIn('loop off:', out)
        self.assertIn('stale:', out)
        self.assertNotIn('held:', out)

    def test_no_load_skips_the_probe(self):
        code, out = self.run_check([todo('SOFT-2927')], '--no-load')
        self.assertEqual(code, 1, out)
        self.assertIn('loop off:', out)
        self.assertNotIn('held:', out)

    def test_the_probe_runs_only_when_loop_off_or_stale_is_there_to_judge(self):
        with patch.object(drain, 'probe_load', return_value=(2, HOLD_LINE)) as probe:
            fixture = self.directory / 'fixture.json'
            fixture.write_text(json.dumps([todo('SOFT-2928', waiting_on=6)]))
            with contextlib.redirect_stdout(io.StringIO()):
                code = drain.main(['--board', '2060', '--label', 'Poteto',
                                   '--fixture', str(fixture), '--now', iso(NOW)])
        self.assertEqual(code, 0)
        probe.assert_not_called()

    def test_a_no_lane_hold_collapses_loop_findings_into_one_line(self):
        # plan-pick found no free lane a minute ago: waiting for one is holding
        # on purpose, so an idle Todo and a stalled Doing are not broken.
        code, out = self.run_check([todo('SOFT-2933', age=3 * 3600),
                                    todo('SOFT-2934', age=3 * 3600),
                                    doing('SOFT-2935', age=7200)],
                                   alive=False, lane=NOW - 60)
        self.assertEqual(code, 0, out)
        since = drain.clock_utc(NOW - 60)
        self.assertIn(f'held: no worker lane since {since}; 2 workable Todo wait for a lane', out)
        self.assertNotIn('loop off:', out)
        self.assertNotIn('stale:', out)
        self.assertNotIn('stalled:', out)
        self.assertIn('drain-check: PASS', out)

    def test_a_lane_hold_never_hides_an_unassigned_ticket(self):
        row = doing('SOFT-2936', age=7200)
        row['task']['assignees'] = []
        code, out = self.run_check([todo('SOFT-2937'), row], alive=False, lane=NOW - 60)
        self.assertEqual(code, 1, out)
        self.assertIn('unassigned: SOFT-2936 in Doing has no agent assigned.', out)
        self.assertIn('held: no worker lane since', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_a_server_hold_wins_over_a_lane_hold(self):
        code, out = self.run_check([todo('SOFT-2938')], probe=(2, HOLD_LINE), lane=NOW - 60)
        self.assertEqual(code, 0, out)
        self.assertIn(f'held: {HOLD_LINE}; 1 workable Todo wait for the server', out)
        self.assertNotIn('wait for a lane', out)

    def test_no_load_skips_the_lane_probe_too(self):
        fixture = self.directory / 'fixture.json'
        fixture.write_text(json.dumps([todo('SOFT-2939')]))
        out = io.StringIO()
        with patch.object(drain, 'probe_lane', return_value=NOW - 60) as lane, \
                contextlib.redirect_stdout(out):
            code = drain.main(['--board', '2060', '--label', 'Poteto', '--fixture',
                               str(fixture), '--now', iso(NOW), '--no-load'])
        lane.assert_not_called()
        self.assertEqual(code, 1, out.getvalue())
        self.assertNotIn('held:', out.getvalue())

    def lane_state(self, rows=None, launches=()):
        """A plan-pick state file and launch log in the temp dir, never the real ones."""
        state = self.directory / 'rung-attempts.json'
        state.write_text(json.dumps(rows if rows is not None else {}))
        log = self.directory / 'launches.jsonl'
        log.write_text(''.join(json.dumps(row) + '\n' for row in launches))
        patched = [patch.object(drain, 'PLAN_PICK_STATE', state),
                   patch.object(drain, 'PLAN_PICK_LOG', log)]
        for item in patched:
            item.start()
            self.addCleanup(item.stop)
        return state, log

    def test_the_lane_probe_reads_the_newest_no_lane_row(self):
        self.lane_state({'ticket:SOFT-1': {'failure': 'lane', 'exit_code': 75,
                                           'finished_at': NOW - 900},
                         'ticket:SOFT-2': {'failure': 'lane', 'exit_code': 75,
                                           'finished_at': NOW - 60}})
        self.assertEqual(drain.probe_lane(NOW), NOW - 60)

    def test_a_stale_no_lane_row_does_not_hold(self):
        self.lane_state({'ticket:SOFT-1': {'failure': 'lane', 'exit_code': 75,
                                           'finished_at': NOW - 1801}})
        self.assertIsNone(drain.probe_lane(NOW))

    def test_a_launch_after_the_no_lane_row_does_not_hold(self):
        self.lane_state({'ticket:SOFT-1': {'failure': 'lane', 'exit_code': 75,
                                           'finished_at': NOW - 600}},
                        launches=[{'at': NOW - 300, 'lane': 'opus', 'event': 'start'}])
        self.assertIsNone(drain.probe_lane(NOW))

    def test_a_real_launch_log_beside_the_no_lane_row_still_holds(self):
        # The log mixes finish rows, a launch row and the null-lane row plan-pick
        # writes at the moment it records the miss. Only a lane it took counts, and
        # only a lane taken after the miss lifts it.
        moment = NOW - 120
        self.lane_state({'ticket:SOFT-1': {'event': 'finish', 'exit_code': 75,
                                           'pr_url': None, 'failure': 'lane',
                                           'rung': 'medium', 'finished_at': moment}},
                        launches=[{'at': moment - 3600, 'lane': 'opus', 'event': 'start',
                                   'launch_id': 'a'},
                                  {'event': 'finish', 'launch_id': 'a',
                                   'finished_at': moment - 3000, 'exit_code': 0},
                                  {'at': moment, 'lane': None, 'session': None,
                                   'cwd': '/tmp', 'not_vendor': None, 'caller': '/tmp'}])
        self.assertEqual(drain.probe_lane(NOW), moment)

    def test_a_lane_taken_after_the_no_lane_row_lifts_the_hold(self):
        moment = NOW - 600
        self.lane_state({'ticket:SOFT-2': {'event': 'finish', 'exit_code': 75,
                                           'pr_url': None, 'failure': 'lane',
                                           'rung': 'medium', 'finished_at': moment}},
                        launches=[{'at': moment, 'lane': None, 'session': None,
                                   'cwd': '/tmp', 'not_vendor': None, 'caller': '/tmp'},
                                  {'at': moment + 60, 'lane': 'sonnet', 'event': 'start',
                                   'launch_id': 'b'},
                                  {'event': 'finish', 'launch_id': 'b',
                                   'finished_at': moment + 120, 'exit_code': 0}])
        self.assertIsNone(drain.probe_lane(NOW))

    def test_a_null_lane_launch_row_alone_holds(self):
        # Most no-lane attempts never reach rung-attempts.json: the brief carried no
        # rung job. The null-lane launch row is the only record of those.
        self.lane_state(launches=[{'at': NOW - 300, 'lane': 'opus', 'event': 'start'},
                                  {'at': NOW - 60, 'lane': None, 'session': None,
                                   'cwd': '/tmp', 'not_vendor': None, 'caller': '/tmp'}])
        self.assertEqual(drain.probe_lane(NOW), NOW - 60)

    def test_a_real_launch_after_a_null_lane_row_lifts_the_hold(self):
        self.lane_state(launches=[{'at': NOW - 600, 'lane': None, 'session': None,
                                   'cwd': '/tmp', 'not_vendor': None, 'caller': '/tmp'},
                                  {'at': NOW - 120, 'lane': 'sonnet', 'event': 'start',
                                   'launch_id': 'c'}])
        self.assertIsNone(drain.probe_lane(NOW))

    def test_a_stale_null_lane_row_does_not_hold(self):
        self.lane_state(launches=[{'at': NOW - 1801, 'lane': None, 'session': None,
                                   'cwd': '/tmp', 'not_vendor': None, 'caller': '/tmp'}])
        self.assertIsNone(drain.probe_lane(NOW))

    def test_a_worker_that_hit_a_lane_limit_mid_run_does_not_hold(self):
        # attempt_failure records "lane" for a run that then hit a rate limit; only
        # exit 75 means plan-pick never found a lane to start.
        self.lane_state({'ticket:SOFT-3': {'failure': 'lane', 'exit_code': 1,
                                           'finished_at': NOW - 60}})
        self.assertIsNone(drain.probe_lane(NOW))

    def test_an_unreadable_launch_log_does_not_hold(self):
        state, log = self.lane_state({'ticket:SOFT-4': {'failure': 'lane', 'exit_code': 75,
                                                        'finished_at': NOW - 60}})
        log.write_text('not json\n')
        self.assertIsNone(drain.probe_lane(NOW))
        log.unlink()
        log.mkdir()
        self.assertIsNone(drain.probe_lane(NOW))
        log.rmdir()
        self.assertEqual(drain.probe_lane(NOW), NOW - 60)

    def test_an_unreadable_state_does_not_hold(self):
        state, _ = self.lane_state()
        state.write_text('not json')
        self.assertIsNone(drain.probe_lane(NOW))
        state.unlink()
        state.mkdir()
        self.assertIsNone(drain.probe_lane(NOW))
        state.rmdir()
        self.assertIsNone(drain.probe_lane(NOW))

    def test_a_usage_error_exits_two(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as raised:
            drain.main(['--board', '0', '--label', 'Poteto'])
        self.assertEqual(raised.exception.code, 2)


class RuleBreakTest(CheckTest):
    """Board-rule breaks reach the chat that owns them, in its own drain check."""

    def worker_card(self, assignees=None):
        task = {'ticketNumber': 'SOFT-2931', 'projectId': 2060, 'section': 'Doing',
                'labels': [{'name': 'Poteto'}], 'updatedAt': iso(NOW - 300),
                'assignees': [agent_assignee()] if assignees is None else assignees}
        return {'task': task, 'comments': []}

    CHAT = 'Poteto (live-p, claude, /tmp)\n'

    def payload(self, rows, **facts):
        """Rows plus the board facts a drain-check fixture does not carry."""
        return {'rows': rows, 'roster': self.CHAT, 'chats': ['Poteto'], **facts}

    def sync_record(self, name, reason='apply exited 1', board=13734):
        """An armed loop for this chat with one failed sync recorded against it."""
        loop.arm(name, board=board, now=NOW)
        loop.record_sync(name, False, reason, now=NOW)

    def test_another_chats_sync_break_is_not_this_chats_finding(self):
        self.sync_record('Multi Bot Android Features', reason='apply exited 1')
        self.sync_record('Multi Bot Android Verifiy', reason='sync token expired')
        code, out = self.run_payload(
            self.payload([], chats=['Multi Bot Android Features',
                                    'Multi Bot Android Verifiy']),
            board=13734, label='Multi Bot Android Verifiy')
        self.assertEqual(code, 0, out)
        self.assertNotIn('apply exited 1', out)
        self.assertIn('rule-break: (sync) sync-record: sync failed: sync token expired.', out)

    def test_the_chats_own_sync_break_comes_back_under_its_state_name(self):
        self.sync_record('Multi Bot Android Verifiy', reason='apply exited 1')
        code, out = self.run_payload(
            self.payload([], chats=['Multi Bot Android Verifiy']),
            '--state-name', 'Multi Bot Android Verifiy',
            board=13734, label='Multi Bot Android')
        self.assertEqual(code, 1, out)
        self.assertIn('rule-break: (sync) sync-record: sync failed: apply exited 1.', out)

    def test_the_chats_own_sync_break_comes_back_under_its_label(self):
        self.sync_record('Multi Bot Android Verifiy', reason='apply exited 1')
        code, out = self.run_payload(
            self.payload([], chats=['Multi Bot Android Verifiy']),
            board=13734, label='Multi Bot Android Verifiy')
        self.assertEqual(code, 0, out)
        self.assertIn('rule-break: (sync) sync-record: sync failed: apply exited 1.', out)

    def test_one_break_prints_one_warning_line_and_still_passes(self):
        row = todo('SOFT-2930')
        row['task']['assignees'] = [{'id': 6, 'email': 'valentin.yeo@gmail.com',
                                     'displayName': 'Valentin Yeo', 'type': 'user'}]
        code, out = self.run_payload(self.payload([row, self.worker_card()],
                                                  workers={'SOFT-2931': True}), alive=True)
        breaks = [line for line in out.splitlines() if line.startswith('rule-break: ')]
        self.assertEqual(len(breaks), 1, out)
        self.assertEqual(breaks[0], "rule-break: SOFT-2930 agent-assignee: assignee "
                                    "'Valentin Yeo' is a person, not an agent; assign the chat agent")
        self.assertIn('drain-check: PASS', out)
        self.assertEqual(code, 0, out)

    def test_a_working_card_with_no_comment_prints_the_fix(self):
        row = doing('SOFT-2937')
        row['task']['staleness'] = {'sectionChangedAt': iso(NOW - 3600)}
        code, out = self.run_payload(self.payload([row], workers={'SOFT-2937': True}), alive=True)
        self.assertIn('rule-break: SOFT-2937 silent-ticket: no comment since it entered Doing', out)
        self.assertIn('hypertask comment add <ticket> --kind qa', out)
        self.assertIn('drain-check: PASS', out)
        self.assertEqual(code, 0, out)

    def test_a_working_card_with_a_fresh_comment_is_quiet(self):
        row = doing('SOFT-2938')
        row['task']['staleness'] = {'sectionChangedAt': iso(NOW - 3600),
                                    'lastCommentAt': iso(NOW - 600)}
        code, out = self.run_payload(self.payload([row], workers={'SOFT-2938': True}), alive=True)
        self.assertNotIn('silent-ticket', out)
        self.assertEqual(code, 0, out)

    def test_a_promoted_rule_fails_the_check(self):
        row = todo('SOFT-2932')
        row['task']['assignees'] = [{'id': 6, 'displayName': 'Valentin Yeo', 'type': 'user'}]
        code, out = self.run_payload(self.payload([row, self.worker_card()],
                                                  workers={'SOFT-2931': True}), alive=True,
                                     fail_rules=frozenset({'agent-assignee'}))
        self.assertEqual(code, 1, out)
        self.assertIn('rule-break: SOFT-2932 agent-assignee:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_another_chats_view_break_is_not_this_chats_finding(self):
        # Both labels are on this ticket, but the broken view belongs to another chat.
        row = todo('SOFT-2933', waiting_on=6)
        row['task']['labels'] = [{'name': 'Poteto'}, {'name': 'Multi Bot Bugs'}]
        payload = self.payload([row], chats=['Poteto', 'Multi Bot Bugs'], views=[
            {'slug': 'poteto', 'id': 'v-1', 'owner': {'displayName': 'Poteto'}},
            {'slug': 'multi-bot-bugs', 'id': 'v-2', 'owner': {'displayName': 'Valentin Yeo'}},
        ])
        code, out = self.run_payload(payload)
        self.assertEqual(code, 0, out)
        self.assertIn('drain-check: PASS', out)
        self.assertNotIn('Multi Bot Bugs', out)
        self.assertNotIn('rule-break:', out)

    def test_human_owner_view_with_matching_title_is_not_a_view_owner_break(self):
        label = 'Seamless Session Transitioning'
        row = {'task': {'ticketNumber': 'MUBO-101', 'projectId': 13734, 'section': 'Todo',
                        'labels': [{'name': label}], 'updatedAt': iso(NOW - 300),
                        'waitingOnUserId': 6},
               'comments': []}
        payload = {
            'rows': [row],
            'roster': f'{label} (live-s, claude, /tmp)\n',
            'chats': [label],
            'labels': [{'id': 'L-seamless', 'name': label}],
            'views': [{
                'id': 'v-seamless',
                'title': label,
                'slug': 'seamless-session-transitioning',
                'owner': {'id': 6, 'displayName': 'Valentin Yeo'},
                'board_filters': {'addedFilters': [{'type': 'Labels',
                                                    'searchPayload': [{'id': 'L-seamless'}]}]},
            }],
        }
        code, out = self.run_payload(payload, board=13734, label=label,
                                     fail_rules=frozenset({'view-owner'}))
        self.assertEqual(code, 0, out)
        self.assertIn('drain-check: PASS', out)
        self.assertNotIn('rule-break:', out)

    def test_human_owner_view_with_mismatched_title_still_flags_view_owner(self):
        label = 'Seamless Session Transitioning'
        row = {'task': {'ticketNumber': 'MUBO-102', 'projectId': 13734, 'section': 'Todo',
                        'labels': [{'name': label}], 'updatedAt': iso(NOW - 300),
                        'waitingOnUserId': 6},
               'comments': []}
        payload = {
            'rows': [row],
            'roster': f'{label} (live-s, claude, /tmp)\n',
            'chats': [label],
            'labels': [{'id': 'L-seamless', 'name': label}],
            'views': [{
                'id': 'v-personal',
                'title': "Valentin's Seamless View",
                'slug': 'seamless-session-transitioning',
                'owner': {'id': 6, 'displayName': 'Valentin Yeo'},
                'board_filters': {'addedFilters': [{'type': 'Labels',
                                                    'searchPayload': [{'id': 'L-seamless'}]}]},
            }],
        }
        code, out = self.run_payload(payload, board=13734, label=label,
                                     fail_rules=frozenset({'view-owner'}))
        self.assertEqual(code, 1, out)
        self.assertIn('rule-break: (view) view-owner:', out)
        self.assertIn('drain-check: FAIL (1 findings)', out)

    def test_the_chats_own_agent_under_another_name_is_no_break(self):
        # Real case: the agent "Multiprompt Android Dev" holds this chat's card.
        own = '7e61b4e1-c796-4dd9-a851-62bb1ff32341'
        task = {'ticketNumber': 'SOFT-2934', 'projectId': 2060, 'section': 'Todo',
                'labels': [{'name': 'Poteto'}], 'updatedAt': iso(NOW - 300),
                'assignees': [agent_assignee('Multiprompt Android Dev') | {'agentId': own}]}
        payload = self.payload([{'task': task, 'comments': []}, self.worker_card()],
                               own_agent_id=own, workers={'SOFT-2931': True})
        code, out = self.run_payload(payload, alive=True)
        self.assertEqual(code, 0, out)
        self.assertNotIn('rule-break:', out)

    def test_the_chats_own_agent_still_breaks_when_it_is_revoked(self):
        own = '7e61b4e1-c796-4dd9-a851-62bb1ff32341'
        task = {'ticketNumber': 'SOFT-2936', 'projectId': 2060, 'section': 'Todo',
                'labels': [{'name': 'Poteto'}], 'updatedAt': iso(NOW - 300),
                'assignees': [agent_assignee('Multiprompt Android Dev') | {'agentId': own}]}
        payload = self.payload([{'task': task, 'comments': []}, self.worker_card()],
                               own_agent_id=own, agents=[], workers={'SOFT-2931': True})
        code, out = self.run_payload(payload, alive=True)
        self.assertIn('rule-break: SOFT-2936 agent-assignee:', out)
        self.assertIn('revoked', out)

    def test_another_agent_on_the_same_name_mismatch_still_breaks(self):
        own = '7e61b4e1-c796-4dd9-a851-62bb1ff32341'
        task = {'ticketNumber': 'SOFT-2935', 'projectId': 2060, 'section': 'Todo',
                'labels': [{'name': 'Poteto'}], 'updatedAt': iso(NOW - 300),
                'assignees': [agent_assignee('Multiprompt Android Dev') | {'agentId': 'other-agent'}]}
        payload = self.payload([{'task': task, 'comments': []}, self.worker_card()],
                               own_agent_id=own, workers={'SOFT-2931': True})
        code, out = self.run_payload(payload, alive=True)
        self.assertIn('rule-break: SOFT-2935 agent-assignee:', out)
        self.assertIn('rule-break: SOFT-2935 label-assignee:', out)

    def test_a_revoked_agent_still_prints_and_names_who_can_fix_it(self):
        row = self.worker_card(assignees=[agent_assignee() | {'agentId': 'gone-agent'}])
        payload = self.payload([row], workers={'SOFT-2931': True}, agents=[])
        code, out = self.run_payload(payload, alive=True)
        self.assertEqual(code, 0, out)
        self.assertIn('rule-break: SOFT-2931 agent-assignee:', out)
        self.assertIn('revoked', out)
        self.assertIn('ask Valentin', out)
        self.assertIn('drain-check: PASS', out)

    def test_the_tick_reads_the_board_once_and_shares_its_pr_facts(self):
        task = self.worker_card()['task']
        saved = {'at': NOW - 60, 'probe_since': '2027-01-01T00:00:00Z', 'repos': [],
                 'tickets': {'SOFT-2931': {'at': NOW - 60, 'updated_at': task['updatedAt'],
                                           'pulls': [], 'facts': {}}}}
        board = drain.reconcile.BOARDS[2060]
        lint = drain.lint_module()
        gh_calls, board_reads = [], []

        def fake_run(*args, **kwargs):
            gh_calls.append(args)
            if 'graphql' in args:
                return json.dumps({'data': {'search': {'issueCount': 0, 'nodes': [],
                                                      'pageInfo': {'hasNextPage': False}}}})
            return json.dumps({'items': [], 'total_count': 0})

        def fake_tickets(**kwargs):
            board_reads.append(kwargs)
            return [task]

        out = io.StringIO()
        with patch.object(lint, 'reconcile', drain.reconcile), \
                patch.object(drain.reconcile, 'board_config', return_value=board), \
                patch.object(drain.reconcile, 'tickets', side_effect=fake_tickets), \
                patch.object(drain.reconcile, 'api', return_value={}), \
                patch.object(drain.reconcile, 'read_board_facts', return_value=saved), \
                patch.object(drain.reconcile, 'run', side_effect=fake_run), \
                patch.object(drain.reconcile, 'worker_alive', return_value=True), \
                patch.object(drain, 'probe_load', return_value=(0, ADD_LINE)), \
                patch.object(drain, 'probe_lane', return_value=None), \
                patch.object(lint, 'mp_session_names', return_value=set()), \
                patch.object(lint, 'published_names', return_value=set()), \
                patch.object(lint.owners, 'live_names', return_value=set()), \
                contextlib.redirect_stdout(out):
            code = drain.main(['--board', '2060', '--label', 'Poteto', '--now', iso(NOW)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(len(board_reads), 1, 'one board read per tick')
        self.assertEqual(len(gh_calls), 2, gh_calls)
        self.assertIn('search/issues', gh_calls[0])
        self.assertIn('graphql', gh_calls[1])
        self.assertNotIn('read failed', out.getvalue())


def write_tool(path, body):
    path.write_text(f'#!{sys.executable}\n' + body)
    path.chmod(0o755)


class HypertaskPathTest(unittest.TestCase):
    """A `hypertask` worker shim early on PATH must never win over the real CLI."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.home = self.directory / 'home'
        self.real_bin = self.home / '.local/bin'
        self.real_bin.mkdir(parents=True)
        self.shim_bin = self.directory / 'shim'
        self.shim_bin.mkdir()
        self.real_log = self.directory / 'real.log'
        self.shim_log = self.directory / 'shim.log'
        self.real_log.write_text('')
        write_tool(self.shim_bin / 'hypertask',
                   f'import pathlib, sys\n'
                   f'pathlib.Path({str(self.shim_log)!r}).write_text(" ".join(sys.argv[1:]))\n'
                   'sys.stderr.write("hypertask: no board login\\n")\n'
                   'raise SystemExit(3)\n')
        write_tool(self.real_bin / 'hypertask',
                   'import json, os, pathlib, sys\n'
                   'log = pathlib.Path(os.environ["REAL_HYPERTASK_LOG"])\n'
                   'log.write_text(log.read_text() + " ".join(sys.argv[1:]) + "\\n")\n'
                   'print(json.dumps({"tasks": [], "total": 0}))\n')

    def environment(self, **extra):
        """The shim first on PATH, the real CLI only in HOME/.local/bin."""
        return {'HOME': str(self.home), 'PATH': f'{self.shim_bin}:/usr/bin:/bin',
                'REAL_HYPERTASK_LOG': str(self.real_log),
                'BOARD_DRAIN_STATE_DIR': str(self.directory / 'state'),
                'RECONCILE_CACHE': str(self.directory / 'cache.json'),
                **extra}

    def run_script(self, name, *argv, **extra):
        return subprocess.run([sys.executable, str(SKILL / name), *argv], capture_output=True,
                              text=True, env=self.environment(**extra), timeout=60)

    def test_drain_check_reads_the_real_cli_not_the_shim(self):
        done = self.run_script('drain-check', '--board', '2060', '--label', 'Poteto',
                              '--now', iso(NOW))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('drain-check: PASS', done.stdout)
        self.assertFalse(self.shim_log.exists(), done.stdout + done.stderr)
        self.assertIn('task list', self.real_log.read_text())

    def test_sync_reads_the_real_cli_not_the_shim(self):
        done = self.run_script('sync', '--board', '2060', '--label', 'Poteto',
                               '--name', 'HT Test', HT_TOKEN='tok-from-env')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('sync: ok', done.stdout)
        self.assertFalse(self.shim_log.exists(), done.stdout + done.stderr)
        self.assertIn('task list', self.real_log.read_text())

    def test_both_scripts_fix_the_path_before_their_steps(self):
        for name, module in (('drain-check', 'board_drain_check_fresh'),
                             ('sync', 'board_drain_sync_fresh')):
            with self.subTest(script=name), \
                    patch.dict(os.environ, {'HOME': str(self.home),
                                            'PATH': f'{self.shim_bin}:/usr/bin:/bin'}):
                load(module, SKILL / name)
                path = os.environ['PATH'].split(os.pathsep)
                self.assertEqual(path[0], str(self.real_bin))
                self.assertEqual(path.count(str(self.real_bin)), 1)

    def test_the_real_bin_goes_first_and_only_once(self):
        before = f'{self.real_bin}{os.pathsep}/usr/bin'
        with patch.dict(os.environ, {'HOME': str(self.home), 'PATH': before}):
            loop.ensure_cli_path()
            self.assertEqual(os.environ['PATH'], before)
            loop.ensure_cli_path()
            self.assertEqual(os.environ['PATH'], before)

    def test_a_missing_real_bin_leaves_path_alone(self):
        with patch.dict(os.environ, {'HOME': str(self.directory / 'nowhere'),
                                    'PATH': '/usr/bin:/bin'}):
            loop.ensure_cli_path()
            self.assertEqual(os.environ['PATH'], '/usr/bin:/bin')


class LoopStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        env = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.directory)})
        env.start()
        self.addCleanup(env.stop)

    def test_arm_then_status_reads_armed(self):
        state = loop.arm('HT Test', every='15m', job='cron-1', now=NOW)
        self.assertEqual(set(state), {'name', 'every', 'armed_at', 'expires_at', 'job',
                                      'owner_pid', 'host'})
        self.assertEqual(state['expires_at'], iso(NOW + 7 * 86400))
        self.assertTrue((self.directory / 'ht-test.json').exists())
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_arm_records_the_board_and_label_it_drains(self):
        state = loop.arm('Vstack Maintainer', every='15m', job='cron-1', board=13556,
                         label='Vstack', now=NOW)
        self.assertEqual(state['board'], 13556)
        self.assertEqual(state['label'], 'Vstack')
        self.assertEqual(loop.status('Vstack Maintainer', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_a_file_without_a_board_and_label_still_reads(self):
        state = loop.arm('HT Test', now=NOW)
        self.assertNotIn('board', state)
        self.assertNotIn('label', state)
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_the_cli_records_the_board_and_label(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.directory))
        result = subprocess.run([sys.executable, str(SKILL / 'loop-state'), 'arm',
                                 '--name', 'Vstack Maintainer', '--every', '15m',
                                 '--job', 'cron-1', '--board', '13556', '--label', 'Vstack'],
                                capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads((self.directory / 'vstack-maintainer.json').read_text())
        self.assertEqual(state['board'], 13556)
        self.assertEqual(state['label'], 'Vstack')

    def test_expiry_within_a_day_asks_for_a_rearm(self):
        loop.arm('HT Test', expires=iso(NOW + 10 * 3600), now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW),
                         (3, 'expires soon (<24h): re-arm now'))

    def test_an_expired_loop_is_not_armed(self):
        loop.arm('HT Test', expires=iso(NOW - 60), now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_a_dead_owner_pid_is_not_armed(self):
        process = subprocess.Popen([sys.executable, '-c', 'pass'])
        process.wait()
        dead = process.pid
        state = loop.arm('HT Test', now=NOW)
        self.assertFalse(loop.reconcile.pid_alive(dead))
        state['owner_pid'] = dead
        loop.state_path('HT Test').write_text(json.dumps(state))
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_another_host_is_not_armed(self):
        state = loop.arm('HT Test', now=NOW)
        state['host'] = 'some-other-machine'
        loop.state_path('HT Test').write_text(json.dumps(state))
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_a_missing_file_is_not_armed(self):
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))
        loop.arm('HT Test', now=NOW)
        loop.clear('HT Test')
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_record_sync_creates_the_file_without_arming(self):
        record = loop.record_sync('HT Test', False, 'usage: no token', now=NOW)
        self.assertEqual(record, {'at': iso(NOW), 'ok': False, 'reason': 'usage: no token'})
        self.assertTrue((self.directory / 'ht-test.json').exists())
        self.assertEqual(loop.sync_state('HT Test'), record)
        # A sync record alone never arms the loop.
        self.assertEqual(loop.status('HT Test', now=NOW), (2, 'not armed'))

    def test_record_sync_keeps_the_armed_loop(self):
        loop.arm('HT Test', every='15m', job='cron-1', now=NOW)
        loop.record_sync('HT Test', True, '', now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))
        self.assertEqual(loop.sync_state('HT Test'), {'at': iso(NOW), 'ok': True, 'reason': ''})

    def test_a_skipped_sync_keeps_the_last_real_sync_time(self):
        loop.record_sync('HT Test', True, '', now=NOW)
        line = 'sync skipped: gh budget (wait until 14:20 UTC)'
        record = loop.record_sync('HT Test', True, line, now=NOW + 900, skipped=True)
        self.assertEqual(record['at'], iso(NOW), 'a skip does not refresh the clock')
        self.assertTrue(record['ok'], 'a skip is not a failure')
        self.assertEqual(record['skipped'], {'at': iso(NOW + 900), 'reason': line})

    def test_arm_keeps_last_sync_and_watch_fields(self):
        loop.record_sync('HT Test', True, 'ok', now=NOW)
        loop.record_watch('HT Test', os.getpid(), now=NOW)
        prior = loop.stored('HT Test')
        state = loop.arm('HT Test', every='6h', job='cron-1', board=13556,
                         label='Board Drain Loop', now=NOW)
        self.assertEqual(state['last_sync'], prior['last_sync'])
        self.assertEqual(state['watch_pid'], prior['watch_pid'])
        self.assertEqual(state['watch_started'], prior['watch_started'])

    def test_loop_interval_reads_plan_pick(self):
        with patch.object(loop, 'PLAN_PICK', SKILL / 'loop-state'), \
                patch.object(loop.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess(
                ['plan-pick', '--loop-interval'], 0, '14400 claude pace ahead', '')
            self.assertEqual(loop.loop_interval(), 14400)
        with patch.object(loop.subprocess, 'run', side_effect=OSError('missing')):
            self.assertEqual(loop.loop_interval(), loop.PACER_FLOOR)

    def test_a_dead_watcher_reads_watcher_dead(self):
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.record_watch('HT Test', dead_pid(), now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW),
                         (2, f'watcher dead since {iso(NOW)}'))

    def test_a_live_watcher_leaves_the_loop_armed(self):
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        state = loop.record_watch('HT Test', os.getpid(), now=NOW)
        self.assertEqual(state['watch_started'], iso(NOW))
        self.assertEqual(state['watch_beat'], iso(NOW))
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_an_exited_watcher_reads_dead_until_a_new_one_starts(self):
        """VSTA-151: the watcher exits, the chat never re-arms, and the loop read armed."""
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.record_watch('HT Test', os.getpid(), now=NOW)
        loop.clear_watch('HT Test')
        self.assertIsNone(loop.stored('HT Test')['watch_pid'])
        self.assertEqual(loop.status('HT Test', now=NOW + 60),
                         (2, f'watcher dead since {iso(NOW)}'))
        loop.record_watch('HT Test', os.getpid(), now=NOW + 120)
        self.assertEqual(loop.status('HT Test', now=NOW + 120)[0], 0)

    def test_a_hung_watcher_past_three_polls_reads_dead(self):
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.record_watch('HT Test', os.getpid(), now=NOW, every=180)
        self.assertEqual(loop.status('HT Test', now=NOW + 540)[0], 0)
        self.assertEqual(loop.status('HT Test', now=NOW + 541),
                         (2, f'watcher dead since {iso(NOW)}'))

    def test_a_live_watcher_without_beats_counts_as_alive_during_upgrade(self):
        """An old pre-upgrade watcher wrote watch_pid and watch_started, never watch_beat."""
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW)
        loop.store('HT Test', {'watch_pid': os.getpid(), 'watch_started': iso(NOW - 3600)})
        self.assertNotIn('watch_beat', loop.stored('HT Test'))
        self.assertEqual(loop.watch_health('HT Test', now=NOW), ('ok', 'watcher ok'))
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))
        loop.store('HT Test', {'watch_pid': dead_pid()})
        self.assertEqual(loop.watch_health('HT Test', now=NOW),
                         ('dead', f'watcher dead since {iso(NOW - 3600)}'))
        self.assertEqual(loop.status('HT Test', now=NOW),
                         (2, f'watcher dead since {iso(NOW - 3600)}'))

    def test_the_pulse_deadline_follows_the_poll_interval(self):
        self.assertEqual(loop.beat_limit({'watch_every': 60}), loop.BEAT_FLOOR)
        self.assertEqual(loop.beat_limit({'watch_every': 180}), 540)
        self.assertEqual(loop.beat_limit({}), 540)
        self.assertEqual(loop.beat_limit({'watch_every': 'broken'}), 540)

    def test_the_cli_watcher_verb_prints_one_line(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.directory))
        command = [sys.executable, str(SKILL / 'loop-state')]
        loop.arm('HT Test', every='15m', now=NOW)
        loop.record_watch('HT Test', os.getpid(), now=NOW, every=180)
        live = subprocess.run(command + ['watcher', '--name', 'HT Test'],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(live.returncode, 0, live.stderr)
        self.assertEqual(live.stdout.strip(), 'watcher ok')
        loop.record_watch('HT Test', dead_pid(), now=NOW - 3600, every=180)
        dead = subprocess.run(command + ['watcher', '--name', 'HT Test'],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(dead.returncode, 1, dead.stderr)
        self.assertEqual(dead.stdout.strip(), f'watcher dead since {iso(NOW - 3600)}')

    def test_an_old_watcher_cannot_clear_its_replacement(self):
        loop.arm('HT Test', now=NOW)
        loop.record_watch('HT Test', 101, now=NOW)
        replacement = loop.record_watch('HT Test', 202, now=NOW + 60)
        loop.clear_watch('HT Test', pid=101)
        self.assertEqual(loop.stored('HT Test'), replacement)
        loop.clear_watch('HT Test', pid=202)
        self.assertEqual(loop.stored('HT Test'), dict(replacement, watch_pid=None))

    def test_a_watcher_can_clear_its_own_pid(self):
        recorded = loop.record_watch('HT Test', 101, now=NOW)
        loop.clear_watch('HT Test', pid=101)
        self.assertEqual(loop.stored('HT Test'), dict(recorded, watch_pid=None))

    def test_no_watcher_recorded_behaves_as_today(self):
        loop.arm('HT Test', every='15m', job='cron-1', now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))
        loop.record_sync('HT Test', True, '', now=NOW)
        self.assertEqual(loop.status('HT Test', now=NOW), (0, 'armed, expires in 7d0h'))

    def test_a_file_with_no_sync_record_reads_none(self):
        loop.arm('HT Test', now=NOW)
        self.assertIsNone(loop.sync_state('HT Test'))
        self.assertIsNone(loop.sync_state('HT Never Armed'))

    def test_the_cli_exits_with_the_status_code(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.directory))
        command = [sys.executable, str(SKILL / 'loop-state')]
        armed = subprocess.run(command + ['arm', '--name', 'HT Test', '--every', '15m'],
                               capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(armed.returncode, 0, armed.stderr)
        self.assertIn('armed, expires in 7d0h', armed.stdout)
        status = subprocess.run(command + ['status', '--name', 'HT Test'],
                                capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertRegex(status.stdout, r'armed, expires in \d+d\d+h')
        cleared = subprocess.run(command + ['clear', '--name', 'HT Test'],
                                 capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        missing = subprocess.run(command + ['status', '--name', 'HT Test'],
                                 capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertEqual(missing.stdout.strip(), 'not armed')

    def test_dead_notice_records_once_per_dead_spell_and_clears_on_recovery(self):
        """VSTA-151 round 2: loop-state tracks dead_since, dead_notice, notice and beat CLI."""
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.directory))
        command = [sys.executable, str(SKILL / 'loop-state')]
        loop.arm('HT Test', every='6h', job='cron-1', now=NOW, board=13556, label='HT Test')
        loop.record_watch('HT Test', os.getpid(), now=NOW, every=180)
        self.assertEqual(loop.dead_since('HT Test', now=NOW), (None, ''))
        self.assertEqual(loop.notice_status('HT Test', now=NOW), ('none', 'no notice'))

        # `loop-state beat` refreshes watch_beat in the same record without a second mechanism.
        beat_run = subprocess.run(command + ['beat', '--name', 'HT Test'],
                                  capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(beat_run.returncode, 0, beat_run.stderr)
        self.assertIn('beat ', beat_run.stdout)

        # Watcher dies at NOW; 11 minutes later it is dead and notice is pending.
        loop.record_watch('HT Test', dead_pid(), now=NOW, every=180)
        self.assertEqual(loop.dead_since('HT Test', now=NOW + 660), (NOW, iso(NOW)))
        self.assertEqual(loop.notice_status('HT Test', now=NOW + 660), ('pending', 'notice not sent'))
        pending = subprocess.run(command + ['notice', '--name', 'HT Test'],
                                 capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(pending.returncode, 1, pending.stderr)
        self.assertEqual(pending.stdout.strip(), 'notice not sent')

        # Recording the notice marks this dead spell sent.
        loop.record_dead_notice('HT Test', iso(NOW), 'ntfy', now=NOW + 660)
        self.assertTrue(loop.notice_sent_for(loop.stored('HT Test'), iso(NOW)))
        self.assertFalse(loop.notice_sent_for(loop.stored('HT Test'), iso(NOW + 120)))
        self.assertEqual(loop.notice_status('HT Test', now=NOW + 700),
                         ('sent', f'notice sent {iso(NOW + 660)} (ntfy)'))
        sent = subprocess.run(command + ['notice', '--name', 'HT Test'],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(sent.stdout.strip(), f'notice sent {iso(NOW + 660)} (ntfy)')

        # Starting a fresh watcher clears dead_notice for the next dead spell.
        loop.record_watch('HT Test', os.getpid(), now=NOW + 800, every=180)
        self.assertNotIn('dead_notice', loop.stored('HT Test'))
        self.assertEqual(loop.notice_status('HT Test', now=NOW + 800), ('none', 'no notice'))


class WatchTest(unittest.TestCase):
    """The watcher wakes its own chat on changes and keeps polling when delivery works."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fixture = self.directory / 'view.json'
        self.sender = self.directory / 'bin/mp-send'
        self.sender.parent.mkdir()
        self.wakes = self.directory / 'wakes.jsonl'
        self.sender.write_text(
            f'#!{sys.executable}\nimport json, pathlib, sys\n'
            f'with pathlib.Path({str(self.wakes)!r}).open("a") as log:\n'
            '    log.write(json.dumps(sys.argv[1:]) + "\\n")\n')
        self.sender.chmod(0o755)
        configs = self.directory / '.local/state/multiprompt/agent-host'
        configs.mkdir(parents=True)
        (configs / 'other.config.json').write_text(json.dumps({'tmux': 'other-tab', 'sid': 'other-sid'}))
        (configs / 'own.config.json').write_text(json.dumps({'tmux': 'own-tab', 'sid': 'own-sid'}))
        env = patch.dict(os.environ, {
            'HOME': str(self.directory), 'MULTIPROMPT_TAB': 'own-tab', 'TMUX': '',
            'PATH': str(self.sender.parent),
            'BOARD_DRAIN_STATE_DIR': str(self.directory / 'state')})
        env.start()
        self.addCleanup(env.stop)

    def rows(self, rows):
        self.fixture.write_text(json.dumps(rows))

    def run_watch(self, rows, *extra, on_sleep=None, clock=None):
        self.rows(rows)
        clock = clock or Clock()
        clock.on_sleep = on_sleep
        cycles = () if ('--cycles' in extra or '--once' in extra) else ('--cycles', '1')
        argv = ['--board', '13556', '--label', 'Board Drain Loop', '--name', 'Watch Test',
                '--fixture', str(self.fixture), '--no-sync', *cycles, *extra]
        out, err = io.StringIO(), io.StringIO()
        with patch.object(watch.drain.reconcile, 'worker_alive', return_value=False), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = watch.main(argv, clock=clock.time, sleep=clock.sleep)
        return code, out.getvalue() + err.getvalue(), clock

    def test_a_beat_that_lands_inside_the_read_keeps_the_helper_alive(self):
        # VSTA-257: the watcher holds one `now` for a whole read, and a slow read (a
        # 20-55s GitHub probe plus the board pages) outlasts a 60s lease beat, so the
        # newest beat sits after `now`. Both reads must still see the live helper, or
        # the watcher prints "orphan PR" on one poll and "cleared" on the next.
        row = vsta('VSTA-1', section='AI Review', age=7200)
        self.rows({'rows': [row], 'pulls': {'VSTA-1': [PR_524]}})
        args = argparse.Namespace(board=13556, label='Board Drain Loop',
                                  fixture=str(self.fixture))
        with tempfile.TemporaryDirectory() as leases, \
                patch.object(watch.drain.reconcile, 'LEASES', Path(leases)), \
                patch.object(watch.drain.reconcile, 'process_tickets', return_value=set()):
            # Each read starts a poll apart, and the helper's next beat lands after
            # that read's own `now` because the read itself ran long.
            for read_began, newest_beat in ((NOW, NOW + 30), (NOW + 180, NOW + 210)):
                self.write_lease(Path(leases), 'VSTA-1',
                                 started=NOW - 600, last_beat=newest_beat)
                snapshot = watch.snapshot(args, read_began)
                self.assertNotIn('orphan PR', snapshot['findings'])

    def test_a_lease_that_stopped_beating_is_still_no_helper(self):
        # The window still has to bite: a beat 15 minutes old is no live helper.
        row = vsta('VSTA-1', section='AI Review', age=7200)
        self.rows({'rows': [row], 'pulls': {'VSTA-1': [PR_524]}})
        args = argparse.Namespace(board=13556, label='Board Drain Loop',
                                  fixture=str(self.fixture))
        with tempfile.TemporaryDirectory() as leases, \
                patch.object(watch.drain.reconcile, 'LEASES', Path(leases)), \
                patch.object(watch.drain.reconcile, 'process_tickets', return_value=set()):
            self.write_lease(Path(leases), 'VSTA-1', started=NOW - 2000, last_beat=NOW - 901)
            self.assertIn('orphan PR', watch.snapshot(args, NOW)['findings'])

    @staticmethod
    def write_lease(directory, key, **record):
        """This host's live PID on a lease record, as `lease run --` writes one."""
        lease = dict(pid=os.getpid(), host=socket.gethostname(), started=NOW, last_beat=NOW)
        lease.update(record)
        (directory / f'{key}.json').write_text(json.dumps(lease))

    def test_once_prints_the_snapshot_and_exits(self):
        rows = [vsta('VSTA-1', section='Doing', age=300), vsta('VSTA-2')]
        rows[1]['task']['waitingOnUserId'] = 6
        rows[1]['comments'] = [dict(human_comment(600), id=12)]
        code, out, _ = self.run_watch(rows, '--once')
        self.assertEqual(code, 0, out)
        snapshot = json.loads(out)
        self.assertEqual(snapshot['tickets']['VSTA-1']['column'], 'Doing')
        self.assertTrue(snapshot['tickets']['VSTA-1']['stalled'] is False)
        self.assertEqual(snapshot['tickets']['VSTA-2']['waiting'], [6, None])
        self.assertEqual(snapshot['tickets']['VSTA-2']['newest_comment'], 12)
        # The finding kinds are drain-check's own: no second verdict lived here.
        self.assertEqual(snapshot['findings'], ['answered', 'unassigned'])

    def test_a_new_ticket_wakes_the_chat(self):
        code, out, _ = self.run_watch(
            [vsta('VSTA-1', section='Doing', age=300)],
            on_sleep=lambda tick: tick >= 1 and self.rows(
                [vsta('VSTA-1', section='Doing', age=300), vsta('VSTA-80')]))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-80 new in Todo', out)

    def test_a_change_sends_one_own_tab_wake_and_keeps_polling(self):
        def on_sleep(tick):
            if tick == 1:
                self.rows([vsta('VSTA-80')])
            elif tick == 2:
                self.assertTrue(self.wakes.exists(), 'change must wake the chat before the job exits')
                wakes = [json.loads(line) for line in self.wakes.read_text().splitlines()]
                self.assertEqual(len(wakes), 1)
                self.assertEqual(wakes[0][:4], ['--tmux', 'own-tab', 'claude', 'own-sid'])
                self.assertIn('changed: VSTA-80 new in Todo', wakes[0][4])
                self.assertIn('run drain-check', wakes[0][4])

        code, out, clock = self.run_watch([], '--every', '10', '--heartbeat', '100',
                                           '--cycles', '2', on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        self.assertGreater(clock.now - NOW, 10, 'must keep polling after the change')

    def test_shell_sender_first_on_path_wakes_the_own_chat(self):
        wrapper = self.directory / 'shell-bin/mp-send'
        wrapper.parent.mkdir()
        wrapper.write_text('#!/bin/sh\nexec "$HOME/bin/mp-send" "$@"\n')
        wrapper.chmod(0o755)
        out = io.StringIO()
        with patch.dict(os.environ, {'PATH': f'{wrapper.parent}{os.pathsep}{self.sender.parent}'}), \
                patch.object(watch.time, 'sleep'), contextlib.redirect_stdout(out):
            self.assertTrue(watch.wake(['changed: VSTA-80 new in Todo']), out.getvalue())
        self.assertEqual(out.getvalue(), '')
        wakes = [json.loads(line) for line in self.wakes.read_text().splitlines()]
        self.assertEqual(wakes, [['--tmux', 'own-tab', 'claude', 'own-sid',
                                 'changed: VSTA-80 new in Todo; run drain-check']])

    def test_missing_sender_prints_change_and_exits_zero(self):
        self.sender.unlink()
        code, out, clock = self.run_watch(
            [], '--every', '10', '--heartbeat', '100', '--cycles', '0',
            on_sleep=lambda tick: self.rows([vsta('VSTA-80')]) if tick == 1 else self.fail(
                'missing own-tab wake must exit so the harness wakes the chat'))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-80 new in Todo', out)
        self.assertEqual(clock.now - NOW, 10)
        self.assertFalse(self.wakes.exists())

    def test_failed_sender_logs_last_stderr_line_and_falls_back_to_exit(self):
        self.sender.write_text(self.sender.read_text() +
                               'print("sender diagnostic\\nchat busy", file=sys.stderr)\n'
                               'sys.exit(7)\n')
        with patch.object(watch.time, 'sleep') as retry_sleep:
            code, out, _ = self.run_watch(
                [], '--every', '10', '--cycles', '0',
                on_sleep=lambda tick: self.rows([vsta('VSTA-80')]) if tick == 1 else self.fail(
                    'failed delivery must exit'))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-80 new in Todo', out)
        self.assertEqual(out.count('wake: failed (7): chat busy\n'), 2)
        self.assertNotIn('sender diagnostic', out)
        self.assertEqual(len(self.wakes.read_text().splitlines()), 2)
        retry_sleep.assert_called_once_with(5)

    def test_sender_failing_once_then_succeeding_keeps_polling(self):
        self.sender.write_text(self.sender.read_text() +
                               f'if len(pathlib.Path({str(self.wakes)!r}).read_text().splitlines()) == 1:\n'
                               '    print("chat busy", file=sys.stderr)\n'
                               '    sys.exit(1)\n')

        def on_sleep(tick):
            if tick == 1:
                self.rows([vsta('VSTA-80')])
            elif tick == 2:
                self.assertEqual(len(self.wakes.read_text().splitlines()), 2)
                self.assertEqual(watch.loop_state.stored('Watch Test')['watch_pid'], os.getpid())

        with patch.object(watch.time, 'sleep') as retry_sleep:
            code, out, clock = self.run_watch([], '--every', '10', '--heartbeat', '100',
                                               '--cycles', '2', on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count('wake: failed (1): chat busy\n'), 1)
        self.assertIn('heartbeat: no change', out)
        self.assertGreater(clock.now - NOW, 10, 'must keep polling after retry succeeds')
        retry_sleep.assert_called_once_with(5)

    def test_sender_timeout_logs_partial_stderr_and_falls_back_to_exit(self):
        self.sender.write_text(self.sender.read_text() +
                               'import time\n'
                               'print("sender diagnostic\\nstill busy", file=sys.stderr, flush=True)\n'
                               'time.sleep(60)\n')
        run = subprocess.run

        def short_timeout(*args, **kwargs):
            self.assertEqual(kwargs['timeout'], 30)
            kwargs['timeout'] = 0.2
            return run(*args, **kwargs)

        with patch.object(watch.subprocess, 'run', side_effect=short_timeout), \
                patch.object(watch.time, 'sleep') as retry_sleep:
            code, out, _ = self.run_watch(
                [], '--every', '10', '--cycles', '0',
                on_sleep=lambda tick: self.rows([vsta('VSTA-80')]) if tick == 1 else self.fail(
                    'timed out delivery must exit'))
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count('wake: failed (timeout): still busy\n'), 2)
        self.assertNotIn('sender diagnostic', out)
        self.assertEqual(len(self.wakes.read_text().splitlines()), 2)
        retry_sleep.assert_called_once_with(5)

    def test_sender_timeout_without_stderr_falls_back_to_exit(self):
        self.sender.write_text(self.sender.read_text() + 'import time\ntime.sleep(60)\n')
        run = subprocess.run

        def short_timeout(*args, **kwargs):
            kwargs['timeout'] = 0.2
            return run(*args, **kwargs)

        with patch.object(watch.subprocess, 'run', side_effect=short_timeout), \
                patch.object(watch.time, 'sleep') as retry_sleep:
            code, out, _ = self.run_watch(
                [], '--every', '10', '--cycles', '0',
                on_sleep=lambda tick: self.rows([vsta('VSTA-80')]) if tick == 1 else self.fail(
                    'timed out delivery must exit'))
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count('wake: failed (timeout): \n'), 2)
        self.assertEqual(len(self.wakes.read_text().splitlines()), 2)
        retry_sleep.assert_called_once_with(5)

    def test_enabled_own_config_wins_over_an_earlier_disabled_match(self):
        configs = self.directory / '.local/state/multiprompt/agent-host'
        (configs / 'a-disabled.config.json').write_text(json.dumps(
            {'tmux': 'own-tab', 'sid': 'stale-sid', 'enabled': False}))
        (configs / 'z-enabled.config.json').write_text(json.dumps(
            {'tmux': 'own-tab', 'sid': 'active-sid', 'enabled': True}))
        code, out, _ = self.run_watch(
            [], on_sleep=lambda tick: self.rows([vsta('VSTA-80')]))
        self.assertEqual(code, 0, out)
        wakes = [json.loads(line) for line in self.wakes.read_text().splitlines()]
        self.assertEqual(wakes[0][:4], ['--tmux', 'own-tab', 'claude', 'active-sid'])

    def test_first_matching_config_is_used_when_none_is_enabled(self):
        configs = self.directory / '.local/state/multiprompt/agent-host'
        (configs / 'a-disabled.config.json').write_text(json.dumps(
            {'tmux': 'own-tab', 'sid': 'first-sid', 'enabled': False}))
        code, out, _ = self.run_watch(
            [], on_sleep=lambda tick: self.rows([vsta('VSTA-80')]))
        self.assertEqual(code, 0, out)
        wakes = [json.loads(line) for line in self.wakes.read_text().splitlines()]
        self.assertEqual(wakes[0][:4], ['--tmux', 'own-tab', 'claude', 'first-sid'])

    def test_no_own_tab_never_targets_another_sid(self):
        with patch.dict(os.environ, {'MULTIPROMPT_TAB': '', 'TMUX': ''}):
            code, out, _ = self.run_watch(
                [], '--every', '10', '--cycles', '0',
                on_sleep=lambda tick: self.rows([vsta('VSTA-80')]) if tick == 1 else self.fail(
                    'no own tab must exit'))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-80 new in Todo', out)
        self.assertFalse(self.wakes.exists())

    def test_no_matching_own_sid_falls_back_without_messaging_another_chat(self):
        configs = self.directory / '.local/state/multiprompt/agent-host'
        (configs / 'own.config.json').write_text('{broken')
        code, out, _ = self.run_watch(
            [], '--every', '10', '--cycles', '0',
            on_sleep=lambda tick: self.rows([vsta('VSTA-80')]) if tick == 1 else self.fail(
                'missing own sid must exit'))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-80 new in Todo', out)
        self.assertFalse(self.wakes.exists())

    def test_tmux_session_resolves_the_own_tab_when_environment_tab_is_absent(self):
        tmux = self.sender.parent / 'tmux'
        tmux.write_text(f'#!{sys.executable}\nprint("own-tab")\n')
        tmux.chmod(0o755)
        with patch.dict(os.environ, {'MULTIPROMPT_TAB': '', 'TMUX': 'fake-socket'}):
            code, out, _ = self.run_watch(
                [], '--every', '10', on_sleep=lambda tick: self.rows([vsta('VSTA-80')]))
        self.assertEqual(code, 0, out)
        wakes = [json.loads(line) for line in self.wakes.read_text().splitlines()]
        self.assertEqual(wakes[0][:4], ['--tmux', 'own-tab', 'claude', 'own-sid'])

    def test_two_changes_within_sixty_seconds_send_one_wake_then_coalesce(self):
        def on_sleep(tick):
            if tick == 1:
                self.rows([vsta('VSTA-80')])
            elif tick == 2:
                self.rows([vsta('VSTA-80'), vsta('VSTA-81')])
            elif tick == 3:
                self.rows([vsta('VSTA-80'), vsta('VSTA-81'), vsta('VSTA-82')])
            elif tick == 6:
                self.assertTrue(self.wakes.exists(), 'first change must send a wake')
                self.assertEqual(len(self.wakes.read_text().splitlines()), 1)
            elif tick == 8:
                wakes = [json.loads(line) for line in self.wakes.read_text().splitlines()]
                self.assertEqual(len(wakes), 2, 'pending changes must wake at the rate-limit deadline')
                self.assertIn('VSTA-81', wakes[1][4])
                self.assertIn('VSTA-82', wakes[1][4])

        code, out, _ = self.run_watch([], '--every', '10', '--heartbeat', '100',
                                       '--cycles', '4', on_sleep=on_sleep)
        self.assertEqual(code, 0, out)

    def test_a_valentin_reply_on_a_waiting_ticket_wakes_the_chat(self):
        first = [dict(agent_comment(3600), id=11)]
        both = first + [dict(human_comment(600), id=12)]
        rows = [vsta('VSTA-12')]
        rows[0]['task']['waitingOnUserId'] = 6
        rows[0]['comments'] = first
        code, out, _ = self.run_watch(
            rows, on_sleep=lambda tick: tick >= 1 and self._mark_waiting(rows, both))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-12 Valentin replied', out)

    def test_a_dead_worker_wakes_the_chat(self):
        code, out, _ = self.run_watch(
            [vsta('VSTA-9', section='Doing', age=300),
             vsta('VSTA-1', section='Done')],
            on_sleep=lambda tick: tick >= 1 and self.rows(
                [vsta('VSTA-9', section='Doing', age=3 * 3600),
                 vsta('VSTA-1', section='Done')]))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-9 worker died', out)

    def test_a_column_move_wakes_the_chat(self):
        code, out, _ = self.run_watch(
            [vsta('VSTA-5', section='Doing', age=300)],
            on_sleep=lambda tick: tick >= 1 and self.rows(
                [vsta('VSTA-5', section='Done')]))
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-5 Doing -> Done', out)

    def test_a_quiet_view_exits_on_the_heartbeat_before_the_harness_limit(self):
        with patch.object(watch.loop_state, 'loop_interval', return_value=loop.PACER_FLOOR):
            code, out, clock = self.run_watch([vsta('VSTA-1', section='Done')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), 'heartbeat: no change in 2h')
        self.assertEqual(clock.now - NOW, 7020)
        self.assertLess(clock.now - NOW, 7200)

    def test_a_quiet_watcher_exits_before_the_job_limit(self):
        """VSTA-239: the harness kills a 2h job, so the watcher leaves first and asks to restart."""
        with patch.object(watch.loop_state, 'loop_interval', return_value=loop.PACER_FLOOR):
            code, out, clock = self.run_watch([vsta('VSTA-1', section='Done')], '--cycles', '0')
        self.assertEqual(code, 0, out)
        self.assertIn('lifetime: exiting before the 2h job limit; restart me', out)
        self.assertLess(clock.now - NOW, watch.LIMIT)

    def test_a_watcher_never_runs_past_the_job_limit(self):
        """A heartbeat set beyond the limit still ends at the lifetime line, not the kill."""
        code, out, clock = self.run_watch([vsta('VSTA-1', section='Done')], '--cycles', '0',
                                          '--heartbeat', str(watch.LIMIT))
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), 'lifetime: exiting before the 2h job limit; restart me')
        self.assertLess(clock.now - NOW, watch.LIMIT)

    def test_the_default_heartbeat_follows_the_plan_pacer(self):
        """A 1h plan pace caps under 2h and sets the heartbeat one poll short of it."""
        paced = 3600 - 180
        with patch.object(watch.loop_state, 'loop_interval', return_value=3600):
            code, out, clock = self.run_watch([vsta('VSTA-1', section='Done')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), 'heartbeat: no change in 57m')
        self.assertEqual(clock.now - NOW, paced)

    def test_an_explicit_heartbeat_is_honoured(self):
        code, out, clock = self.run_watch([vsta('VSTA-1', section='Done')],
                                          '--heartbeat', '600')
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), 'heartbeat: no change in 10m')
        self.assertEqual(clock.now - NOW, 600)

    def test_one_api_failure_retries_on_the_next_poll(self):
        def on_sleep(tick):
            if tick == 1:
                self.fixture.write_text('{not json')
            elif tick == 2:
                self.rows([vsta('VSTA-80')])

        code, out, _ = self.run_watch([vsta('VSTA-1', section='Done')], on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        self.assertNotIn('FAIL', out)
        self.assertIn('changed: VSTA-80 new in Todo', out)

    def test_three_api_failures_in_a_row_exit_one(self):
        self.fixture.write_text('{not json')
        clock = Clock()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = watch.main(
                ['--board', '13556', '--label', 'Board Drain Loop', '--name', 'Watch Test',
                 '--fixture', str(self.fixture), '--no-sync'],
                clock=clock.time, sleep=clock.sleep)
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn('watch: FAIL', out.getvalue())
        self.assertEqual(clock.now - NOW, 2 * 180)  # three attempts, two waits between

    def test_the_watcher_records_and_clears_its_pid(self):
        seen = []

        def on_sleep(tick):
            state = json.loads((self.directory / 'state/watch-test.json').read_text())
            seen.append((state.get('watch_pid'), state.get('watch_started')))

        code, out, _ = self.run_watch([vsta('VSTA-1', section='Done')], on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        self.assertEqual(seen[0], (os.getpid(), iso(NOW)))
        state = json.loads((self.directory / 'state/watch-test.json').read_text())
        self.assertIsNone(state.get('watch_pid'))

    def test_the_watcher_leaves_a_replacement_pid_on_exit(self):
        replacement_pid = os.getpid() + 1

        def on_sleep(tick):
            watch.loop_state.record_watch('Watch Test', replacement_pid, now=NOW + 180)

        code, out, _ = self.run_watch([vsta('VSTA-1', section='Done')],
                                      '--heartbeat', '180', on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        state = json.loads((self.directory / 'state/watch-test.json').read_text())
        self.assertEqual(state['watch_pid'], replacement_pid)
        self.assertEqual(state['watch_started'], iso(NOW + 180))

    def test_the_watcher_pulses_on_every_poll(self):
        """VSTA-151: the pulse is the marker a dead watcher leaves behind."""
        beats = []

        def on_sleep(tick):
            state = json.loads((self.directory / 'state/watch-test.json').read_text())
            beats.append(state.get('watch_beat'))

        with patch.object(watch.loop_state, 'loop_interval', return_value=loop.PACER_FLOOR):
            code, out, _ = self.run_watch([vsta('VSTA-1', section='Done')], on_sleep=on_sleep)
        self.assertEqual(code, 0, out)
        self.assertEqual(beats[:3], [iso(NOW), iso(NOW + 180), iso(NOW + 360)])
        state = json.loads((self.directory / 'state/watch-test.json').read_text())
        self.assertEqual(state['watch_every'], 180)
        self.assertEqual(state['watch_beat'], iso(NOW + 7020))
        self.assertIsNone(state.get('watch_pid'))
        self.assertEqual(loop.watch_health('Watch Test', now=NOW + 7020),
                         ('dead', f'watcher dead since {iso(NOW + 7020)}'))

    def test_the_cli_records_the_watcher_pid(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.directory / 'state'))
        done = subprocess.run([sys.executable, str(SKILL / 'loop-state'), 'watch',
                               '--name', 'Watch Test', '--pid', str(os.getpid())],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        state = json.loads((self.directory / 'state/watch-test.json').read_text())
        self.assertEqual(state['watch_pid'], os.getpid())

    def test_watch_survives_view_changes_and_heartbeats_by_default(self):
        """VSTA-151 round 2: watch keeps polling after changes and heartbeats instead of exiting."""
        self.rows([vsta('VSTA-1', section='Doing', age=300)])
        clock = Clock()
        seen_pids = []

        class StopTest(BaseException):
            pass

        def on_sleep(tick):
            state = json.loads((self.directory / 'state/watch-test.json').read_text())
            seen_pids.append((tick, state.get('watch_pid'), state.get('watch_beat')))
            if tick == 1:
                self.rows([vsta('VSTA-1', section='Doing', age=300), vsta('VSTA-80')])
            elif tick == 2:
                self.rows([vsta('VSTA-1', section='Done'), vsta('VSTA-80')])
            elif tick == 5:
                raise StopTest()

        clock.on_sleep = on_sleep
        argv = ['--board', '13556', '--label', 'Board Drain Loop', '--name', 'Watch Test',
                '--fixture', str(self.fixture), '--no-sync', '--every', '180', '--heartbeat', '360']
        out = io.StringIO()
        with patch.object(watch.drain.reconcile, 'worker_alive', return_value=False), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(StopTest):
                watch.main(argv, clock=clock.time, sleep=clock.sleep)
        output = out.getvalue()
        self.assertIn('changed: VSTA-80 new in Todo', output)
        self.assertIn('changed: VSTA-1 Doing -> Done', output)
        self.assertIn('heartbeat: no change in 6m', output)
        self.assertEqual(len(seen_pids), 5)
        self.assertTrue(all(pid == os.getpid() for _, pid, _ in seen_pids), seen_pids)

    def test_killed_real_watcher_subprocess_survives_change_then_reads_dead(self):
        """VSTA-151 round 2: a real watch process survives a view change and only dies when killed."""
        import time as real_time

        state_dir = self.directory / 'state'
        self.rows([vsta('VSTA-1', section='Doing', age=300)])
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(state_dir))
        proc = subprocess.Popen(
            [sys.executable, str(SKILL / 'watch'), '--board', '13556',
             '--label', 'Board Drain Loop', '--name', 'Watch Test',
             '--fixture', str(self.fixture), '--no-sync', '--every', '1', '--heartbeat', '60'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        try:
            state_file = state_dir / 'watch-test.json'
            deadline = real_time.monotonic() + 10
            while real_time.monotonic() < deadline and not state_file.exists():
                real_time.sleep(0.1)
            self.assertTrue(state_file.exists(), 'watcher did not record state')
            # Trigger a view change and confirm the watcher reports it AND stays alive.
            self.rows([vsta('VSTA-1', section='Doing', age=300), vsta('VSTA-80')])
            line = proc.stdout.readline()
            self.assertIn('changed: VSTA-80 new in Todo', line)
            real_time.sleep(0.3)
            self.assertIsNone(proc.poll(), 'watcher exited on view change instead of self-restarting')
            state = json.loads(state_file.read_text())
            self.assertEqual(state['watch_pid'], proc.pid)
        finally:
            proc.kill()
            proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()
        self.assertEqual(loop.watch_health('Watch Test')[0], 'dead')
        self.assertIn('watcher dead since ', loop.watch_health('Watch Test')[1])

    def _mark_waiting(self, rows, comments):
        rows[0]['comments'] = comments
        self.rows(rows)


class WatchSyncTest(unittest.TestCase):
    """The watcher runs the chat's own sync, so a merged PR's card still moves."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fixture = self.directory / 'view.json'
        self.rows([vsta('VSTA-1', section='Done')])
        env = patch.dict(os.environ, {'HOME': str(self.directory), 'MULTIPROMPT_TAB': '',
                                     'TMUX': '', 'PATH': str(self.directory),
                                     'BOARD_DRAIN_STATE_DIR': str(self.directory / 'state')})
        env.start()
        self.addCleanup(env.stop)

    def rows(self, rows):
        self.fixture.write_text(json.dumps(rows))

    def run_watch(self, *extra, syncs=None, on_sync=None):
        """syncs: one (exit code, reason) per sync call, in order; extra calls succeed."""
        queue, calls, clock = list(syncs or []), [], Clock()

        def fake_sync(argv):
            calls.append({'argv': list(argv), 'at': clock.now - NOW})
            code, reason = queue.pop(0) if queue else (0, '')
            if code == 'skip':
                # A tick skipped over the gh budget: not failed, not fresh either.
                loop.record_sync('Watch Test', True, reason, now=clock.now, skipped=True)
                if on_sync:
                    on_sync(clock.now - NOW)
                return 0
            loop.record_sync('Watch Test', not code, reason, now=clock.now)
            if on_sync:
                on_sync(clock.now - NOW)
            return code

        out = io.StringIO()
        with patch.object(watch.loop_state, 'arm_timer'), \
                patch.object(watch.sync, 'main', side_effect=fake_sync), \
                patch.object(watch.drain.reconcile, 'worker_alive', return_value=False), \
                contextlib.redirect_stdout(out):
            cycles = () if ('--cycles' in extra or '--once' in extra) else ('--cycles', '1')
            code = watch.main(['--board', '13556', '--label', 'Board Drain Loop',
                               '--name', 'Watch Test', '--fixture', str(self.fixture),
                               *cycles, *extra],
                              clock=clock.time, sleep=clock.sleep)
        return code, out.getvalue(), calls

    def test_the_watcher_calls_the_sync_scripts_own_code(self):
        self.assertEqual(Path(watch.sync.__file__).resolve(), (SKILL / 'sync').resolve())

    def test_the_sync_runs_at_start_and_every_sync_every_seconds(self):
        code, out, calls = self.run_watch('--every', '60', '--heartbeat', '240',
                                          '--sync-every', '120')
        self.assertEqual(code, 0, out)
        self.assertEqual([call['at'] for call in calls], [0, 120, 240])

    def test_the_default_sync_runs_every_fifteen_minutes(self):
        code, out, calls = self.run_watch('--every', '60', '--heartbeat', '1800')
        self.assertEqual(code, 0, out)
        self.assertEqual([call['at'] for call in calls], [0, 900, 1800])

    def test_no_sync_never_runs_it(self):
        code, out, calls = self.run_watch('--every', '60', '--heartbeat', '240', '--no-sync')
        self.assertEqual(code, 0, out)
        self.assertEqual(calls, [])

    def test_once_never_syncs(self):
        code, out, calls = self.run_watch('--once')
        self.assertEqual(code, 0, out)
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(out)['tickets']['VSTA-1']['column'], 'Done')

    def test_the_sync_runs_as_this_chat(self):
        _code, out, calls = self.run_watch('--every', '60', '--heartbeat', '60',
                                           '--sync-every', '600')
        self.assertEqual(calls[0]['argv'], ['--board', '13556', '--label', 'Board Drain Loop',
                                            '--name', 'Watch Test'], out)

    def test_a_failed_sync_wakes_the_chat_at_once(self):
        code, out, calls = self.run_watch(
            '--every', '60', '--heartbeat', '600',
            syncs=[(1, 'board 13556 unreachable')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), 'changed: sync failed: board 13556 unreachable')
        self.assertEqual(len(calls), 1, out)

    def test_a_sync_that_moved_a_card_wakes_the_chat_on_the_next_snapshot(self):
        def move(tick):
            if tick:
                self.rows([vsta('VSTA-1', section='Done'), vsta('VSTA-80')])

        code, out, calls = self.run_watch('--every', '60', '--heartbeat', '600',
                                          '--sync-every', '120', on_sync=move)
        self.assertEqual(code, 0, out)
        self.assertIn('changed: VSTA-80 new in Todo', out)
        self.assertEqual([call['at'] for call in calls], [0, 120])

    def test_a_failed_sync_records_the_failure_for_drain_check(self):
        _code, _out, _calls = self.run_watch('--every', '60', '--heartbeat', '600',
                                             syncs=[(1, 'preview printed: usage')])
        record = loop.sync_state('Watch Test')
        self.assertFalse(record['ok'])
        self.assertEqual(record['reason'], 'preview printed: usage')

    def test_a_budget_skip_keeps_the_watcher_watching(self):
        line = 'sync skipped: gh budget (wait until 14:20 UTC)'
        code, out, calls = self.run_watch('--every', '60', '--heartbeat', '1000',
                                          '--sync-every', '300', syncs=[('skip', line)])
        self.assertEqual(code, 0, out)
        self.assertEqual([call['at'] for call in calls], [0, 300, 600, 900],
                         'the watcher never stops on a skip')
        self.assertIn(line, out)
        self.assertNotIn('sync failed', out)
        self.assertTrue(loop.sync_state('Watch Test')['ok'])


class RelationsCliTest(unittest.TestCase):
    """The real CLI answers `task relations`: one read per unmarked Todo ticket."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.real_bin = self.directory / 'home/.local/bin'
        self.real_bin.mkdir(parents=True)
        self.real_log = self.directory / 'real.log'
        self.real_log.write_text('')
        task = {'projectId': 13556, 'labels': [{'name': 'Board Drain Loop'}],
                'status': 'Normal', 'assignees': [], 'waitingOnUserId': None,
                'blockerCommentId': None, 'updatedAt': iso(NOW - 300)}
        tasks = [dict(task, ticketNumber='VSTA-7', section='Todo'),
                 dict(task, ticketNumber='VSTA-8', section='Todo', waitingOnUserId=6),
                 dict(task, ticketNumber='VSTA-2', section='Doing',
                      assignees=[agent_assignee('Board Drain Loop')])]
        answers = {'task list': {'tasks': tasks, 'total': len(tasks)},
                   'comment list': {'comments': []},
                   'task relations': {'success': True, 'relations': blocked_by()},
                   'project show': {'project': {'uniqueIdentifier': 'VSTA', 'sections': [
                       {'section_title': 'Todo'}, {'section_title': 'Doing'}]}}}
        write_tool(self.real_bin / 'hypertask',
                   'import json, os, pathlib, sys\n'
                   'log = pathlib.Path(os.environ["REAL_HYPERTASK_LOG"])\n'
                   'log.write_text(log.read_text() + " ".join(sys.argv[1:]) + "\\n")\n'
                   f'answers = {answers!r}\n'
                   'args = [a for a in sys.argv[1:] if a != "--json"]\n'
                   'print(json.dumps(answers.get(" ".join(args[:2]), {"tasks": [], "total": 0})))\n')

    def test_links_come_from_the_cli_once_per_unmarked_todo(self):
        done = subprocess.run(
            [sys.executable, str(SKILL / 'drain-check'), '--board', '13556',
             '--label', 'Board Drain Loop', '--now', iso(NOW)],
            capture_output=True, text=True, timeout=60,
            env={'HOME': str(self.directory / 'home'), 'PATH': '/usr/bin:/bin',
                 'REAL_HYPERTASK_LOG': str(self.real_log),
                 'BOARD_DRAIN_STATE_DIR': str(self.directory / 'state'),
                 'RECONCILE_CACHE': str(self.directory / 'cache.json')})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('blocked: VSTA-7 by VSTA-2, VSTA-3', done.stdout)
        self.assertIn('waiting: VSTA-8 (marked)', done.stdout)
        self.assertIn('drain-check: PASS', done.stdout)
        reads = [line for line in self.real_log.read_text().splitlines()
                 if 'task relations' in line]
        self.assertEqual(reads, ['--json task relations VSTA-7'])


class SyncTest(unittest.TestCase):
    """The sync steps reconcile runs as this chat's own login, without the network."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.creds = self.directory / 'credentials'
        self.creds.mkdir()
        self.states = self.directory / 'state'
        env = patch.dict(os.environ, {'BOARD_DRAIN_STATE_DIR': str(self.states),
                                      'BOARD_DRAIN_CRED_DIR': str(self.creds),
                                      'HT_TOKEN': '', 'SHIP_SESSION_NAME': ''})
        env.start()
        self.addCleanup(env.stop)

    def run_sync(self, answers, *extra, name='HT Test'):
        """answers: one (returncode, stdout, stderr) per reconcile call, in order."""
        queued, calls = list(answers), []

        def fake(argv, **kwargs):
            calls.append({'argv': argv, **kwargs})
            return subprocess.CompletedProcess(argv, *queued.pop(0))

        out, err = io.StringIO(), io.StringIO()
        with patch.object(sync.subprocess, 'run', side_effect=fake), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.main(['--board', '2060', '--label', 'Poteto', '--name', name, *extra])
        return code, out.getvalue() + err.getvalue(), calls

    def write_token(self, text='tok-from-file', name='HT Test'):
        (self.creds / (loop.slug(name) + '-agent-token')).write_text(text + '\n')

    def test_a_usage_error_fails_and_records_it(self):
        self.write_token()
        code, out, calls = self.run_sync([(2, '', 'usage: --apply requires SHIP_SESSION_NAME\n')])
        self.assertEqual(code, 1, out)
        self.assertIn('sync: FAIL', out)
        self.assertIn('usage:', out)
        self.assertEqual(len(calls), 1, out)  # no apply after a broken preview
        record = loop.sync_state('HT Test')
        self.assertIsNotNone(record)
        self.assertFalse(record['ok'])
        self.assertIn('usage:', record['reason'])
        self.assertEqual(loop.status('HT Test'), (2, 'not armed'))

    def test_an_error_in_the_output_fails_even_on_a_zero_exit(self):
        self.write_token()
        code, out, _ = self.run_sync([(0, 'reconcile: API error: 500\n', '')])
        self.assertEqual(code, 1, out)
        self.assertIn('sync: FAIL', out)
        self.assertFalse(loop.sync_state('HT Test')['ok'])

    def test_a_non_zero_exit_fails(self):
        self.write_token()
        code, out, _ = self.run_sync([(1, '', 'board 2060 unreachable\n')])
        self.assertEqual(code, 1, out)
        self.assertIn('sync: FAIL', out)
        self.assertIn('board 2060 unreachable', out)
        self.assertFalse(loop.sync_state('HT Test')['ok'])

    def test_a_budget_skip_prints_one_line_and_exits_clean(self):
        self.write_token()
        line = 'sync skipped: gh budget (wait until 14:20 UTC)'
        code, out, calls = self.run_sync([(0, line + '\n', 'reconcile: budget done in 0.1s\n')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip().splitlines(), [line])
        self.assertEqual(len(calls), 1, 'the apply step never runs after a skip')
        record = loop.sync_state('HT Test')
        self.assertTrue(record['ok'])
        self.assertEqual(record['skipped']['reason'], line)

    def test_a_skip_on_the_apply_step_prints_one_line_and_cleans_up(self):
        self.write_token()
        line = 'sync skipped: gh budget (wait until 14:20 UTC)'
        code, out, calls = self.run_sync([(0, 'preview: nothing to move\n', ''),
                                          (0, line + '\n', '')])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(calls), 2)
        self.assertEqual(out.strip().splitlines()[-1], line)
        self.assertTrue(loop.sync_state('HT Test')['ok'])

    def test_a_clean_preview_then_apply_succeeds(self):
        self.write_token()
        code, out, calls = self.run_sync([(0, 'preview: 2 moves\n', ''),
                                          (0, 'applied: 2 moves\n', '')])
        self.assertEqual(code, 0, out)
        self.assertIn('preview: 2 moves', out)
        self.assertIn('applied: 2 moves', out)
        self.assertEqual(out.strip().splitlines()[-1], 'sync: ok')
        self.assertEqual(len(calls), 2)
        self.assertNotIn('--apply', calls[0]['argv'])
        self.assertIn('--apply', calls[1]['argv'])
        self.assertEqual(calls[1]['argv'][calls[1]['argv'].index('--limit') + 1], '5')
        self.assertEqual(loop.sync_state('HT Test')['ok'], True)

    def test_the_token_comes_from_the_session_credentials(self):
        self.write_token()
        code, out, calls = self.run_sync([(0, 'ok\n', ''), (0, 'ok\n', '')])
        self.assertEqual(code, 0, out)
        for call in calls:
            self.assertEqual(call['env']['HT_TOKEN'], 'tok-from-file')
            self.assertEqual(call['env']['SHIP_SESSION_NAME'], 'HT Test')

    def test_an_existing_token_and_session_name_are_kept(self):
        with patch.dict(os.environ, {'HT_TOKEN': 'from-env', 'SHIP_SESSION_NAME': 'other-chat'}):
            code, out, calls = self.run_sync([(0, 'ok\n', ''), (0, 'ok\n', '')])
        self.assertEqual(code, 0, out)
        self.assertEqual(calls[0]['env']['HT_TOKEN'], 'from-env')
        self.assertEqual(calls[0]['env']['SHIP_SESSION_NAME'], 'other-chat')

    def test_labels_sharing_a_prefix_get_their_own_budget_session(self):
        bugs = sync.caller(13734, 'Multi Bot Bugs')
        features = sync.caller(13734, 'Multi Bot Features')
        self.assertEqual(bugs, 'sync:13734:multi-bo-' + hashlib.sha1(b'Multi Bot Bugs').hexdigest()[:4])
        self.assertNotEqual(bugs, features)
        self.assertNotEqual(sync.caller(13734, 'Multi Bot Bugs'), sync.caller(2060, 'Multi Bot Bugs'))

    def test_each_reconcile_call_carries_the_caller(self):
        self.write_token()
        code, out, calls = self.run_sync([(0, 'ok\n', ''), (0, 'ok\n', '')])
        self.assertEqual(code, 0, out)
        expected = sync.caller(2060, 'Poteto')
        for call in calls:
            self.assertEqual(call['env']['GH_CALLER'], expected)

    def test_an_existing_gh_caller_is_kept(self):
        self.write_token()
        with patch.dict(os.environ, {'GH_CALLER': 'reconcile:2060:mine'}):
            code, out, calls = self.run_sync([(0, 'ok\n', ''), (0, 'ok\n', '')])
        self.assertEqual(code, 0, out)
        for call in calls:
            self.assertEqual(call['env']['GH_CALLER'], 'reconcile:2060:mine')

    def test_no_token_anywhere_fails(self):
        code, out, calls = self.run_sync([])
        self.assertEqual(code, 1, out)
        self.assertIn('sync: FAIL', out)
        self.assertIn('HT_TOKEN', out)
        self.assertEqual(calls, [])
        self.assertFalse(loop.sync_state('HT Test')['ok'])

    def run_sync_for(self, board, label, name, answers, *extra):
        queued, calls = list(answers), []

        def fake(argv, **kwargs):
            calls.append({'argv': argv, **kwargs})
            return subprocess.CompletedProcess(argv, *queued.pop(0))

        out, err = io.StringIO(), io.StringIO()
        with patch.object(sync.subprocess, 'run', side_effect=fake), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.main(['--board', str(board), '--label', label, '--name', name, *extra])
        return code, out.getvalue() + err.getvalue(), calls

    def test_board_lead_runs_unlabeled_after_own_label_with_same_limit(self):
        self.write_token(name='Multi Bot')
        answers = [
            (0, 'DRY RUN board=13734 tickets=1 unknown=0\n', 'reconcile: board 13734 title=Multi Bot\n'),
            (0, 'PREVIEW board=13734 tickets=1 unknown=0\n', ''),
            (0, 'PLAN MUBO-101 AI Review -> Done | merged with PASS\n', ''),
            (0, 'MOVE MUBO-101 AI Review -> Done | merged with PASS\n', ''),
        ]
        code, out, calls = self.run_sync_for(13734, 'Multi Bot', 'Multi Bot', answers, '--limit', '7')
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip().splitlines()[-1], 'sync: ok')
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0]['argv'][2:], ['--board', '13734', '--label', 'Multi Bot'])
        self.assertEqual(calls[1]['argv'][2:], ['--board', '13734', '--label', 'Multi Bot',
                                                '--apply', '--limit', '7'])
        self.assertEqual(calls[2]['argv'][2:], ['--board', '13734', '--unlabeled'])
        self.assertEqual(calls[3]['argv'][2:], ['--board', '13734', '--unlabeled',
                                                '--apply', '--limit', '7'])
        expected_caller = sync.caller(13734, 'Multi Bot')
        for call in calls:
            self.assertEqual(call['env']['HT_TOKEN'], 'tok-from-file')
            self.assertEqual(call['env']['SHIP_SESSION_NAME'], 'Multi Bot')
            self.assertEqual(call['env']['GH_CALLER'], expected_caller)

    def test_vstack_lead_runs_unlabeled_after_own_label(self):
        self.write_token(name='Vstack Maintainer')
        answers = [(0, 'ok\n', '')] * 4
        code, out, calls = self.run_sync_for(13556, 'Vstack', 'Vstack Maintainer', answers)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[2]['argv'][2:], ['--board', '13556', '--unlabeled'])
        self.assertEqual(calls[3]['argv'][2:], ['--board', '13556', '--unlabeled',
                                                '--apply', '--limit', '5'])

    def test_non_lead_chats_do_not_run_unlabeled(self):
        self.write_token(name='Multi Bot Bugs')
        code, out, calls = self.run_sync_for(
            13734, 'Multi Bot Bugs', 'Multi Bot Bugs',
            [(0, 'ok\n', 'reconcile: board 13734 title=Multi Bot\n'), (0, 'ok\n', '')])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(calls), 2)

        self.write_token(name='Hypertask Reconciler')
        code, out, calls = self.run_sync_for(
            13556, 'Hypertask Reconciler', 'Hypertask Reconciler',
            [(0, 'ok\n', 'reconcile: board 13556 title=Vstack\n'), (0, 'ok\n', '')])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(calls), 2)

    def test_board15_lead_runs_unlabeled_and_non_lead_does_not(self):
        self.write_token(name='HT Product Lead')
        code, out, calls = self.run_sync_for(
            15, 'HT Product Lead', 'HT Product Lead', [(0, 'ok\n', '')] * 4)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[2]['argv'][2:], ['--board', '15', '--unlabeled'])

        self.write_token(name='Mobile Designer')
        code, out, calls = self.run_sync_for(
            15, 'Mobile Designer', 'Mobile Designer',
            [(0, 'ok\n', 'reconcile: board 15 title=Hypertask\n'), (0, 'ok\n', '')])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(calls), 2)

    def test_lead_stops_before_unlabeled_on_failure(self):
        self.write_token(name='Multi Bot')
        code, out, calls = self.run_sync_for(
            13734, 'Multi Bot', 'Multi Bot',
            [(0, 'ok\n', 'reconcile: board 13734 title=Multi Bot\n'), (1, '', 'boom\n')])
        self.assertEqual(code, 1, out)
        self.assertEqual(len(calls), 2)
        self.assertFalse(loop.sync_state('Multi Bot')['ok'])

    def test_lead_stops_before_unlabeled_on_budget_skip(self):
        self.write_token(name='Multi Bot')
        skip_line = 'sync skipped: gh budget (wait until 14:20 UTC)'
        code, out, calls = self.run_sync_for(
            13734, 'Multi Bot', 'Multi Bot',
            [(0, 'ok\n', 'reconcile: board 13734 title=Multi Bot\n'),
             (0, 'ok\n', ''),
             (0, skip_line + '\n', '')])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(calls), 3)
        self.assertEqual(out.strip().splitlines()[-1], skip_line)
        record = loop.sync_state('Multi Bot')
        self.assertTrue(record['ok'])
        self.assertEqual(record['skipped']['reason'], skip_line)

    def test_the_cli_runs_and_refuses_without_a_token(self):
        env = dict(os.environ, BOARD_DRAIN_STATE_DIR=str(self.states),
                   BOARD_DRAIN_CRED_DIR=str(self.creds), HT_TOKEN='', SHIP_SESSION_NAME='')
        done = subprocess.run([sys.executable, str(SKILL / 'sync'), '--board', '2060',
                               '--label', 'Poteto', '--name', 'HT Test'],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn('sync: FAIL', done.stdout)


VSTACK_PR = {'url': 'https://github.com/valentinyeo/vstack/pull/7',
             'state': 'OPEN', 'checks': 'green'}
CEO_PR = {'url': 'https://github.com/valentinyeo/ceo/pull/9',
          'state': 'OPEN', 'checks': 'green'}


class ViewReposTest(unittest.TestCase):
    """The merge gate is judged on the PRs this chat's own view carries, nothing else."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for patcher in (patch.dict(os.environ,
                                   {'BOARD_DRAIN_STATE_DIR': str(self.directory)}),
                        patch.object(drain.loop_state, 'timer_enabled', return_value=True),
                        patch.object(drain, 'open_pull_rows', return_value=[])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def board(self):
        return drain.reconcile.BOARDS[13556]

    def run_payload(self, payload):
        fixture = self.directory / 'fixture.json'
        fixture.write_text(json.dumps(payload))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = drain.main(['--board', '2060', '--label', 'Poteto',
                               '--fixture', str(fixture), '--now', iso(NOW), '--no-load'])
        return code, out.getvalue()

    def test_the_prs_loaded_for_the_view_name_their_repos(self):
        self.assertEqual(drain.view_repos([todo('SOFT-1')], {'SOFT-1': [VSTACK_PR]}, (),
                                          self.board()),
                         {'valentinyeo/vstack'})

    def test_a_pr_the_card_links_names_its_repo(self):
        row = todo('SOFT-2')
        row['task']['pullRequests'] = [CEO_PR]
        self.assertEqual(drain.view_repos([row], None, (), self.board()), {'valentinyeo/ceo'})

    def test_the_open_listing_row_matched_to_a_card_names_its_repo(self):
        listing = [dict(VSTACK_PR, title='SOFT-3 fix the gate', headRefName='SOFT-3-gate')]
        self.assertEqual(drain.view_repos([todo('SOFT-3')], {}, listing, self.board()),
                         {'valentinyeo/vstack'})

    def test_another_chats_pr_and_repo_never_enter_the_set(self):
        row = todo('SOFT-4')
        row['task']['pullRequests'] = [CEO_PR]
        listing = [dict(VSTACK_PR, title='SOFT-99 another chat', headRefName='SOFT-99-x')]
        self.assertEqual(drain.view_repos([row], {}, listing, self.board()),
                         {'valentinyeo/ceo'})

    def test_a_view_with_no_prs_names_no_repo(self):
        self.assertEqual(drain.view_repos([todo('SOFT-5')], {}, (), self.board()), set())

    def gate_sees(self, payload):
        seen = {}

        def record(board, now, fixture=None, repos=None):
            seen['repos'] = repos
            return []

        with patch.object(drain.merge_gate, 'gate_findings', side_effect=record):
            self.run_payload(payload)
        return seen['repos']

    def test_the_check_hands_the_gate_only_the_views_repos(self):
        self.assertEqual(self.gate_sees({'rows': [todo('SOFT-1')],
                                         'pulls': {'SOFT-1': [VSTACK_PR]}}),
                         {'valentinyeo/vstack'})

    def test_the_check_asks_no_gate_read_without_a_pr(self):
        self.assertEqual(self.gate_sees({'rows': [todo('SOFT-1')]}), set())


LABEL = 'Board Drain Loop'


def cap_pull(number, *keys, created=None):
    """One open PR fact, its title naming the tickets it carries."""
    named = ' '.join(keys) or f'VSTA-{number}'
    return {'url': f'https://github.com/valentinyeo/vstack/pull/{number}', 'number': number,
            'state': 'OPEN', 'title': f'fix: {named}', 'headRefName': f'pr-{number}',
            'body': '', 'createdAt': created or iso(NOW - 60 * number),
            'repository': {'nameWithOwner': 'valentinyeo/vstack'}}


def own_cards(count=5):
    """This label's cards, each in Checks with its own open PR."""
    rows = [vsta(f'VSTA-{n}', section='Checks') for n in range(1, count + 1)]
    pulls = {f'VSTA-{n}': [cap_pull(n)] for n in range(1, count + 1)}
    return rows, pulls


class PrCapTest(CheckTest):
    """The PR cap counts only the pull requests this chat's own cards carry (VSTA-237)."""

    def drain_cap(self, payload):
        code, out = self.run_payload(payload, board=13556, label=LABEL)
        return code, out

    def cap_line(self, out):
        return next((line for line in out.splitlines()
                     if line.startswith('agent PR cap:')), '')

    def test_a_pr_naming_another_labels_ticket_is_not_counted(self):
        # PR 391 names only VSTA-233, a Hypertask Reconciler card, so it never spends
        # this label's cap however the board read hangs it on one of these cards.
        rows, pulls = own_cards()
        foreign = vsta('VSTA-233', section='Checks')
        foreign['task']['labels'] = [{'name': 'Hypertask Reconciler'}]
        rows.append(foreign)
        pulls['VSTA-233'] = [cap_pull(391, 'VSTA-233')]
        pulls['VSTA-1'].append(cap_pull(391, 'VSTA-233'))
        code, out = self.drain_cap({'rows': rows, 'pulls': pulls})
        self.assertNotIn('agent PR cap', out)

    def test_a_pr_naming_both_an_own_and_a_foreign_ticket_counts_once(self):
        rows, pulls = own_cards()
        pulls['VSTA-5'].append(cap_pull(6, 'VSTA-5', 'VSTA-233', created=iso(NOW)))
        code, out = self.drain_cap({'rows': rows, 'pulls': pulls})
        self.assertEqual(code, 1, out)
        line = self.cap_line(out)
        self.assertIn('owns 6 open PRs (cap 5)', line)
        self.assertEqual(line.count('/pull/6'), 1, line)
        self.assertIn('VSTA-5 https://github.com/valentinyeo/vstack/pull/6', line)

    def test_own_prs_still_trip_the_cap_at_six(self):
        rows, pulls = own_cards(5)
        code, out = self.drain_cap({'rows': rows, 'pulls': pulls})
        self.assertNotIn('agent PR cap', out)
        rows, pulls = own_cards(6)
        code, out = self.drain_cap({'rows': rows, 'pulls': pulls})
        self.assertEqual(code, 1, out)
        line = self.cap_line(out)
        self.assertIn('owns 6 open PRs (cap 5)', line)
        self.assertIn('/pull/1', line)
        self.assertNotIn('/pull/2', line)


if __name__ == '__main__':
    unittest.main()
