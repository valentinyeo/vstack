"""Fixtures-only tests for scripts/up-to-date: a stale or overwritten base is refused."""

import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/up-to-date'


def load_script():
    loader = importlib.machinery.SourceFileLoader('up_to_date', str(SCRIPT))
    spec = importlib.util.spec_from_loader('up_to_date', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def commit(sha, date):
    return {'sha': sha, 'commit': {'committer': {'date': date}}}


def pull(number=223, state='open', target='main'):
    return {'number': number, 'state': state, 'merged': False,
            'base': {'ref': target, 'sha': 'b' * 40}, 'head': {'sha': 'c' * 40}}


class UpToDateTest(unittest.TestCase):
    """The #223 merge: a base 66 hours old under a file #251 rewrote."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def api(self, base_at, head_at, pr_files, main_files, open_pull=None):
        """GitHub's answers for one PR, keyed by the URL the script asks for."""
        target = 'main'
        answers = {
            'pulls/223': open_pull or pull(),
            'compare/main...' + 'c' * 40: {
                'merge_base_commit': commit('d' * 40, base_at),
                'files': [{'filename': path} for path in pr_files]},
            'commits/main': commit('e' * 40, head_at),
        }
        answers['compare/' + 'd' * 40 + '...main'] = {
            'merge_base_commit': commit('d' * 40, base_at),
            'files': [{'filename': path} for path in main_files]}

        def request(url, token):
            for suffix, answer in answers.items():
                if url.endswith(suffix):
                    return answer
            raise AssertionError(f'unexpected URL: {url}')
        return request

    def run_check(self, request):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(self.m, 'api_request', side_effect=request), \
                patch.dict('os.environ', {'GITHUB_TOKEN': 'fixture'}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.m.main(['--repo', 'valentinyeo/vstack', '--pr', '223'])
        return code, out.getvalue(), err.getvalue()

    def test_the_223_merge_is_refused_and_names_the_fix(self):
        """#223 merged on a 66-hour-old base; #251 had rewritten reconcile under it."""
        request = self.api('2026-11-20T17:51:02Z', '2026-11-23T11:51:02Z',
                           ['skills/hypertask-work/reconcile'],
                           ['skills/hypertask-work/reconcile', 'tests/test_hypertask_work.py'])
        code, out, err = self.run_check(request)
        self.assertEqual(code, 1)
        self.assertIn('66h behind main (24h allowed)', err)
        self.assertIn('skills/hypertask-work/reconcile', err)
        self.assertIn('rebase onto origin/main and rerun the tests', err)
        self.assertEqual(out, '')

    def test_a_current_base_that_main_rewrote_is_still_refused(self):
        request = self.api('2026-11-23T10:00:00Z', '2026-11-23T11:51:02Z',
                           ['skills/hypertask-work/reconcile'],
                           ['skills/hypertask-work/reconcile'])
        code, _, err = self.run_check(request)
        self.assertEqual(code, 1)
        self.assertNotIn('behind main', err)
        self.assertIn('changed skills/hypertask-work/reconcile', err)
        self.assertIn('rebase onto origin/main and rerun the tests', err)

    def test_a_stale_base_that_main_left_alone_is_still_refused(self):
        request = self.api('2026-11-20T17:51:02Z', '2026-11-23T11:51:02Z',
                           ['skills/hypertask-work/reconcile'], ['docs/other.md'])
        code, _, err = self.run_check(request)
        self.assertEqual(code, 1)
        self.assertIn('66h behind main', err)
        self.assertNotIn('changed', err)

    def test_a_rebased_pr_main_left_alone_passes(self):
        request = self.api('2026-11-23T10:00:00Z', '2026-11-23T11:51:02Z',
                           ['skills/hypertask-work/reconcile'], ['docs/other.md'])
        code, out, err = self.run_check(request)
        self.assertEqual((code, err), (0, ''))
        self.assertIn('up-to-date: PR #223 is built on current main', out)

    def test_a_merged_pr_is_not_checked(self):
        request = self.api('2026-11-20T17:51:02Z', '2026-11-23T11:51:02Z', [], [],
                           open_pull={**pull(), 'state': 'closed', 'merged': True})
        with self.assertRaises(SystemExit) as stop:
            self.run_check(request)
        self.assertIn('not open', str(stop.exception.code))

    def test_self_test_reproduces_the_223_findings(self):
        self.assertEqual(self.m.self_test(), 0)


if __name__ == '__main__':
    unittest.main()
