"""merge-gate: every repo a chat ships from must require the verifier check.

The real GitHub answers are replayed by a fake `gh` on PATH, so the branch-protection
read, the ruleset read, the cache and `--fix` writes are all exercised as they ship.
"""
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
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / 'skills/board-drain/merge-gate'
DRAIN = ROOT / 'skills/board-drain/drain-check'
NOW = 1800000000

FAKE_GH = '''#!/usr/bin/env python3
import json
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
entry = {"argv": sys.argv[1:]}
if "--input" in sys.argv:
    name = sys.argv[sys.argv.index("--input") + 1]
    entry["input"] = json.loads(Path(name).read_text())
with (here / "gh.log").open("a") as handle:
    handle.write(json.dumps(entry) + "\\n")
routes = json.loads((here / "routes.json").read_text())
call = " ".join(sys.argv[1:])
for route in routes:
    if all(part in call for part in route["match"]):
        if route.get("apply"):
            payload = entry["input"]
            if sys.argv[sys.argv.index("-X") + 1] == "PATCH":
                updated = {"match": ["branches/main/protection/required_status_checks"],
                           "stdout": json.dumps(payload)}
            else:
                updated = {"match": ["rules/branches/main"],
                           "stdout": json.dumps(payload["rules"])}
            (here / "routes.json").write_text(json.dumps([updated, *routes]))
        if route.get("stderr"):
            sys.stderr.write(route["stderr"])
        sys.stdout.write(route.get("stdout") or "")
        sys.exit(route.get("code", 0))
sys.stderr.write("no route: " + call + "\\n")
sys.exit(1)
'''


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


gate = load('merge_gate_test', GATE)
drain = load('board_drain_check_merge_gate', DRAIN)


def ok_route(path, body):
    return {'match': [path], 'stdout': json.dumps(body)}


def missing_route(path, error='Branch not protected'):
    return {'match': [path], 'code': 1, 'stderr': f'gh: {error} (HTTP 404)\n'}


PROTECTION = 'branches/main/protection/required_status_checks'
RULES = 'rules/branches/main'
CEO_PROTECTION = 'branches/master/protection/required_status_checks'
CEO_RULES = 'rules/branches/master'
# GitHub's own annotation when it refuses to start a private repo's job (VSTA-198).
BILLING_NOTE = ('The job was not started because recent account payments have failed or '
                'your spending limit needs to be increased. Please check the \'Billing & '
                "plans' section in your settings")
WAITS = ('gate waits: valentinyeo/ceo master '
         '(GitHub billing blocks private checks; waits on Valentin)')
# What `gh api repos/<owner>/<name>` answers unless a test routes it itself.
REPO = {'private': False, 'default_branch': 'main'}


class GateCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        fake = self.bin / 'gh'
        fake.write_text(FAKE_GH)
        fake.chmod(0o755)
        self.routes = self.bin / 'routes.json'
        self.log = self.bin / 'gh.log'
        self.env = {'HOME': str(self.directory / 'home'),
                    'PATH': f'{self.bin}:/usr/bin:/bin',
                    'RECONCILE_CACHE': str(self.directory / 'cache.json')}

    def answer(self, routes):
        """Serve these routes, then a public repo for the read every missing gate makes."""
        self.routes.write_text(json.dumps([*routes, {'match': ['repos/'],
                                                     'stdout': json.dumps(REPO)}]))
        self.log.unlink(missing_ok=True)

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]

    def run_gate(self, *argv):
        return subprocess.run([sys.executable, str(GATE), *argv], capture_output=True,
                              text=True, env=self.env, timeout=60)

    def run_drain(self, payload):
        fixture = self.directory / 'fixture.json'
        fixture.write_text(json.dumps(payload))
        return subprocess.run([sys.executable, str(DRAIN), '--board', '13556',
                               '--label', 'Vstack', '--fixture', str(fixture),
                               '--now', '2027-01-15T00:00:00Z', '--no-load'],
                              capture_output=True, text=True, env=self.env, timeout=60)


