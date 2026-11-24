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
import unittest
from unittest.mock import patch

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
        self.routes.write_text(json.dumps(routes))
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
        spent = len(self.calls())
        self.assertEqual(spent, 2)
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

    def test_fix_adds_the_repo_name_to_its_ruleset(self):
        ruleset = {'id': 7, 'name': 'main', 'target': 'branch', 'enforcement': 'active',
                   'conditions': {'ref_name': {'include': ['refs/heads/main'], 'exclude': []}},
                   'rules': [{'type': 'required_status_checks',
                              'parameters': {'strict_required_status_checks_policy': True,
                                             'required_status_checks': [{'context': 'build'}]}}]}
        self.answer([missing_route(PROTECTION), ok_route(RULES, []),
                     ok_route('user', {'login': 'valentinyeo'}),
                     ok_route('repos/valentinyeo/vstack/rulesets/7', ruleset),
                     ok_route('repos/valentinyeo/vstack/rulesets', [{'id': 7, 'name': 'main'}])])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main', '--fix')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('now requires verifier in ruleset main (7)', done.stdout)
        writes = [call for call in self.calls() if call['argv'][:2] == ['api', '-X']]
        contexts = [check['context'] for check in
                    writes[0]['input']['rules'][0]['parameters']['required_status_checks']]
        self.assertEqual(contexts, ['build', 'verifier'])


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
    def test_fix_adds_the_check_to_classic_protection(self):
        self.answer([ok_route(PROTECTION, {'strict': True, 'contexts': ['build']}),
                     ok_route(RULES, []),
                     ok_route('user', {'login': 'valentinyeo'})])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main', '--fix')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('fixed: valentinyeo/vstack main now requires pstack-verifier '
                      'in classic branch protection', done.stdout)
        writes = [call for call in self.calls() if call['argv'][:2] == ['api', '-X']]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['input'], {'strict': True,
                                              'contexts': ['build', 'pstack-verifier']})

    def test_fix_updates_the_ruleset_that_already_covers_the_branch(self):
        ruleset = {'id': 7, 'name': 'main', 'target': 'branch', 'enforcement': 'active',
                   'conditions': {'ref_name': {'include': ['refs/heads/main'], 'exclude': []}},
                   'rules': [{'type': 'required_status_checks',
                              'parameters': {'strict_required_status_checks_policy': True,
                                             'required_status_checks': [{'context': 'build'}]}}]}
        self.answer([missing_route(PROTECTION), ok_route(RULES, []),
                     ok_route('user', {'login': 'valentinyeo'}),
                     ok_route('repos/valentinyeo/vstack/rulesets/7', ruleset),
                     ok_route('repos/valentinyeo/vstack/rulesets', [{'id': 7, 'name': 'main'}])])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main', '--fix')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('fixed: valentinyeo/vstack main now requires pstack-verifier '
                      'in ruleset main (7)', done.stdout)
        writes = [call for call in self.calls() if call['argv'][:2] == ['api', '-X']]
        self.assertEqual(len(writes), 1)
        contexts = [check['context'] for check in
                    writes[0]['input']['rules'][0]['parameters']['required_status_checks']]
        self.assertEqual(contexts, ['build', 'pstack-verifier'])
        self.assertTrue(writes[0]['input']['rules'][0]['parameters']
                        ['strict_required_status_checks_policy'])

    def test_fix_creates_a_ruleset_when_the_repo_has_none(self):
        self.answer([missing_route(PROTECTION), ok_route(RULES, []),
                     ok_route('user', {'login': 'valentinyeo'}),
                     ok_route('repos/valentinyeo/vstack/rulesets', [])])
        done = self.run_gate('--repo', 'valentinyeo/vstack', '--branch', 'main', '--fix')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('in a new ruleset "merge gate"', done.stdout)
        writes = [call for call in self.calls() if call['argv'][:2] == ['api', '-X']]
        self.assertEqual(writes[0]['input']['conditions']['ref_name']['include'],
                         ['~DEFAULT_BRANCH'])
        self.assertEqual(writes[0]['input']['rules'][0]['type'], 'required_status_checks')

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
                                          'required': ['build', 'pstack-verifier']}]})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn('merge gate', done.stdout)

    def test_a_fixture_without_gates_reads_no_github(self):
        self.answer([])
        done = self.run_drain({'rows': [doing('VSTA-188')]})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_vstack_fixture_passes_on_the_verifier_name(self):
        self.answer([])
        done = self.run_drain({'rows': [doing('VSTA-188')],
                               'gates': [{'repo': 'valentinyeo/vstack', 'branch': 'main',
                                          'required': ['build', 'verifier']}]})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn('merge gate', done.stdout)

    def test_a_vstack_fixture_fails_on_the_pstack_name_only(self):
        self.answer([])
        done = self.run_drain({'rows': [doing('VSTA-188')],
                               'gates': [{'repo': 'valentinyeo/vstack', 'branch': 'main',
                                          'required': ['build', 'pstack-verifier']}]})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('merge gate missing: valentinyeo/vstack main', done.stdout)


if __name__ == '__main__':
    unittest.main()
