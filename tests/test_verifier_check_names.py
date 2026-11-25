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
# Real hypertask-ai/hypertask#3835 merged head and pstack-verifier workflow run.
HYPER_HEAD = '624ddfc863fce1d78bdf934791dd99d3ff38af78'
HYPER_RUN = 45482013810


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


def status_context(context, oid=HYPER_HEAD, state='SUCCESS', repo=HYPER, run=HYPER_RUN, attempt=1):
    """The StatusContext shape hypertask-ai/hypertask posts for pstack-verifier."""
    return {'__typename': 'StatusContext', 'context': context, 'state': state,
            'targetUrl': f'https://github.com/{repo}/actions/runs/{run}/attempts/{attempt}',
            'commit': {'oid': oid}}


def hyper_3835_node(with_pass=True):
    nodes = [check('ci-tests', oid=HYPER_HEAD, run=45481972974),
             status_context('ai-review')]
    if with_pass:
        nodes.append(status_context('pstack-verifier'))
    return {'url': 'https://github.com/hypertask-ai/hypertask/pull/3835',
            'state': 'MERGED', 'mergedAt': '2026-11-24T21:02:00Z',
            'createdAt': '2026-11-24T20:30:00Z',
            'headRefOid': HYPER_HEAD, 'baseRefOid': '2050d1af5172e0f6bbf07d4411f1a694f169d9f0',
            'mergeable': 'UNKNOWN', 'author': {'login': 'valentinyeo'},
            'commits': {'nodes': [{'commit': {'committedDate': '2026-11-24T20:32:00Z'}}]},
            'statusCheckRollup': {'state': 'SUCCESS',
                                  'contexts': {'pageInfo': {'hasNextPage': False},
                                               'nodes': nodes}},
            'comments': {'totalCount': 0, 'nodes': []}}


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

    def test_hypertask_status_context_pass_plans_done_from_qa(self):
        """hypertask-ai/hypertask posts pstack-verifier as a StatusContext on the head."""
        pull = r.pull_from_node(HYPER, 3835, hyper_3835_node(with_pass=True))
        self.assertEqual(pull.state, 'MERGED')
        self.assertTrue(pull.passed)
        self.assertEqual(self.runs, [(HYPER, HYPER_RUN)])
        self.assertEqual(r.target(r.Facts('QA', 8000, False, (pull,)), board=r.BOARDS[15]),
                         ('No Flag', 'merged with PASS'))

    def test_hypertask_merged_without_pass_in_qa_plans_backlog(self):
        pull = r.pull_from_node(HYPER, 3835, hyper_3835_node(with_pass=False))
        self.assertEqual(pull.state, 'MERGED')
        self.assertFalse(pull.passed)
        self.assertEqual(r.target(r.Facts('QA', 8000, False, (pull,)), board=r.BOARDS[15]),
                         ('Backlog', 'merged without PASS: rule break; owner must verify'))

    def test_status_context_rejects_bad_head_state_repo_name_or_self_hosted(self):
        self.assertFalse(r.pstack_pass_on_head(
            [status_context('pstack-verifier', oid=OTHER_HEAD)], HYPER_HEAD, HYPER))
        self.assertFalse(r.pstack_pass_on_head(
            [status_context('pstack-verifier', state='FAILURE')], HYPER_HEAD, HYPER))
        self.assertFalse(r.pstack_pass_on_head(
            [status_context('pstack-verifier', repo=VSTACK)], HYPER_HEAD, HYPER))
        self.assertFalse(r.pstack_pass_on_head(
            [status_context('verifier')], HYPER_HEAD, HYPER))
        bad_url = {**status_context('pstack-verifier'), 'targetUrl': 'https://example.com/ok'}
        self.assertFalse(r.pstack_pass_on_head([bad_url], HYPER_HEAD, HYPER))
        r.jobs_evidence = lambda repo, run_id: {'jobs': True, 'self_hosted': True}
        self.assertFalse(r.pstack_pass_on_head(
            [status_context('pstack-verifier')], HYPER_HEAD, HYPER))


def gh_comment(body, login='github-actions', when='2026-11-24T12:00:00Z', number=1):
    return {'author': {'login': login}, 'body': body, 'updatedAt': when, 'databaseId': number}