class GateReadTest(GateCase):
    def test_classic_protection_that_requires_the_check_passes(self):
        self.answer([ok_route(PROTECTION, {'strict': True, 'contexts': ['build', 'pstack-verifier']}),
                     ok_route(RULES, [])])
        done = self.run_gate('--repo', 'valentinyeo/multiprompt', '--branch', 'main')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate ok: valentinyeo/multiprompt main')

    def test_classic_protection_without_the_check_fails(self):
        self.answer([ok_route(PROTECTION, {'strict': False, 'contexts': ['build', 'lint']}),
                     ok_route(RULES, [])])
        done = self.run_gate('--repo', 'valentinyeo/multiprompt', '--branch', 'main')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate missing: valentinyeo/multiprompt main')

    def test_a_ruleset_that_requires_the_check_passes(self):
        rules = [{'type': 'required_status_checks',
                  'parameters': {'required_status_checks': [{'context': 'pstack-verifier'}]}}]
        self.answer([missing_route(PROTECTION), ok_route(RULES, rules)])
        done = self.run_gate('--repo', 'valentinyeo/multiprompt-android', '--branch', 'main')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate ok: valentinyeo/multiprompt-android main')

    def test_a_ruleset_with_other_checks_only_fails(self):
        rules = [{'type': 'pull_request',
                  'parameters': {}},
                 {'type': 'required_status_checks',
                  'parameters': {'required_status_checks': [{'context': 'test'}]}}]
        self.answer([missing_route(PROTECTION), ok_route(RULES, rules)])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate missing: valentinyeo/vstack main')

    def test_an_unprotected_branch_has_no_gate_and_no_error(self):
        self.answer([missing_route(PROTECTION), ok_route(RULES, [])])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertNotIn('Traceback', done.stderr)

    def test_a_gate_that_cannot_be_read_exits_2(self):
        self.answer([{'match': [PROTECTION], 'code': 1, 'stderr': 'gh: Server Error (HTTP 500)\n'},
                     ok_route(RULES, [])])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main')
        self.assertEqual(done.returncode, 2)
        self.assertIn('HTTP 500', done.stderr)

    def test_a_second_run_within_the_hour_costs_no_github_call(self):
        self.answer([ok_route(PROTECTION, {'strict': False, 'contexts': ['build']}),
                     ok_route(RULES, [])])
        first = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main')
        self.assertEqual(first.returncode, 1, first.stderr)
        # Protection, rulesets and the repo it takes privacy from: one read each.
        spent = len(self.calls())
        self.assertEqual(spent, 3)
        second = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main')
        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual(len(self.calls()), spent)

    def test_many_repos_report_one_line_each(self):
        self.answer([ok_route(PROTECTION, {'strict': False, 'contexts': ['pstack-verifier']}),
                     ok_route(RULES, [])])
        done = self.run_gate('--repo', 'valentinyeo/a', '--repo', 'valentinyeo/b', '--branch', 'main')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines(),
                         ['gate ok: valentinyeo/a main', 'gate ok: valentinyeo/b main'])

    def test_the_command_needs_a_board_or_a_repo(self):
        self.answer([])
        done = self.run_gate()
        self.assertEqual(done.returncode, 2)
        self.assertIn('--board or --repo', done.stderr)


