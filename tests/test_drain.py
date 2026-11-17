import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def drain_text():
    text = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
    return text.split('- **Drain:**', 1)[1].split('- **Short chats:**', 1)[0]


def referenced_round(text):
    """Contract adapter for a prose skill, not a replacement drain engine."""
    return all(clause in text for clause in (
        'playbooks/shipping.md', 'steps 1-4',
        'every open PR', "lead's tickets", 'GitHub',
    ))


def replay(text, prs):
    if not referenced_round(text):
        return []
    return [pr['id'] for pr in prs
            if pr['verdict'] in ('PASS', 'PASS+NOTES')
            and pr['checks'] and pr['patch'] == pr['verified_patch']
            and pr.get('parent_verified', True)]


class DrainRuleTests(unittest.TestCase):
    def test_17_nov_five_pass_prs_enter_shipping(self):
        prs = [dict(id=f'{repo}#{number}', verdict='PASS', checks=True,
                    patch='same', verified_patch='same')
               for repo, numbers in [('house-rules', [593, 594, 595]),
                                     ('vstack', [106, 107])]
               for number in numbers]
        self.assertEqual(replay(drain_text(), prs), [pr['id'] for pr in prs])

    def test_round_delegates_in_order(self):
        text = drain_text()
        steps = ['playbooks/autonomous-run.md', 'playbooks/shipping.md',
                 'scripts/watch-pr/watch-pr', 'fleet/reconcile', 'fleet/slots']
        positions = [text.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        for clause in ('0.15.43', 'checkable', 'steps 1-4', 'GitHub runners',
                       'never on the server', '.github/workflows/pstack-sources.yml',
                       'patch-id', 'bottom-up', 'read back', 'fallback',
                       'SOFT-2446', 'Valentin Review', 'Checks', 'AI Review',
                       'Todo', 'Doing', 'Done'):
            with self.subTest(clause=clause):
                self.assertIn(clause, text)
        self.assertNotIn('Drain check:', text)

    def test_waiting_ticket_is_outside_finish_line(self):
        text = drain_text()
        self.assertIn('Exclude tickets waiting on Valentin or BlockedBy', text)
        self.assertIn('Pending workers, CI and verdicts remain actionable', text)
        tickets = [dict(id=1, waiting=True, blocked=False),
                   dict(id=2, waiting=False, blocked=True),
                   dict(id=3, waiting=False, blocked=False)]
        actionable = [t['id'] for t in tickets if not (t['waiting'] or t['blocked'])]
        self.assertEqual(actionable, [3])

    def test_clean_rebase_keeps_pass_changed_patch_and_fail_do_not(self):
        self.assertIn('Compare git patch-id', drain_text())
        self.assertIn('A clean rebase keeps PASS', drain_text())
        self.assertIn('Changed patches and FAIL require fresh verification', drain_text())
        with tempfile.TemporaryDirectory() as directory:
            def git(*args):
                return subprocess.check_output(['git', '-C', directory, *args], text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@users.noreply.github.com')
            path = Path(directory)
            (path / 'work').write_text('before\n')
            git('add', '.')
            git('commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            (path / 'work').write_text('after\n')
            git('commit', '-qam', 'patch')
            verdict_sha = git('rev-parse', 'HEAD')
            def patch_id(sha):
                diff = git('show', '--format=', sha)
                return subprocess.check_output(['git', 'patch-id', '--stable'],
                                               input=diff, text=True).split()[0]
            verified = patch_id(verdict_sha)
            git('checkout', '-qb', 'trunk', base)
            (path / 'other').write_text('unrelated\n')
            git('add', '.')
            git('commit', '-qm', 'trunk advanced')
            git('cherry-pick', verdict_sha)
            rebased_sha = git('rev-parse', 'HEAD')
            self.assertNotEqual(verdict_sha, rebased_sha)
            self.assertEqual(verified, patch_id(rebased_sha))
            pr = dict(id='rebased', verdict='PASS', checks=True,
                      patch=patch_id(rebased_sha), verified_patch=verified)
            self.assertEqual(replay(drain_text(), [pr]), ['rebased'])
            (path / 'work').write_text('changed behavior\n')
            git('commit', '-qam', 'changed patch', '--amend')
            pr['patch'] = patch_id('HEAD')
            self.assertEqual(replay(drain_text(), [pr]), [])
            pr.update(patch=verified, verdict='FAIL')
            self.assertEqual(replay(drain_text(), [pr]), [])
            pr.update(verdict='PASS', parent_verified=False)
            self.assertEqual(replay(drain_text(), [pr]), [])


if __name__ == '__main__':
    unittest.main()
