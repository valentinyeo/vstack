"""VSTA-193: vstack's own verifier check counts as the PASS on a merged PR.

vstack's verifier is the `verifier` job of .github/workflows/pstack-sources.yml (house
delta `github-actions-verifier` in skills/pstack-diff/house.txt), not pstack's
`pstack-verifier`. The board sync read only the pstack name, so vstack PRs #344, #342,
#337 and #315 merged with a real PASS on their merged head and their cards went back to
Todo as "merged without PASS".

The shapes here are #344's real merge: head b5fa03a, `verifier` SUCCESS on that head.
"""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'skills/hypertask-work/reconcile'

VSTACK = 'valentinyeo/vstack'
TOKEN_LADDER = 'valentinyeo/token-ladder'
POSTBOX = 'valentinyeo/postbox'
HOUSE_RULES = 'valentinyeo/house-rules'
HYPER = 'hypertask-ai/hypertask'
# PR #344's merged head, and the head of the PR that followed it.
HEAD = 'b5fa03a125b6177d7e04f4001d2f50d1caf9f002'
OTHER_HEAD = '9aa542a1f0e7f0a3c2b0d2b8f5e4a5a5c1d3b7e9'
RUN = 45390544671


def load_reconcile():
    loader = importlib.machinery.SourceFileLoader('fleet_reconcile', str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


r = load_reconcile()


def check(name, oid=HEAD, status='COMPLETED', conclusion='SUCCESS', run=RUN):
    return {'__typename': 'CheckRun', 'name': name, 'status': status, 'conclusion': conclusion,
            'checkSuite': {'commit': {'oid': oid}, 'workflowRun': {'databaseId': run}}}


def pr_344_checks():
    """The rollup GitHub returned for #344 on its merged head,
    minus the checks the repo has since dropped."""
    return [check('regression'), check('skill-lint'), check('hook-self-tests'),
            check('skills'),
            check('verifier', run=45390544671),
            check('verify-vstack', run=45390544811),
            check('pacer-check', run=45390544811)]


def pr_344_node():
    return {'url': 'https://github.com/valentinyeo/vstack/pull/344',
            'state': 'MERGED', 'mergedAt': '2026-11-24T12:21:33Z',
            'headRefOid': HEAD, 'baseRefOid': 'd02e1180000000000000000000000000000000ff',
            'mergeable': 'UNKNOWN', 'author': {'login': 'valentinyeo'},
            'commits': {'last': {'nodes': [{'commit': {'committedDate': '2026-11-24T11:59:00Z'}}]}},
            'statusCheckRollup': {'state': 'SUCCESS',
                                  'contexts': {'pageInfo': {'hasNextPage': False},
                                               'nodes': pr_344_checks()}},
            'comments': {'totalCount': 0, 'nodes': []}}


class VerifierCheckNames(unittest.TestCase):
    """The check run name is the repo's own, so vstack reads `verifier` and nobody else."""

    def setUp(self):
        self.runs = []

        def hosted(repo, run_id):
            self.runs.append((repo, run_id))
            return {'jobs': True, 'self_hosted': False}

        self._saved = (r.jobs_evidence, r.verifier_policy)
        r.jobs_evidence = hosted
        r.verifier_policy = lambda repo, ref: None

    def tearDown(self):
        r.jobs_evidence, r.verifier_policy = self._saved

    def test_pr_344_counts_as_passed_on_its_merged_head(self):
        self.assertTrue(r.pstack_pass_on_head(pr_344_checks(), HEAD, VSTACK))

    def test_a_verifier_on_another_head_does_not_count(self):
        """#342's verdict on its own head is not a PASS for #344."""
        checks = [check('verifier', oid=OTHER_HEAD)]
        self.assertFalse(r.pstack_pass_on_head(checks, HEAD, VSTACK))

    def test_the_verifier_name_counts_in_no_other_repo(self):
        self.assertFalse(r.pstack_pass_on_head(pr_344_checks(), HEAD, HYPER))

    def test_token_ladder_takes_the_pstack_name_after_its_rename(self):
        """token-ladder PR 47 renamed its verifier job, so the default name counts there."""
        self.assertTrue(r.pstack_pass_on_head([check('pstack-verifier')], HEAD, TOKEN_LADDER))
        self.assertFalse(r.pstack_pass_on_head([check('verifier')], HEAD, TOKEN_LADDER))

    def test_postbox_counts_verify_verdict_as_the_pass(self):
        """VSTA-196: postbox posts `verify-verdict` and requires it on main."""
        self.assertTrue(r.pstack_pass_on_head([check('verify-verdict')], HEAD, POSTBOX))
        self.assertFalse(r.pstack_pass_on_head([check('pstack-verifier')], HEAD, POSTBOX))

    def test_house_rules_counts_its_reusable_workflow_check_as_the_pass(self):
        """house-rules' verifier is a reusable workflow, so GitHub names the check
        `skill-lint / pstack-verifier` and main requires exactly that (VSTA-196)."""
        self.assertTrue(r.pstack_pass_on_head([check('skill-lint / pstack-verifier')],
                                              HEAD, HOUSE_RULES))
        self.assertFalse(r.pstack_pass_on_head([check('pstack-verifier')], HEAD, HOUSE_RULES))

    def test_pstack_verifier_still_counts_where_it_is_the_check(self):
        self.assertTrue(r.pstack_pass_on_head([check('pstack-verifier')], HEAD, HYPER))

    def test_a_no_verdict_failure_does_not_count(self):
        """The verifier job concludes FAILURE on NO VERDICT, which is not a pass."""
        checks = [check('verifier', conclusion='FAILURE')]
        self.assertFalse(r.pstack_pass_on_head(checks, HEAD, VSTACK))

    def test_a_verifier_still_running_does_not_count(self):
        checks = [check('verifier', status='IN_PROGRESS', conclusion=None)]
        self.assertFalse(r.pstack_pass_on_head(checks, HEAD, VSTACK))

    def test_a_self_hosted_verifier_job_does_not_count(self):
        r.jobs_evidence = lambda repo, run_id: {'jobs': True, 'self_hosted': True}
        self.assertFalse(r.pstack_pass_on_head(pr_344_checks(), HEAD, VSTACK))

    def test_the_merged_pull_read_finds_the_pass(self):
        """The read the board sync makes, on the node GitHub returns for #344."""
        pull = r.pull_from_node(VSTACK, 344, pr_344_node())
        self.assertEqual(pull.state, 'MERGED')
        self.assertTrue(pull.passed)

    def test_the_card_plans_done_with_pass(self):
        """A card in Checks whose merged PR reads PASS plans Done, not back to Todo."""
        pull = r.pull_from_node(VSTACK, 344, pr_344_node())
        facts = r.Facts('Checks', 8000, False, (pull,))
        self.assertEqual(r.target(facts, board=r.BOARDS[13556]), ('Done', 'merged with PASS'))


if __name__ == '__main__':
    unittest.main()