class BillingTest(GateCase):
    """A private repo GitHub bills cannot run checks for waits, and never gets --fixed.

    The real case is valentinyeo/ceo on master: PR #82's pstack-verifier job was never
    started because the account's payments failed. Requiring that check would block
    every merge, so the gate reports the wait instead of a missing gate.
    """

    def answer_ceo(self, private=True, note=BILLING_NOTE, annotated=1):
        self.answer([
            missing_route(CEO_PROTECTION),
            ok_route(CEO_RULES, []),
            ok_route('actions/runs', {'total_count': 1, 'workflow_runs': [
                {'id': 45422309359, 'check_suite_id': 9002, 'conclusion': 'failure'}]}),
            ok_route('check-suites/9002/check-runs', {'total_count': 1, 'check_runs': [
                {'id': 777, 'name': 'skill-lint / pstack-verifier', 'conclusion': 'failure',
                 'output': {'annotations_count': annotated}}]}),
            ok_route('check-runs/777/annotations', [{'message': note}]),
            # Last: this path is a prefix of every read above it.
            ok_route('repos/valentinyeo/ceo', {'private': private,
                                              'default_branch': 'master'}),
        ])

    def test_a_private_repo_blocked_by_billing_waits(self):
        self.answer_ceo()
        done = self.run_gate('--repo', 'valentinyeo/ceo', '--branch', 'master')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.stdout.strip(), WAITS)

    def test_fix_refuses_a_billing_blocked_private_repo(self):
        self.answer_ceo()
        done = self.run_gate('--repo', 'valentinyeo/ceo', '--branch', 'master', '--fix')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('skipped: valentinyeo/ceo master cannot run checks (GitHub billing',
                      done.stdout)
        self.assertEqual([call for call in self.calls() if '-X' in call['argv']], [])

    def test_the_billing_read_is_cached_with_the_gate(self):
        self.answer_ceo()
        first = self.run_gate('--repo', 'valentinyeo/ceo', '--branch', 'master')
        self.assertEqual(first.returncode, 0, first.stderr)
        spent = len(self.calls())
        second = self.run_gate('--repo', 'valentinyeo/ceo', '--branch', 'master')
        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual(len(self.calls()), spent)

    def test_a_gate_saved_before_billing_existed_is_read_again(self):
        self.answer_ceo()
        # The shape an older merge-gate cached an hour ago: a miss with no billing answer.
        Path(self.env['RECONCILE_CACHE']).write_text(json.dumps({
            'merge-gate:valentinyeo/ceo@master':
                {'mode': 'none', 'contexts': [], 'at': int(time.time())}}))
        done = self.run_gate('--repo', 'valentinyeo/ceo', '--branch', 'master')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.stdout.strip(), WAITS)

    def test_a_public_repo_still_reads_nothing_about_billing(self):
        self.answer_ceo(private=False)
        done = self.run_gate('--repo', 'valentinyeo/ceo', '--branch', 'master')
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate missing: valentinyeo/ceo master')
        self.assertEqual([call for call in self.calls() if 'actions' in ' '.join(call['argv'])],
                         [])

    def test_a_private_repo_whose_checks_run_is_still_missing(self):
        self.answer_ceo(note='Build failed: 2 tests', annotated=1)
        done = self.run_gate('--repo', 'valentinyeo/ceo', '--branch', 'master')
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate missing: valentinyeo/ceo master')

    def test_a_check_run_with_no_annotation_is_still_missing(self):
        self.answer_ceo(annotated=0)
        done = self.run_gate('--repo', 'valentinyeo/ceo', '--branch', 'master')
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate missing: valentinyeo/ceo master')


def fake_gate(record):
    return lambda repo, branch, now=None: (record if repo == 'valentinyeo/ceo'
                                           else {'mode': 'none', 'contexts': []})


class GateFindingsBillingTest(unittest.TestCase):
    """drain-check must not read a billing wait as a gate a chat can fix."""

    def findings(self, record):
        board = gate.board_object(13556)
        with patch.object(gate, 'repos_for', return_value=(('valentinyeo/ceo', 'master'),
                                                          ('valentinyeo/vstack', 'main'))), \
                patch.object(gate, 'gate', side_effect=fake_gate(record)):
            return gate.gate_findings(board, NOW)

    def test_a_billing_wait_produces_no_finding(self):
        findings = self.findings({'mode': 'none', 'contexts': [], 'billing': True})
        self.assertEqual([text for _kind, text in findings],
                         ['merge gate missing: valentinyeo/vstack main; run '
                          'skills/board-drain/merge-gate --board 13556 --fix.'])


