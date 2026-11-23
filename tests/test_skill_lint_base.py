"""Skill lint judges the PR's own changes, not main's.

PR 292 touched only skills/fleet-report/, yet Skill lint failed it with
"skills/long-chat/SKILL.md:1: grew from 373 to 448 words" because main grew that skill
after the PR forked. The merge step reads the live base branch, while the lint step read
github.event.pull_request.base.sha, an older commit: the diff then carried main's own
growth and blamed the PR for it. The base is now the merge base of HEAD and the freshly
fetched base ref, so a skill main changed alone is out of the PR's diff.
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/skill-lint.yml'
MERGE_STEP = 'Check the tree main will get'
LINT_STEP = 'Lint changed skills with the shared script'
PR_SKILL = Path('skills/fleet-report/SKILL.md')
MAIN_SKILL = Path('skills/long-chat/SKILL.md')
STUB = '''import os, sys
args = sys.argv[1:]
base = args[args.index('--base') + 1]
Path = __import__('pathlib').Path
Path(os.environ['SKILL_LINT_RECORD']).write_text(base + '\\n')
'''


def step_body(text, name):
    rest = text[text.index(name):]
    end = len(rest)
    for later in ('\n      - name:', '\n      - uses:'):
        found = rest.find(later, 1)
        if found != -1:
            end = min(end, found)
    return rest[:end]


def shell(step):
    lines = step.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == 'run: |') + 1
    return '\n'.join(line[10:] for line in lines[start:])


def step_env(step):
    """The env keys GitHub fills for a step, so the step runs as it does on a runner."""
    lines = step.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == 'env:') + 1
    keys = []
    for line in lines[start:]:
        found = re.match(r' {10}([A-Z_]+):', line)
        if not found:
            break
        keys.append(found[1])
    return keys


class BaseIsTheFetchedBaseRef(unittest.TestCase):
    def test_the_base_comes_from_the_base_ref_not_the_event_sha(self):
        text = WORKFLOW.read_text()
        body = step_body(text, LINT_STEP)
        self.assertIn('BASE_REF', body, 'the base branch name comes from the pull request')
        self.assertRegex(body, r'git\b[^\n]*\bmerge-base\b',
                         'the base of the diff is the merge base with the base branch')
        self.assertNotIn('pull_request.base.sha', body,
                         'the event base sha lags the base branch the checkout merged')
        self.assertIn('--base "$BASE"', body, 'the shared script takes the computed base')

    def test_a_push_to_main_still_lints_against_the_previous_commit(self):
        body = step_body(WORKFLOW.read_text(), LINT_STEP)
        self.assertIn('BEFORE', body, 'a push has no pull request base; use event.before')


class MainOnlyGrowthIsNotThePRs(unittest.TestCase):
    def test_a_skill_only_main_grew_is_out_of_the_pr_diff(self):
        with tempfile.TemporaryDirectory() as where:
            repo, origin = Path(where) / 'repo', Path(where) / 'origin.git'
            stub = Path(where) / 'lint-source/scripts/skill-lint'
            stub.parent.mkdir(parents=True)
            stub.write_text(STUB)
            record = Path(where) / 'base.txt'
            git(where, 'init', '-q', '--bare', str(origin))
            git(where, 'clone', '-q', str(origin), str(repo))
            (repo / PR_SKILL).parent.mkdir(parents=True)
            (repo / PR_SKILL).write_text(words(100) + '\n')
            (repo / MAIN_SKILL).parent.mkdir(parents=True)
            (repo / MAIN_SKILL).write_text(words(373) + '\n')
            commit(repo, 'base')
            fork = git(repo, 'rev-parse', 'HEAD').strip()
            git(repo, 'checkout', '-q', '-B', 'main')
            git(repo, 'push', '-q', 'origin', 'main')
            git(repo, 'checkout', '-q', '-b', 'branch')
            (repo / PR_SKILL).write_text(words(120) + '\n')
            commit(repo, 'the pr grows its own skill')
            pr_head = git(repo, 'rev-parse', 'HEAD').strip()
            git(repo, 'checkout', '-q', 'main')
            (repo / MAIN_SKILL).write_text(words(448) + '\n')
            commit(repo, 'main grows a skill the pr never touched')
            git(repo, 'push', '-q', 'origin', 'main')
            git(repo, 'checkout', '-q', 'branch')
            text = WORKFLOW.read_text()
            # BASE is the event's base sha, which still points at the fork: exactly what
            # GitHub hands the old workflow when main moves after the PR opens.
            supplied = {'BASE': fork, 'BASE_REF': 'main', 'BEFORE': pr_head}
            keys = {key for step in (MERGE_STEP, LINT_STEP)
                    for key in step_env(step_body(text, step))}
            self.assertTrue(keys, 'the steps name their inputs')
            self.assertEqual(set(keys) - set(supplied), set(), f'feed the new input: {keys}')
            env = {'PATH': '/usr/bin:/bin', 'HOME': where, 'SKILL_LINT_RECORD': str(record),
                   'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
                   'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
            env.update({key: supplied[key] for key in keys})
            for step in (MERGE_STEP, LINT_STEP):
                run = subprocess.run(['bash', '-c', shell(step_body(text, step))], cwd=repo,
                                     text=True, capture_output=True, timeout=120, env=env)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            base = record.read_text().strip()
            changed = git(repo, 'diff', '--name-only', base, 'HEAD', '--', 'skills').split()
            self.assertNotIn(str(MAIN_SKILL), changed,
                             'a skill only main changed counts as the PR growing it')
            self.assertIn(str(PR_SKILL), changed, 'the PR\'s own skill is still judged')
            self.assertEqual(git(repo, 'show', f'{base}:{MAIN_SKILL}'),
                             git(repo, 'show', f'HEAD:{MAIN_SKILL}'),
                             'the base has to hold the same text as the linted tree, or the growth is invented')
            self.assertTrue(re.fullmatch('[0-9a-f]{40}', base), base)


def words(count):
    return ' '.join(['word'] * count)


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=str(cwd), check=True, text=True,
                          capture_output=True, timeout=120,
                          env={'PATH': '/usr/bin:/bin', 'GIT_AUTHOR_NAME': 't',
                               'GIT_AUTHOR_EMAIL': 't@example.invalid',
                               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid',
                               'HOME': str(cwd)}).stdout


def commit(cwd, message):
    git(cwd, 'add', '-A')
    git(cwd, 'commit', '-qm', message)


if __name__ == '__main__':
    unittest.main()