class VerifierCommentVerdicts(unittest.TestCase):
    """VSTA-230: merged PRs read GitHub Actions verdict comments on the merged head."""

    def setUp(self):
        self._saved = (r.jobs_evidence, r.verifier_policy)
        r.jobs_evidence = lambda repo, run_id: {'jobs': True, 'self_hosted': False}
        r.verifier_policy = lambda repo, ref: None

    def tearDown(self):
        r.jobs_evidence, r.verifier_policy = self._saved

    def merged_node(self, comments, checks=(), head=HEAD):
        return {
            'url': 'https://github.com/valentinyeo/multiprompt/pull/1229',
            'state': 'MERGED', 'mergedAt': '2026-11-24T12:21:33Z',
            'headRefOid': head, 'baseRefOid': 'd02e1180000000000000000000000000000000ff',
            'mergeable': 'UNKNOWN', 'author': {'login': 'valentinyeo'},
            'commits': {'last': {'nodes': [{'commit': {'committedDate': '2026-11-24T11:59:00Z'}}]}},
            'statusCheckRollup': {'state': 'FAILURE',
                                  'contexts': {'pageInfo': {'hasNextPage': False},
                                               'nodes': list(checks)}},
            'comments': {'totalCount': len(comments), 'nodes': list(comments)},
        }

    def test_accepts_vstack_house_rules_multiprompt_and_postbox_pass_shapes(self):
        cases = (
            ('vstack PASS', f'PASS\n\nAll green.\n\nVerifier model: opencode-go/glm-5.3-flash. Head `{HEAD}`.'),
            ('house-rules PASS+NOTES', f'PASS+NOTES\n\nNotes.\n\nVerifier model: opencode-go/deepseek-v4.1-flash. Head {HEAD}.'),
            ('pstack-verifier PASS+NOTES @ sha', f'pstack-verifier: PASS+NOTES @ {HEAD}\n\n- Journey passed.'),
            ('pstack-verifier PASS @ short sha', f'pstack-verifier: PASS @ {HEAD[:10]}\n\n- Journey passed.'),
            ('postbox Commit sha', f'<!-- postbox-verify-verdict -->\n### Verifier verdict\n\nPASS\n\nCommit {HEAD}\n'),
            ('github-actions[bot] REST login', f'pstack-verifier: PASS+NOTES @ {HEAD}\n'),
        )
        for label, body in cases:
            login = 'github-actions[bot]' if 'REST' in label else 'github-actions'
            with self.subTest(label=label):
                node = self.merged_node([gh_comment(body, login=login)])
                pull = r.pull_from_node('valentinyeo/multiprompt', 1229, node)
                self.assertTrue(pull.passed)

    def test_later_blocked_run_does_not_erase_pass_on_merged_head(self):
        comments = [
            gh_comment(f'pstack-verifier: PASS+NOTES @ {HEAD}\n\n- Journey passed.',
                       when='2026-11-24T12:00:00Z', number=1),
            gh_comment(f'pstack-verifier: BLOCKED @ {HEAD}\n\n- Cancelled.',
                       when='2026-11-24T12:30:00Z', number=2),
        ]
        checks = [check('pstack-verifier', conclusion='FAILURE')]
        pull = r.pull_from_node('valentinyeo/multiprompt', 1229, self.merged_node(comments, checks))
        self.assertTrue(pull.passed)

    def test_rejects_fail_wrong_head_human_author_and_self_hosted(self):
        cases = (
            ('FAIL on merged head', [gh_comment(f'pstack-verifier: FAIL @ {HEAD}\n\nVERDICT: PASS')]),
            ('PASS then FAIL on merged head', [
                gh_comment(f'pstack-verifier: PASS @ {HEAD}', when='2026-11-24T12:00:00Z', number=1),
                gh_comment(f'pstack-verifier: FAIL @ {HEAD}', when='2026-11-24T12:05:00Z', number=2),
            ]),
            ('PASS on older head', [gh_comment(f'pstack-verifier: PASS+NOTES @ {OTHER_HEAD}')]),
            ('PASS without sha', [gh_comment('PASS\n\nNo commit sha.')]),
            ('PASS from human login', [gh_comment(f'pstack-verifier: PASS @ {HEAD}', login='valentinyeo')]),
            ('NO VERDICT notice', [gh_comment(f'NO VERDICT: every model lane failed.\n\nHead `{HEAD}`.')]),
            ('BLOCKED only', [gh_comment(f'pstack-verifier: BLOCKED @ {HEAD}')]),
        )
        for label, comments in cases:
            with self.subTest(label=label):
                pull = r.pull_from_node('valentinyeo/multiprompt', 1229, self.merged_node(comments))
                self.assertFalse(pull.passed)

        r.jobs_evidence = lambda repo, run_id: {'jobs': True, 'self_hosted': True}
        node = self.merged_node(
            [gh_comment(f'pstack-verifier: PASS @ {HEAD}')],
            checks=[check('pstack-verifier', conclusion='SUCCESS')],
        )
        self.assertFalse(r.pull_from_node('valentinyeo/multiprompt', 1229, node).passed)


if __name__ == '__main__':
    unittest.main()