class VerifierNameTest(GateCase):
    """The gate takes each repo's verifier name from reconcile's one table.

    vstack's verifier answers as `verifier` (VSTA-193), so a gate that hard-coded
    `pstack-verifier` would call vstack ungated when it is gated, and a repo that
    requires nothing must still fail.
    """

    def test_vstack_requires_its_own_verifier_name(self):
        self.answer([ok_route(PROTECTION, {'strict': False, 'contexts': ['build', 'verifier']}),
                     ok_route(RULES, [])])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate ok: valentinyeo/vstack main')

    def test_vstack_does_not_accept_the_pstack_name(self):
        self.answer([ok_route(PROTECTION, {'strict': False, 'contexts': ['pstack-verifier']}),
                     ok_route(RULES, [])])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate missing: valentinyeo/vstack main')

    def test_a_repo_that_requires_nothing_fails(self):
        self.answer([ok_route(PROTECTION, {'strict': False, 'contexts': []}),
                     ok_route(RULES, [])])
        done = self.run_gate('--repo', 'valentinyeo/multiprompt', '--branch', 'main')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(done.stdout.strip(), 'gate missing: valentinyeo/multiprompt main')

    def test_the_name_is_reconciles_table_read_live(self):
        self.assertEqual(gate.check_names('valentinyeo/vstack'),
                         tuple(gate.reconcile.verifier_check_names('valentinyeo/vstack')))
        with patch.dict(gate.reconcile.VERIFIER_CHECKS, {'someone/app': ('own-verifier',)},
                        clear=True):
            self.assertEqual(gate.check_names('someone/app'), ('own-verifier',))
            self.assertEqual(gate.required_name('someone/app'), 'own-verifier')
            self.assertEqual(gate.check_names('valentinyeo/vstack'), ('pstack-verifier',))


class ReposForBoardTest(GateCase):
    def write_facts(self, facts):
        """Save one board's facts where this process's reconcile reads them."""
        Path(os.environ['RECONCILE_CACHE']).write_text(
            json.dumps({'board-facts-13556.json': facts}))

    def setUp(self):
        super().setUp()
        patcher = patch.dict(os.environ,
                             {'RECONCILE_CACHE': self.env['RECONCILE_CACHE']})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_board_config_names_its_repos(self):
        pairs = gate.repos_for(gate.board_object(15))
        self.assertIn(('hypertask-ai/hypertask', 'production'), pairs)
        self.assertIn(('valentinyeo/vstack', 'main'), pairs)

    def test_a_board_without_repos_takes_them_from_its_saved_facts(self):
        facts = {'repos': ['valentinyeo/vstack', 'hypertask-ai/hypertask'],
                 'tickets': {'VSTA-1': {'pulls': [
                     {'url': 'https://github.com/valentinyeo/vstack/pull/1',
                      'repository': {'nameWithOwner': 'valentinyeo/vstack'},
                      'baseRefName': 'main'},
                     {'url': 'https://github.com/hypertask-ai/hypertask/pull/2',
                      'repository': {'nameWithOwner': 'hypertask-ai/hypertask'},
                      'baseRefName': 'production'}]}}}
        self.write_facts(facts)
        self.assertEqual(gate.fact_repos(13556),
                         (('valentinyeo/vstack', 'main'),
                          ('hypertask-ai/hypertask', 'production')))

    def test_a_repo_from_facts_keeps_its_release_branch(self):
        facts = {'repos': ['hypertask-ai/hypertask'], 'tickets': {}}
        self.write_facts(facts)
        self.assertEqual(gate.fact_repos(13556), (('hypertask-ai/hypertask', 'production'),))


