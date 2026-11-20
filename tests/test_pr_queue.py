"""Tests for skills/pr-housekeeping/pr-queue: the class ladder, ownership, verdict at head, exit codes.

Every fixture is a plain gh JSON shape and a roster line. No test touches the network."""

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/pr-housekeeping/pr-queue'
SHA = 'a' * 40
HEAD = 'b' * 40
OLD = 'c' * 40
BODY = 'Author model: deepseek/deepseek-v4.1-flash\nPacer launch: deepseek 2026-11-20T10:40:13Z\n'


def load_script():
    loader = importlib.machinery.SourceFileLoader('pr_queue', str(SCRIPT))
    spec = importlib.util.spec_from_loader('pr_queue', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def hours_ago(hours):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - hours * 3600))


def rollup(kind):
    if kind == 'none':
        return []
    passed = [{'__typename': 'CheckRun', 'name': 'skills', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}]
    if kind == 'green':
        return passed
    if kind == 'red':
        return passed + [{'__typename': 'CheckRun', 'name': 'verifier', 'status': 'COMPLETED',
                          'conclusion': 'FAILURE'}]
    if kind == 'pending':
        return passed + [{'__typename': 'CheckRun', 'name': 'verifier', 'status': 'IN_PROGRESS', 'conclusion': ''}]
    if kind == 'cancelled':
        return passed + [{'__typename': 'CheckRun', 'name': 'verifier', 'status': 'COMPLETED',
                          'conclusion': 'CANCELLED'}]
    if kind == 'status-context':
        return [{'__typename': 'StatusContext', 'context': 'build', 'state': 'ERROR'}]
    raise ValueError(kind)


def comment(body, age=1.0):
    return {'body': body, 'createdAt': hours_ago(age), 'author': {'login': 'verifier'}}


def view(number=1, repo='o/r', title=None, branch=None, author='valentinyeo',
         age=1.0, pushed=1.0, body=BODY, checks='green', mergeable='MERGEABLE', comments=(), head=SHA):
    # One ticket key per PR unless the test names one, so unrelated fixtures never read as duplicates.
    title = title or f'SOFT-{number} thing'
    branch = branch or f'soft-{number}-thing'
    return {
        'repository': repo,
        'number': number,
        'url': f'https://github.com/{repo}/pull/{number}',
        'title': title,
        'headRefName': branch,
        'headRefOid': head,
        'author': {'login': author},
        'createdAt': hours_ago(age),
        'updatedAt': hours_ago(age),
        'isDraft': False,
        'body': body,
        'mergeable': mergeable,
        'statusCheckRollup': rollup(checks),
        'comments': list(comments),
        'commits': [{'oid': head, 'committedDate': hours_ago(pushed)}],
    }


def chat(name, cwd='', repo=None, branch=None):
    return {'name': name, 'cwd': cwd, 'repo': repo, 'branch': branch}


def states(rows):
    return {row['number']: row['state'] for row in rows}


class ModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def rows(self, views, chats=(chat('Some Chat', repo='o/r'),), **kwargs):
        return self.m.build_rows(views, list(chats), **kwargs)

    def test_ticket_key_from_title_then_branch(self):
        self.assertEqual(self.m.ticket_key('SOFT-2943: tidy up', 'x'), 'SOFT-2943')
        self.assertEqual(self.m.ticket_key('tidy up', 'soft-2943-tidy-up'), 'SOFT-2943')
        self.assertIsNone(self.m.ticket_key('bump a dependency', 'dependabot/npm/x'))
        self.assertIsNone(self.m.ticket_key('RUNNER-3 test', 'x'), 'runner keys are not tickets')

    def test_checks_state(self):
        self.assertEqual(self.m.checks_state(rollup('green')), 'green')
        self.assertEqual(self.m.checks_state(rollup('red')), 'red')
        self.assertEqual(self.m.checks_state(rollup('pending')), 'pending')
        self.assertEqual(self.m.checks_state(rollup('none')), 'none')
        self.assertEqual(self.m.checks_state(rollup('cancelled')), 'green', 'a superseded run is not a failure')
        self.assertEqual(self.m.checks_state(rollup('status-context')), 'red')

    def test_verdict_reads_only_the_current_head(self):
        old = comment(f'VERDICT: PASS\n\nVerifier model: opencode-go/glm-5.3-flash. Head `{OLD}`.', age=2)
        now = comment(f'VERDICT: PASS+NOTES\n\nVerifier model: opencode-go/glm-5.3-flash. Head `{SHA}`.', age=1)
        self.assertEqual(self.m.verdict_at([old], SHA), 'none', 'a verdict on an older head does not count')
        self.assertEqual(self.m.verdict_at([old, now], SHA), 'PASS+NOTES')
        self.assertEqual(self.m.verdict_at([old], OLD), 'PASS')

    def test_verdict_uses_the_newest_answer_at_head(self):
        passed = comment(f'pstack-verifier: PASS @ {SHA}\n\nVERDICT: PASS', age=3)
        failed = comment(f'pstack-verifier: FAIL @ {SHA}\n\nVERDICT: FAIL', age=1)
        self.assertEqual(self.m.verdict_at([passed, failed], SHA), 'FAIL')

    def test_verdict_ignores_a_comment_without_a_verdict(self):
        chatter = comment(f'pushed {SHA}', age=1)
        self.assertEqual(self.m.verdict_at([chatter], SHA), 'none')

    def test_verdict_paragraph_and_json_forms(self):
        paragraph = comment(f'Answer below.\n\nPASS\n\nHead: `{SHA}`', age=1)
        self.assertEqual(self.m.verdict_at([paragraph], SHA), 'PASS')
        boxed = comment(f'{{"verdict": "PASS"}}\n\nHead {SHA}', age=1)
        self.assertEqual(self.m.verdict_at([boxed], SHA), 'PASS')

    def test_owner_from_branch_slug(self):
        chats = [chat('PR Housekeeping', repo='o/r'), chat('Vstack Maintainer', repo='o/r')]
        self.assertEqual(self.m.owner_chat('soft-2943-pr-housekeeping', 'o/r', chats), 'PR Housekeeping')

    def test_owner_from_worktree_branch_beats_a_slug(self):
        chats = [chat('Responsive Mode', repo='o/r', branch='soft-2943-pr-housekeeping')]
        self.assertEqual(self.m.owner_chat('soft-2943-pr-housekeeping', 'o/r', chats), 'Responsive Mode')

    def test_owner_from_the_only_checkout_of_the_repo(self):
        chats = [chat('Pecunia', repo='o/r'), chat('Upwork', repo='o/other')]
        self.assertEqual(self.m.owner_chat('feature-x', 'o/r', chats), 'Pecunia')

    def test_owner_is_null_when_many_chats_share_the_repo(self):
        chats = [chat('Board Drain Loop', repo='o/r'), chat('VPS Admin', repo='o/r')]
        self.assertIsNone(self.m.owner_chat('feature-x', 'o/r', chats), 'two chats, no branch: nobody owns it')

    def test_owner_ignores_generic_chat_names(self):
        chats = [chat('Claude', repo='o/r')]
        self.assertIsNone(self.m.owner_chat('claude-helper-gate', 'o/r', chats))

    def test_owner_from_the_board_assignee(self):
        chats = [chat('Board Drain Loop', repo='o/r'), chat('VPS Admin', repo='o/r')]
        self.assertIsNone(self.m.owner_chat('feature-x', 'o/r', chats), 'two checkouts own nobody')
        self.assertEqual(self.m.owner_chat('feature-x', 'o/r', chats, ['VPS Admin']), 'VPS Admin')
        self.assertEqual(self.m.owner_chat('feature-x', 'o/r', chats, ['vps admin']), 'VPS Admin',
                         'the board name matches without case')

    def test_board_assignee_that_is_not_live_owns_nothing(self):
        chats = [chat('Board Drain Loop', repo='o/r'), chat('VPS Admin', repo='o/r')]
        self.assertIsNone(self.m.owner_chat('feature-x', 'o/r', chats, ['HT Vstack Lead']))
        self.assertIsNone(self.m.owner_chat('feature-x', 'o/r', chats, ['Board Drain Loop', 'VPS Admin']),
                          'two live assignees own nobody')
        self.assertIsNone(self.m.owner_chat('feature-x', 'o/r', chats, ['Claude']), 'a generic name owns nobody')

    def test_branch_slug_beats_the_board_assignee(self):
        chats = [chat('PR Housekeeping', repo='o/r'), chat('VPS Admin', repo='o/r')]
        self.assertEqual(self.m.owner_chat('vsta-12-pr-housekeeping', 'o/r', chats, ['VPS Admin']),
                         'PR Housekeeping', 'the branch is the closest evidence')

    def test_ticket_owner_names(self):
        answer = json.dumps({'success': True, 'tasks': [
            {'ticketNumber': 'VSTA-12', 'assignees': [{'displayName': 'PR Housekeeping'}, {'displayName': ''}]}]})
        self.assertEqual(self.m.ticket_owner_names(answer, 'VSTA-12'), ['PR Housekeeping'])
        self.assertEqual(self.m.ticket_owner_names('', 'VSTA-12'), [])
        self.assertEqual(self.m.ticket_owner_names('not json', 'VSTA-12'), [])
        self.assertEqual(self.m.ticket_owner_names(json.dumps({'tasks': []}), 'VSTA-12'), [])

    def test_every_state_class(self):
        passed = comment(f'VERDICT: PASS\n\nHead `{SHA}`')
        failed = comment(f'VERDICT: FAIL\n\nHead `{SHA}`')
        rows = self.rows([
            view(1, author='app/dependabot'),
            view(2, title='SOFT-2 a', age=2, checks='none'), view(3, title='SOFT-2 b', age=1, checks='none'),
            view(4, mergeable='CONFLICTING'),
            view(5, checks='red'),
            view(6, comments=[failed]),
            view(7, body=''),
            view(8),
            view(9, pushed=100),
            view(10, comments=[passed]),
            view(11, repo='o/other'),
            view(12, mergeable='CONFLICTING', checks='red'),
            view(13, checks='red', body=''),
            view(14, comments=[failed], body=''),
            view(15, body=''),
            view(16, pushed=100, body=''),
            view(17, pushed=100, comments=[passed]),
            view(18, repo='o/other', comments=[passed]),
            view(19, repo='o/other', mergeable='CONFLICTING', checks='red', body=''),
        ])
        got = states(rows)
        self.assertEqual(got[1], 'BOT')
        self.assertEqual(got[2], 'NO-VERDICT')
        self.assertEqual(got[3], 'DUPLICATE', 'the newer PR of a ticket is the duplicate')
        self.assertEqual(got[4], 'CONFLICT')
        self.assertEqual(got[5], 'RED')
        self.assertEqual(got[6], 'VERIFIER-FAIL')
        self.assertEqual(got[7], 'MISSING-LINES')
        self.assertEqual(got[8], 'NO-VERDICT')
        self.assertEqual(got[9], 'NO-VERDICT', 'no verdict is the next action before stale')
        self.assertEqual(got[10], 'READY')
        self.assertEqual(got[11], 'NO-OWNER', 'no owner comes before no verdict')
        self.assertEqual(got[12], 'CONFLICT', 'conflict beats red')
        self.assertEqual(got[13], 'RED', 'red beats missing lines')
        self.assertEqual(got[14], 'VERIFIER-FAIL', 'verifier fail beats missing lines')
        self.assertEqual(got[15], 'MISSING-LINES', 'missing lines beats no verdict')
        self.assertEqual(got[16], 'MISSING-LINES', 'missing lines beats stale')
        self.assertEqual(got[17], 'STALE', 'a verified PR nobody pushed for 72h is stale')
        self.assertEqual(got[18], 'NO-OWNER', 'a verified PR no live chat claims has no owner')
        self.assertEqual(got[19], 'NO-OWNER', 'no owner beats conflict, red and missing lines')

    def test_duplicate_keeps_the_verified_pr_at_its_head(self):
        passed = [comment(f'VERDICT: PASS\n\nHead `{SHA}`')]
        rows = self.rows([view(180, title='SOFT-70 stalled', age=5, checks='none'),
                          view(181, title='SOFT-70 verified', age=1, comments=passed)],
                         chats=[chat('Owner', repo='o/r')])
        got = {row['number']: row for row in rows}
        self.assertEqual(got[181]['state'], 'READY', 'the verified PR is the one to keep')
        self.assertEqual(got[180]['state'], 'DUPLICATE')
        self.assertEqual(got[180]['duplicate_of'], 181)
        self.assertIn('#181', got[180]['next_action'], 'the duplicate names the keeper')

    def test_duplicate_ignores_a_verdict_from_an_older_head(self):
        stale_verdict = [comment(f'VERDICT: PASS\n\nHead `{OLD}`')]
        rows = self.rows([view(182, title='SOFT-71 old verdict', age=5, comments=stale_verdict),
                          view(183, title='SOFT-71 green', age=1)],
                         chats=[chat('Owner', repo='o/r')])
        got = {row['number']: row for row in rows}
        self.assertEqual(got[182]['verdict'], 'none', 'a verdict on an older head does not count')
        self.assertEqual(got[183]['state'], 'NO-VERDICT')
        self.assertEqual(got[182]['duplicate_of'], 183, 'the newest green one is the keeper')

    def test_duplicate_keeps_the_newest_green_pr_when_none_is_verified(self):
        rows = self.rows([view(184, title='SOFT-72 old', age=5), view(185, title='SOFT-72 new', age=1)],
                         chats=[chat('Owner', repo='o/r')])
        got = {row['number']: row for row in rows}
        self.assertEqual(got[185]['state'], 'NO-VERDICT')
        self.assertEqual(got[184]['duplicate_of'], 185)

    def test_duplicate_falls_back_to_the_oldest_pr(self):
        rows = self.rows([view(20, title='SOFT-9 new', age=1, checks='none'),
                          view(21, title='SOFT-9 old', age=5, checks='none')],
                         chats=[chat('Owner', repo='o/r')])
        rows = {row['number']: row for row in rows}
        self.assertEqual(rows[21]['state'], 'NO-VERDICT')
        self.assertEqual(rows[20]['state'], 'DUPLICATE')
        self.assertEqual(rows[20]['duplicate_of'], 21)

    def test_duplicate_breaks_a_same_second_tie_by_number(self):
        rows = self.rows([view(30, title='SOFT-8 a', age=2, checks='none'),
                          view(31, title='SOFT-8 b', age=2, checks='none')],
                         chats=[chat('Owner', repo='o/r')])
        got = {row['number']: row for row in rows}
        self.assertEqual(got[31]['state'], 'DUPLICATE')
        self.assertEqual(got[31]['duplicate_of'], 30)
        self.assertNotEqual(got[30]['state'], 'DUPLICATE', 'one keeper per ticket, even in the same second')

    def test_billing_needs_a_failing_check_message(self):
        failed = [{'output': {'title': 'The job was not started because recent account payments have failed '
                                       'or your spending limit needs to be increased.'}}]
        clean = [{'output': {'title': None, 'summary': None}}]
        billing = self.rows([view(30, checks='red')], billing_probe=lambda repo, sha: failed)[0]
        plain = self.rows([view(31, checks='red')], billing_probe=lambda repo, sha: clean)[0]
        self.assertTrue(billing['billing_blocked'])
        self.assertEqual(billing['state'], 'BILLING')
        self.assertFalse(plain['billing_blocked'])
        self.assertEqual(plain['state'], 'RED')

    def test_billing_never_probes_a_green_pr(self):
        calls = []

        def probe(repo, sha):
            calls.append((repo, sha))
            return [{'output': {'title': 'recent account payments have failed'}}]

        row = self.rows([view(32, checks='green')], billing_probe=probe)[0]
        self.assertEqual(calls, [])
        self.assertFalse(row['billing_blocked'])

    def test_rows_carry_every_field(self):
        row = self.rows([view(40, comments=[comment(f'VERDICT: PASS\n\nHead `{SHA}`')], age=2, pushed=3)])[0]
        for field in ('repo', 'number', 'url', 'title', 'branch', 'head_sha', 'author', 'age_hours',
                      'hours_since_push', 'ticket_key', 'owner_chat', 'checks', 'billing_blocked', 'conflict',
                      'verdict', 'has_author_model', 'has_pacer_line', 'duplicate_of', 'state', 'next_action'):
            self.assertIn(field, row)
        self.assertEqual(row['repo'], 'o/r')
        self.assertEqual(row['ticket_key'], 'SOFT-40')
        self.assertEqual(row['verdict'], 'PASS')
        self.assertEqual(row['owner_chat'], 'Some Chat')
        self.assertAlmostEqual(row['age_hours'], 2, delta=0.1)
        self.assertAlmostEqual(row['hours_since_push'], 3, delta=0.1)
        self.assertTrue(row['has_author_model'] and row['has_pacer_line'])
        self.assertTrue(row['next_action'])

    def test_missing_lines_use_the_repo_pacer_rule(self):
        row = self.rows([view(41, body='Author model: deepseek/deepseek-v4.1-flash\nPacer launch: soon\n')])[0]
        self.assertTrue(row['has_author_model'])
        self.assertFalse(row['has_pacer_line'], 'an unparseable launch line is no line')
        self.assertEqual(row['state'], 'MISSING-LINES')

    def test_stale_hours_is_configurable(self):
        passed = [comment(f'VERDICT: PASS\n\nHead `{SHA}`')]
        rows = self.rows([view(50, pushed=10, comments=passed)], chats=[chat('Owner', repo='o/r')],
                         stale_hours=5)
        self.assertEqual(rows[0]['state'], 'STALE')
        rows = self.rows([view(50, pushed=10, comments=passed)], chats=[chat('Owner', repo='o/r')],
                         stale_hours=20)
        self.assertEqual(rows[0]['state'], 'READY', 'a verified PR inside the window is ready')

    def test_ready_accepts_pass_with_notes(self):
        notes = comment(f'VERDICT: PASS+NOTES\n\nHead `{SHA}`')
        row = self.rows([view(60, comments=[notes])])[0]
        self.assertEqual(row['state'], 'READY')

    def test_ok_waits_for_ci(self):
        passed = comment(f'VERDICT: PASS\n\nHead `{SHA}`')
        row = self.rows([view(61, checks='pending', comments=[passed])])[0]
        self.assertEqual(row['state'], 'OK')

    def test_counts(self):
        rows = self.rows([view(70), view(71, checks='red')], chats=[chat('Owner', repo='o/r')])
        self.assertEqual(self.m.counts(rows), {'NO-VERDICT': 1, 'RED': 1})


