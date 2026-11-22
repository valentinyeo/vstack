"""A Hypertask rule lives in skills/hypertask and nowhere else.

Another skill or reference file may point at the skill. It may not restate the
thing the skill owns: column titles as rules, the ticket parts, the comment
kinds, or the reconcile flags.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / 'skills/hypertask'
FIXTURE = ROOT / 'tests/fixtures/hypertask-restate/valentin-mode-old-board-sync.md'

COLUMNS = ('Verification Backlog', 'Todo', 'Doing', 'Building', 'Checks',
           'AI Review', 'Verifier', 'Valentin Review', 'Done')
PARTS = ('Problem', 'Fix', 'Risk', 'Decision')
UNIQUE_PARTS = ('Done when',)
POINTERS = ('/hypertask', 'skills/hypertask', 'hypertask skill', 'references/')


def points_at_the_skill(line):
    return any(pointer in line for pointer in POINTERS)


def word(text, value):
    return re.search(r'(?<![\w-])' + re.escape(value.lower()) + r'(?![\w-])', text.lower())


def findings(text):
    """(line number, what it restates) for each rule another file must not own."""
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or points_at_the_skill(line):
            continue
        columns = sum(1 for column in COLUMNS if word(line, column))
        if columns >= 3:
            yield number, 'column titles as rules'
        parts = sum(1 for part in PARTS if word(line, part))
        if any(word(line, unique) for unique in UNIQUE_PARTS) and parts >= 2:
            yield number, 'the ticket parts'
        if 'question|qa|done' in line.lower():
            yield number, 'the comment kinds'
        if ('reconcile' in line.lower() and '--apply' in line
                and ('--label' in line or '--ticket' in line)):
            yield number, 'the reconcile flags'


def scanned():
    """Every SKILL.md and reference file outside the owning skill."""
    found = []
    for base in (ROOT / 'skills', ROOT / '.claude/skills'):
        for path in base.rglob('*.md'):
            if OWNER in path.parents:
                continue
            relative = path.relative_to(base)
            reference = 'references' in relative.parts
            support_doc = len(relative.parts) == 2 and path.name != 'SKILL.md'
            if path.name == 'SKILL.md' or reference or support_doc:
                found.append(path)
    return sorted(found)


class RestatingLint(unittest.TestCase):
    def test_the_old_board_sync_paragraph_fails(self):
        """Today's valentin-mode Board sync paragraph named the flags instead."""
        text = FIXTURE.read_text()
        found = list(findings(text))
        self.assertTrue(found, 'the old Board sync paragraph must fail the lint')
        reasons = {reason for _line, reason in found}
        self.assertIn('the reconcile flags', reasons)
        line = next(number for number, _line in enumerate(text.splitlines(), 1)
                    if 'reconcile --label <label> --apply' in _line)
        self.assertIn((line, 'the reconcile flags'), found)

    def test_current_valentin_mode_points_at_the_skill(self):
        body = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
        self.assertEqual(list(findings(body)), [], 'valentin-mode must point, not restate')
        self.assertIn('/hypertask', body)
        self.assertIn('checkup', body)

    def test_every_outside_skill_and_reference_points_at_the_skill(self):
        problems = []
        for path in scanned():
            for number, reason in findings(path.read_text()):
                problems.append(f'{path.relative_to(ROOT)}:{number}: {reason}')
        self.assertEqual(problems, [], '\n'.join(problems))

    def test_the_owning_skill_has_the_seven_references(self):
        expected = {'identity.md', 'cli.md', 'tickets.md', 'board.md', 'views.md',
                    'sync.md', 'checkup.md', 'board-lint-rules.md'}
        actual = {path.name for path in (OWNER / 'references').glob('*.md')}
        self.assertEqual(actual, expected)

    def test_the_skill_itself_is_not_scanned(self):
        self.assertNotIn(OWNER, [path.parents[1] for path in scanned() if OWNER in path.parents])
        self.assertTrue(all(OWNER not in path.parents for path in scanned()))


if __name__ == '__main__':
    unittest.main()
