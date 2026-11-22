"""Skill lint reads the tree main will get, not just the branch tip.

PR 271 passed Skill lint on its own head (1045 words) and turned main red the moment it
landed (1072): the checkout was the branch tip, which never had the base branch's newer
lines, while the squash merged base and branch together. A budget checked on the branch
alone cannot see the total after the merge, so the workflow updates the branch with its
base first. pstack principle-prove-it-works: the gate proves the artifact that ships.
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/skill-lint.yml'
MERGE_STEP = 'Check the tree main will get'
LINT_RUN = 'python3 ../lint-source/scripts/skill-lint'
SKILL = Path('skills/valentin-mode/SKILL.md')


def step_body(text, name):
    start = text.index(name)
    rest = text[start:]
    end = len(rest)
    for later in ('\n      - name:', '\n      - uses:'):
        found = rest.find(later, 1)
        if found != -1:
            end = min(end, found)
    return rest[:end]


class CheckedTreeIncludesTheBase(unittest.TestCase):
    def test_the_workflow_brings_the_base_into_the_branch_before_it_lints(self):
        text = WORKFLOW.read_text()
        self.assertIn(MERGE_STEP, text, 'Skill lint must check the merge result, not the branch tip')
        body = step_body(text, MERGE_STEP)
        self.assertRegex(body, r'git\b(?:[^\n]*\b)?merge\b',
                         'the step must merge the base branch into the branch')
        self.assertIn('BASE_REF', body, 'the base branch name comes from the pull request')
        self.assertIn('working-directory: change', body,
                      'the merge happens in the checkout the lint reads')
        self.assertLess(text.index(MERGE_STEP), text.index(LINT_RUN),
                        'the merge has to land before the shared script reads the files')

    def test_it_only_runs_for_a_pull_request(self):
        text = WORKFLOW.read_text()
        body = step_body(text, MERGE_STEP)
        self.assertIn("if: github.event_name == 'pull_request'", body,
                      'a push to main already has the merged tree')

    def test_the_step_leaves_branch_plus_base_in_the_working_tree(self):
        """Run the step's own shell against a throwaway repo: base growth shows up."""
        step = step_body(WORKFLOW.read_text(), MERGE_STEP)
        self.assertIn('run: |', step, 'the step keeps its shell in a run: block')
        body = '\n'.join(line[10:] for line in step.splitlines() if line.startswith('          '))
        with tempfile.TemporaryDirectory() as where:
            repo = Path(where) / 'repo'
            origin = Path(where) / 'origin.git'
            git(where, 'init', '-q', '--bare', str(origin))
            git(where, 'clone', '-q', str(origin), str(repo))
            skill = repo / SKILL
            skill.parent.mkdir(parents=True)
            skill.write_text(words(1000) + '\nepilogue\n')
            commit(repo, 'base')
            git(repo, 'checkout', '-q', '-B', 'main')
            git(repo, 'push', '-q', 'origin', 'main')
            git(repo, 'checkout', '-q', '-b', 'branch')
            skill.write_text('the branch adds this line\n' + words(1000) + '\nepilogue\n')
            commit(repo, 'branch')
            git(repo, 'checkout', '-q', 'main')
            skill.write_text(words(1000) + '\nepilogue\nthe base grows after the branch forked\n')
            commit(repo, 'base grows')
            git(repo, 'push', '-q', 'origin', 'main')
            git(repo, 'checkout', '-q', 'branch')
            run = subprocess.run(['bash', '-c', body], cwd=repo, text=True,
                                 capture_output=True, timeout=120,
                                 env={'BASE_REF': 'main', 'PATH': '/usr/bin:/bin',
                                      'HOME': where, 'GIT_AUTHOR_NAME': 't',
                                      'GIT_AUTHOR_EMAIL': 't@example.invalid',
                                      'GIT_COMMITTER_NAME': 't',
                                      'GIT_COMMITTER_EMAIL': 't@example.invalid'})
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            merged = skill.read_text()
        self.assertIn('the base grows after the branch forked', merged,
                      'the lint reads a tree without the base branch: main can go red after merge')
        self.assertIn('the branch adds this line', merged)


def words(count):
    return ' '.join(['word'] * count)


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=str(cwd), check=True, text=True,
                          capture_output=True, timeout=120,
                          env={'PATH': '/usr/bin:/bin', 'GIT_AUTHOR_NAME': 't',
                               'GIT_AUTHOR_EMAIL': 't@example.invalid',
                               'GIT_COMMITTER_NAME': 't',
                               'GIT_COMMITTER_EMAIL': 't@example.invalid',
                               'HOME': str(cwd)})


def commit(cwd, message):
    git(cwd, 'add', '-A')
    git(cwd, 'commit', '-qm', message)


if __name__ == '__main__':
    unittest.main()