class CliTests(unittest.TestCase):
    """The real exit code the loop tick sees: nonzero whenever a PR in scope is NO-OWNER or STALE."""

    def cli(self, views, chats=('Owner (live-x, claude, /home/valentin/projects/r)',), args=(), gh_exit=0,
            checks=(), board=None, token=False, env_extra=None, script=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'home'
            bin_dir = root / 'bin'
            (home / '.local/share/house-rules/fleet').mkdir(parents=True)
            bin_dir.mkdir()
            (home / '.local/share/house-rules/fleet/roster-live').write_text(
                '#!/bin/sh\ncat "$HOME/roster.txt"\n')
            (home / '.local/share/house-rules/fleet/roster-live').chmod(0o755)
            (home / 'roster.txt').write_text('\n'.join(chats) + '\n')
            (root / 'search.json').write_text(json.dumps([
                {'number': item['number'], 'title': item['title'], 'url': item['url'],
                 'repository': {'nameWithOwner': item['repository']}, 'author': item['author'],
                 'createdAt': item['createdAt'], 'updatedAt': item['updatedAt'], 'isDraft': False}
                for item in views]))
            (root / 'views').mkdir()
            for item in views:
                key = item['repository'].replace('/', '_') + '-' + str(item['number'])
                (root / 'views' / (key + '.json')).write_text(json.dumps(item))
            (root / 'checks').mkdir()
            for item, runs in checks:
                key = item['repository'].replace('/', '_') + '-' + str(item['number'])
                (root / 'checks' / (key + '.json')).write_text(json.dumps({'check_runs': runs}))
            # The fixture gh answers three shapes and fails the rest, so an unexpected call is loud.
            (bin_dir / 'gh').write_text(f'''#!{sys.executable}
import json, subprocess, sys
from pathlib import Path
root = Path({str(root)!r})
argv = sys.argv[1:]
if argv[:2] == ["search", "prs"]:
    if {gh_exit}:
        sys.exit({gh_exit})
    print((root / "search.json").read_text())
    sys.exit(0)
if argv[:2] == ["pr", "view"]:
    repo = argv[argv.index("--repo") + 1]
    key = repo.replace("/", "_") + "-" + argv[2]
    print((root / "views" / (key + ".json")).read_text())
    sys.exit(0)
if argv[0] == "api":
    parts = argv[1].split("/")
    repo = parts[1] + "/" + parts[2]
    sha = parts[4]
    for item in json.loads((root / "search.json").read_text()):
        key = repo.replace("/", "_") + "-" + str(item["number"])
        path = root / "checks" / (key + ".json")
        if path.exists() and json.loads((root / "views" / (key + ".json")).read_text())["headRefOid"] == sha:
            print(path.read_text())
            sys.exit(0)
    print('{{"check_runs": []}}')
    sys.exit(0)
sys.stderr.write("gh fixture: unexpected " + " ".join(argv) + "\\n")
sys.exit(3)
''')
            (bin_dir / 'gh').chmod(0o755)
            # A fake board reader: it records every call so a test can prove the run stayed read only.
            if board is not None:
                (root / 'board.json').write_text(json.dumps(board))
                (root / 'calls.txt').write_text('')
                (bin_dir / 'hypertask').write_text(
                    '#!/usr/bin/env python3\nimport json, sys\nfrom pathlib import Path\n'
                    f'root = Path({str(root)!r})\n'
                    'with (root / "calls.txt").open("a") as log:\n'
                    '    log.write(" ".join(sys.argv[1:]) + "\\n")\n'
                    'board = json.loads((root / "board.json").read_text())\n'
                    'args = sys.argv[1:]\n'
                    'if board == "fail":\n'
                    '    sys.stderr.write("hypertask fixture: the login was rejected\\n")\n'
                    '    sys.exit(1)\n'
                    'if args[-3:-1] != ["task", "get"]:\n'
                    '    sys.stderr.write("hypertask fixture: unexpected " + " ".join(args) + "\\n")\n'
                    '    sys.exit(3)\n'
                    'key = args[-1]\n'
                    'print(json.dumps({"success": True, "tasks": [{"ticketNumber": key,\n'
                    '    "assignees": board.get(key, [])}] if key in board else []}))\n')
                (bin_dir / 'hypertask').chmod(0o755)
            token_path = root / 'token.txt'
            token_path.write_text('tok-fixture\n')
            if token:
                args = [*args, '--token-file', str(token_path)]
            (root / 'token.txt').chmod(0o600)
            env = dict(os.environ, HOME=str(home), PATH=str(bin_dir) + ':' + os.environ['PATH'])
            env.update(env_extra or {})
            result = subprocess.run([sys.executable, str(script or SCRIPT), *args], env=env,
                                    capture_output=True, text=True)
            calls = root / 'calls.txt'
            result.calls = calls.read_text().splitlines() if calls.exists() else []
            return result

    def test_all_owned_and_fresh_exits_zero(self):
        passed = comment(f'VERDICT: PASS\n\nHead `{SHA}`')
        views = [view(1, repo='o/r', branch='owner-thing', pushed=1, comments=[passed])]
        result = self.cli(views, chats=('Owner (live-x, claude, /home/valentin/projects/r)',),
                          args=['--owner', 'o'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('READY', result.stdout)

    def test_no_owner_exits_one(self):
        passed = comment(f'VERDICT: PASS\n\nHead `{SHA}`')
        views = [view(1, repo='o/r', branch='nobody-here', pushed=1, comments=[passed])]
        result = self.cli(views, chats=())
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('NO-OWNER', result.stdout)

    def test_runs_through_a_symlink_outside_the_repo(self):
        """~/.claude/skills/pr-housekeeping is a symlink into the checkout: the script still finds
        scripts/verdict.py and scripts/pacer-check.py through its real path."""
        passed = comment(f'VERDICT: PASS\n\nHead `{SHA}`')
        views = [view(1, repo='o/r', branch='owner-thing', pushed=1, comments=[passed])]
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / 'skills'
            link.symlink_to(ROOT / 'skills')
            result = self.cli(views, chats=('Owner (live-x, claude, /home/valentin/projects/r)',),
                              script=link / 'pr-housekeeping/pr-queue')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('READY', result.stdout)

    def test_board_assignee_owns_the_pr(self):
        passed = comment(f'VERDICT: PASS\n\nHead `{SHA}`')
        views = [view(1, repo='o/r', title='VSTA-12 thing', branch='ticket-thing', pushed=1,
                      comments=[passed])]
        chats = ('Board Owner (live-x, claude, /home/valentin/projects/r)',
                 'Other Chat (live-y, claude, /home/valentin/projects/s)')
        self.assertEqual(self.cli(views, chats=chats).returncode, 1, 'no token, so nobody owns it')
        result = self.cli(views, chats=chats, token=True,
                          board={'VSTA-12': [{'displayName': 'Board Owner'}]})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('READY', result.stdout)
        self.assertIn('Board Owner', result.stdout)

    def test_board_is_read_with_the_ticket_key_and_nothing_else(self):
        views = [view(1, repo='o/r', title='VSTA-12 thing', branch='ticket-thing')]
        chats = ('Board Owner (live-x, claude, /home/valentin/projects/r)',
                 'Other Chat (live-y, claude, /home/valentin/projects/s)')
        result = self.cli(views, chats=chats, token=True,
                          board={'VSTA-12': [{'displayName': 'Board Owner'}]})
        self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
        calls = result.calls
        self.assertEqual(len(calls), 1, calls)
        self.assertTrue(calls[0].startswith('--json --token tok-fixture '), calls)
        self.assertTrue(calls[0].endswith(' task get VSTA-12'), calls)

    def test_board_reads_one_ticket_once(self):
        views = [view(1, repo='o/r', title='VSTA-12 a', branch='ticket-one'),
                 view(2, repo='o/r', title='VSTA-12 b', branch='ticket-two')]
        chats = ('Board Owner (live-x, claude, /home/valentin/projects/r)',
                 'Other Chat (live-y, claude, /home/valentin/projects/s)')
        result = self.cli(views, chats=chats, token=True,
                          board={'VSTA-12': [{'displayName': 'Board Owner'}]})
        self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
        self.assertEqual(len(result.calls), 1, result.calls)

    def test_a_missing_token_file_runs_without_the_board(self):
        views = [view(1, repo='o/r', title='VSTA-12 thing', branch='ticket-thing')]
        chats = ('Board Owner (live-x, claude, /home/valentin/projects/r)',
                 'Other Chat (live-y, claude, /home/valentin/projects/s)')
        result = self.cli(views, chats=chats, args=['--token-file', '/nonexistent/token'],
                          board={'VSTA-12': [{'displayName': 'Board Owner'}]})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('NO-OWNER', result.stdout)
        self.assertEqual(result.calls, [])
        self.assertIn('cannot read --token-file', result.stderr)

    def test_board_needs_a_token(self):
        views = [view(1, repo='o/r', title='VSTA-12 thing', branch='ticket-thing')]
        chats = ('Board Owner (live-x, claude, /home/valentin/projects/r)',
                 'Other Chat (live-y, claude, /home/valentin/projects/s)')
        result = self.cli(views, chats=chats, board={'VSTA-12': [{'displayName': 'Board Owner'}]})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('NO-OWNER', result.stdout)
        self.assertEqual(result.calls, [], 'no token means no board read')

    def test_ht_token_in_the_environment_is_used(self):
        passed = comment(f'VERDICT: PASS\n\nHead `{SHA}`')
        views = [view(1, repo='o/r', title='VSTA-12 thing', branch='ticket-thing', comments=[passed])]
        chats = ('Board Owner (live-x, claude, /home/valentin/projects/r)',
                 'Other Chat (live-y, claude, /home/valentin/projects/s)')
        result = self.cli(views, chats=chats, board={'VSTA-12': [{'displayName': 'Board Owner'}]},
                          env_extra={'HT_TOKEN': 'tok-env'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('READY', result.stdout)

    def test_a_failing_board_read_leaves_the_pr_unowned(self):
        views = [view(1, repo='o/r', title='VSTA-12 thing', branch='ticket-thing')]
        chats = ('Board Owner (live-x, claude, /home/valentin/projects/r)',
                 'Other Chat (live-y, claude, /home/valentin/projects/s)')
        result = self.cli(views, chats=chats, token=True, board='fail')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('NO-OWNER', result.stdout)

    def test_stale_exits_one(self):
        passed = comment(f'VERDICT: PASS\n\nHead `{SHA}`')
        views = [view(1, repo='o/r', branch='owner-thing', pushed=100, comments=[passed])]
        result = self.cli(views, chats=('Owner (live-x, claude, /home/valentin/projects/r)',))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('STALE', result.stdout)

    def test_network_error_exits_two(self):
        result = self.cli([], gh_exit=1)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_mine_keeps_only_its_own_rows(self):
        views = [view(1, repo='o/r', branch='owner-thing', pushed=1),
                 view(2, repo='o/r', branch='someone-else', title='SOFT-7 other', pushed=1)]
        result = self.cli(views, chats=('Owner (live-x, claude, /home/valentin/projects/r)',
                                        'Other Chat (live-y, claude, /home/valentin/projects/r)'),
                          args=['--mine', 'owner'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('o/r#1', result.stdout)
        self.assertNotIn('o/r#2', result.stdout)

    def test_mine_naming_no_live_chat_exits_two(self):
        views = [view(1, repo='o/r', branch='owner-thing')]
        result = self.cli(views, chats=('Owner (live-x, claude, /home/valentin/projects/r)',),
                          args=['--mine', 'Gone Chat'])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_mine_with_no_readable_checkout_says_zero_rows_proves_nothing(self):
        result = self.cli([], chats=('Owner (live-x, claude, /home/valentin/projects/gone)',),
                          args=['--mine', 'Owner'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('0 rows proves nothing', result.stderr)

    def test_repo_filter(self):
        views = [view(1, repo='o/r', branch='owner-thing'), view(2, repo='o/one', branch='owner-thing')]
        result = self.cli(views, chats=('Owner (live-x, claude, /home/valentin/projects/r)',),
                          args=['--repo', 'o/r'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('o/r#1', result.stdout)
        self.assertNotIn('o/one#2', result.stdout)

    def test_json_output(self):
        views = [view(1, repo='o/r', branch='owner-thing')]
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'queue.json'
            result = self.cli(views, args=['--json', str(out)])
            self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(len(data['rows']), 1)
            self.assertIn('counts', data)
            self.assertEqual(data['rows'][0]['number'], 1)

    def test_billing_fixture_reaches_the_table(self):
        pr = view(1, repo='o/r', branch='owner-thing', checks='red')
        runs = [{'output': {'title': 'The job was not started because recent account payments have failed'}}]
        result = self.cli([pr], checks=[(pr, runs)])
        self.assertIn('BILLING', result.stdout, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