class FixTest(GateCase):
    def assert_fixed_gate_cached(self):
        with patch.dict(os.environ, self.env), \
                patch.object(gate, 'repos_for', return_value=BOARD_REPOS), \
                patch.object(gate, 'gh_json', side_effect=AssertionError('unexpected gate read')):
            self.assertEqual(gate.gate_findings(gate.board_object(13556), gate.time.time() + 1,
                                                repos={'valentinyeo/vstack'}), [])

    def setUp(self):
        super().setUp()
        (self.bin / 'gh').rename(self.bin / 'gh.real')
        wrapper = self.bin / 'gh'
        wrapper.write_text((ROOT / 'tools/gh-wrapper/gh').read_text())
        wrapper.chmod(0o755)
        self.env.update(GH_REAL=str(self.bin / 'gh.real'),
                        HT_GH_CACHE_DIR=str(self.directory / 'gh-cache'),
                        GH_CALL_LOG=str(self.directory / 'calls.tsv'))

    def test_exit_zero_printing_usage_does_not_claim_a_fix(self):
        for method in ('PATCH', 'PUT', 'POST'):
            with self.subTest(method=method):
                Path(self.env['RECONCILE_CACHE']).unlink(missing_ok=True)
                self.env['HT_GH_CACHE_DIR'] = str(self.directory / f'gh-cache-{method}')
                classic = (ok_route(PROTECTION, {'strict': False, 'contexts': ['build']})
                           if method == 'PATCH' else missing_route(PROTECTION))
                rulesets = ([{'id': 7}] if method == 'PUT' else [])
                self.answer([
                    {'match': ['-X'], 'stdout': 'Usage: gh api <endpoint> [flags]\n'},
                    classic, ok_route(RULES, []),
                    ok_route('user', {'login': 'valentinyeo'}),
                    ok_route('repos/valentinyeo/vstack/rulesets/7',
                             {'id': 7, 'conditions': {'ref_name': {
                                 'include': ['refs/heads/main']}}, 'rules': []}),
                    ok_route('repos/valentinyeo/vstack/rulesets', rulesets),
                ])
                done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main', '--fix')
                self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
                self.assertIn('failed: valentinyeo/vstack main still does not require verifier',
                              done.stdout)
                self.assertNotIn('fixed:', done.stdout)
                saved = json.loads(Path(self.env['RECONCILE_CACHE']).read_text())
                self.assertNotIn('merge-gate:valentinyeo/vstack@main', saved)

    def test_fix_caches_the_fresh_record_not_the_expected_write(self):
        fresh = dict(gate_record('build', 'verifier', 'server-check'), at=NOW)
        with patch.object(gate, 'owner_login', return_value='valentinyeo'), \
                patch.object(gate, 'api_write'), \
                patch.object(gate, 'gate', return_value=fresh) as read, \
                patch.object(gate.reconcile, 'cache_write') as write:
            result = gate.fix('valentinyeo/vstack', 'main', gate_record('build'))
        self.assertTrue(result.startswith('fixed:'), result)
        read.assert_called_once_with('valentinyeo/vstack', 'main', fresh=True)
        write.assert_called_once_with('merge-gate:valentinyeo/vstack@main', fresh)

    def test_fix_adds_the_check_to_classic_protection(self):
        self.answer([{'match': ['-X PATCH'], 'apply': True},
                     ok_route(PROTECTION, {'strict': True, 'contexts': ['build']}),
                     ok_route(RULES, []),
                     ok_route('user', {'login': 'valentinyeo'})])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main', '--fix')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('fixed: valentinyeo/vstack main now requires verifier '
                      'in classic branch protection', done.stdout)
        writes = [call for call in self.calls() if call['argv'][:2] == ['api', '-X']]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['input'], {'strict': True,
                                              'contexts': ['build', 'verifier']})
        self.assert_fixed_gate_cached()

    def test_fix_updates_the_ruleset_that_already_covers_the_branch(self):
        ruleset = {'id': 7, 'name': 'main', 'target': 'branch', 'enforcement': 'active',
                   'conditions': {'ref_name': {'include': ['refs/heads/main'], 'exclude': []}},
                   'rules': [{'type': 'required_status_checks',
                              'parameters': {'strict_required_status_checks_policy': True,
                                             'required_status_checks': [{'context': 'build'}]}}]}
        self.answer([{'match': ['-X PUT'], 'apply': True},
                     missing_route(PROTECTION), ok_route(RULES, []),
                     ok_route('user', {'login': 'valentinyeo'}),
                     ok_route('repos/valentinyeo/vstack/rulesets/7', ruleset),
                     ok_route('repos/valentinyeo/vstack/rulesets', [{'id': 7, 'name': 'main'}])])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main', '--fix')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('fixed: valentinyeo/vstack main now requires verifier '
                      'in ruleset main (7)', done.stdout)
        writes = [call for call in self.calls() if call['argv'][:2] == ['api', '-X']]
        self.assertEqual(len(writes), 1)
        contexts = [check['context'] for check in
                    writes[0]['input']['rules'][0]['parameters']['required_status_checks']]
        self.assertEqual(contexts, ['build', 'verifier'])
        self.assertTrue(writes[0]['input']['rules'][0]['parameters']
                        ['strict_required_status_checks_policy'])
        self.assert_fixed_gate_cached()

    def test_fix_creates_a_ruleset_when_the_repo_has_none(self):
        other = {'contexts': ['build'], 'at': NOW}
        Path(self.env['RECONCILE_CACHE']).write_text(json.dumps({
            'merge-gate:valentinyeo/other@main': other}))
        self.answer([{'match': ['-X POST'], 'apply': True},
                     missing_route(PROTECTION), ok_route(RULES, []),
                     ok_route('user', {'login': 'valentinyeo'}),
                     ok_route('repos/valentinyeo/vstack/rulesets', [])])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main', '--fix')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('in a new ruleset "merge gate"', done.stdout)
        writes = [call for call in self.calls() if call['argv'][:2] == ['api', '-X']]
        self.assertEqual(writes[0]['input']['conditions']['ref_name']['include'],
                         ['~DEFAULT_BRANCH'])
        self.assertEqual(writes[0]['input']['rules'][0]['type'], 'required_status_checks')
        self.assert_fixed_gate_cached()
        saved = json.loads(Path(self.env['RECONCILE_CACHE']).read_text())
        self.assertEqual(saved['merge-gate:valentinyeo/other@main'], other)
        self.assertEqual(saved['merge-gate:valentinyeo/vstack@main']['contexts'], ['verifier'])
        spent = len(self.calls())
        again = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main')
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn('gate ok:', again.stdout)
        self.assertEqual(len(self.calls()), spent)

    def test_a_failed_fix_does_not_cache_a_passing_gate(self):
        self.answer([{'match': ['-X', 'PATCH'], 'code': 1, 'stderr': 'write failed'},
                     ok_route(PROTECTION, {'strict': True, 'contexts': ['build']}),
                     ok_route(RULES, []),
                     ok_route('user', {'login': 'valentinyeo'})])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main', '--fix')
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertNotIn('fixed:', done.stdout)
        calls = self.calls()
        again = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main')
        self.assertEqual(again.returncode, 1, again.stderr)
        self.assertEqual(again.stdout.strip(), 'gate missing: valentinyeo/vstack main')
        self.assertEqual(self.calls(), calls)

    def test_fix_never_touches_a_hypertask_ai_repo(self):
        self.answer([missing_route('branches/production/protection/required_status_checks'),
                     ok_route('rules/branches/production', []),
                     ok_route('user', {'login': 'valentinyeo'})])
        done = self.run_gate('--repo', 'hypertask-ai/hypertask', '--branch', 'production', '--fix')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('skipped: hypertask-ai/hypertask production is hypertask-ai; report only',
                      done.stdout)
        self.assertEqual([call for call in self.calls() if call['argv'][:2] == ['api', '-X']], [])

    def test_fix_leaves_a_repo_this_account_does_not_own(self):
        self.answer([missing_route(PROTECTION), ok_route(RULES, []),
                     ok_route('user', {'login': 'valentinyeo'})])
        done = self.run_gate('--repo', 'someoneelse/app', '--branch', 'main', '--fix')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('skipped: someoneelse/app main is not owned by valentinyeo', done.stdout)
        self.assertEqual([call for call in self.calls() if '-X' in call['argv']], [])


def agent():
    return {'id': 6, 'email': '', 'displayName': 'Vstack Maintainer', 'type': 'agent',
            'agentId': '8658ed82-c372-4e10-8410-0989067bb08f',
            'agent': {'id': '8658ed82-c372-4e10-8410-0989067bb08f'}}


def doing(key, label='Vstack'):
    """A live Doing card: a fresh agent-held row, so no other rule fires."""
    return {'task': {'ticketNumber': key, 'projectId': 13556, 'section': 'Doing',
                     'labels': [{'name': label}], 'waitingOnUserId': None,
                     'blockerCommentId': None, 'updatedAt': '2027-01-14T23:50:00Z',
                     'assignees': [agent()]},
            'comments': []}


class DrainCheckGateTest(GateCase):
    def test_a_missing_gate_fails_the_check_and_names_the_fix(self):
        self.answer([])
        done = self.run_drain({'rows': [doing('VSTA-188')],
                               'gates': [{'repo': 'valentinyeo/vstack', 'branch': 'main',
                                          'required': ['build', 'lint']}]})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('merge gate missing: valentinyeo/vstack main; run '
                      'skills/board-drain/merge-gate --board 13556 --fix.', done.stdout)

    def test_a_gated_repo_adds_no_finding(self):
        self.answer([])
        done = self.run_drain({'rows': [doing('VSTA-188')],
                               'gates': [{'repo': 'valentinyeo/vstack', 'branch': 'main',
                                          'required': ['build', 'verifier']}]})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn('merge gate', done.stdout)

    def test_a_fixture_without_gates_reads_no_github(self):
        self.answer([])
        done = self.run_drain({'rows': [doing('VSTA-188')]})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_vstack_fixture_fails_on_the_pstack_name_only(self):
        self.answer([])
        done = self.run_drain({'rows': [doing('VSTA-188')],
                               'gates': [{'repo': 'valentinyeo/vstack', 'branch': 'main',
                                          'required': ['build', 'pstack-verifier']}]})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('merge gate missing: valentinyeo/vstack main', done.stdout)


# Board 13556 ships from three repos, but one chat's view usually touches only one.
BOARD_REPOS = (('valentinyeo/ceo', 'master'), ('valentinyeo/house-rules', 'main'),
               ('valentinyeo/vstack', 'main'))


def gate_record(*contexts):
    return {'mode': 'classic', 'classic': list(contexts), 'strict': False,
            'contexts': list(contexts)}


class ViewReposGateTest(GateCase):
    """A gate is judged where the chat's own view ships, never where another chat does."""

    def findings(self, repos, *contexts):
        with patch.object(gate, 'repos_for', return_value=BOARD_REPOS), \
                patch.object(gate, 'gate', return_value=gate_record(*contexts)) as read:
            found = gate.gate_findings(gate.board_object(13556), NOW, repos=repos)
        return found, [item[0][:2] for item in read.call_args_list]

    def test_a_view_whose_work_is_only_in_vstack_never_judges_ceo(self):
        found, read = self.findings({'valentinyeo/vstack'}, 'verifier')
        self.assertEqual(found, [])
        self.assertEqual(read, [('valentinyeo/vstack', 'main')])

    def test_a_missing_gate_in_the_views_own_repo_is_still_reported(self):
        found, read = self.findings({'valentinyeo/vstack'}, 'build', 'lint')
        self.assertEqual(read, [('valentinyeo/vstack', 'main')])
        self.assertEqual([text for _, text in found],
                         ['merge gate missing: valentinyeo/vstack main; run '
                          'skills/board-drain/merge-gate --board 13556 --fix.'])

    def test_a_repo_the_board_does_not_ship_from_is_never_judged(self):
        found, read = self.findings({'someoneelse/app'})
        self.assertEqual(found, [])
        self.assertEqual(read, [])

    def test_a_view_with_no_prs_reads_no_gate(self):
        found, read = self.findings(set())
        self.assertEqual(found, [])
        self.assertEqual(read, [])

    def test_a_board_wide_judgement_still_reads_every_repo(self):
        # merge-gate's own CLI passes no repos: it still judges every repo the board ships from.
        found, read = self.findings(None)
        self.assertEqual(read, list(BOARD_REPOS))
        self.assertEqual(len(found), 3)


if __name__ == '__main__':
    unittest.main()
