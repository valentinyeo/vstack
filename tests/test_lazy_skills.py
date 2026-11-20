"""Only valentin-mode and responsive-mode load on their own.

Every other skill hides from the model's skill list, the way pstack hides its
leaves, and is opened through the valentin-mode index or its own slash command.
These checks read the real skills/ folder next to the tests.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / 'skills'
FLAG = 'disable-model-invocation: true'
INDEX = SKILLS / 'valentin-mode/SKILL.md'
INDEX_HEADING = '## Skill index'
RULES_HEADING = '## Changing the rules'
SKILL_PATH = re.compile(r'\.\./[\w.-]+/SKILL\.md')

HIDDEN = [
    'design-lead-setup',
    'join-slack',
    'pospeak',
    'ptacek-copyedit',
    'report-page',
    'schneider-deutsch-stil',
    'unjargon',
    'web-writing',
    'zinsser-english-style',
]


def frontmatter(name):
    """Return the YAML block of a skill, without the surrounding --- lines."""
    text = (SKILLS / name / 'SKILL.md').read_text()
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        raise AssertionError('%s has no frontmatter' % name)
    for end in range(1, len(lines)):
        if lines[end].strip() == '---':
            return '\n'.join(lines[1:end])
    raise AssertionError('%s frontmatter is never closed' % name)


def index_section():
    """Return the lines of the index section, which ends the file."""
    lines = INDEX.read_text().splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == INDEX_HEADING]
    if len(starts) != 1:
        raise AssertionError('expected one %r heading, found %d'
                             % (INDEX_HEADING, len(starts)))
    start = starts[0]
    for end in range(start + 1, len(lines)):
        if lines[end].startswith('## '):
            return lines[start:end]
    return lines[start:]


class HiddenSkills(unittest.TestCase):
    def test_hidden_skills_carry_the_flag(self):
        for name in HIDDEN:
            with self.subTest(skill=name):
                self.assertIn(FLAG, frontmatter(name).splitlines(),
                              '%s must carry %r' % (name, FLAG))

    def test_flag_sits_inside_the_frontmatter(self):
        for name in HIDDEN:
            with self.subTest(skill=name):
                text = (SKILLS / name / 'SKILL.md').read_text()
                body = text.split('---', 2)[2]
                self.assertNotIn(FLAG, body,
                                 '%s carries the flag below the frontmatter' % name)

    def test_rest_of_the_frontmatter_is_untouched(self):
        for name in HIDDEN:
            with self.subTest(skill=name):
                keys = [line.split(':')[0].strip()
                        for line in frontmatter(name).splitlines()
                        if line and not line.startswith((' ', '-'))]
                self.assertIn('name', keys)
                self.assertIn('description', keys)


class LoadedSkills(unittest.TestCase):
    def test_responsive_mode_stays_loadable(self):
        # valentin-mode loads it with the Skill tool, which refuses a hidden skill.
        self.assertNotIn('disable-model-invocation', frontmatter('responsive-mode'))

    def test_valentin_mode_stays_hidden(self):
        self.assertIn(FLAG, frontmatter('valentin-mode').splitlines())


class HypertaskSkillUntouched(unittest.TestCase):
    def test_other_ticket_owns_it(self):
        # The hypertask skill (which now holds the work and checkup material)
        # is loadable on purpose, so it stays out of the hidden set.
        self.assertNotIn('disable-model-invocation', frontmatter('hypertask'))


class ValentinModeIndex(unittest.TestCase):
    def test_section_sits_after_the_rules_and_ends_the_file(self):
        lines = INDEX.read_text().splitlines()
        headings = [line.strip() for line in lines if line.startswith('## ')]
        self.assertIn(INDEX_HEADING, headings)
        self.assertEqual(headings[-1], INDEX_HEADING,
                         'the index must be the last ## heading')
        self.assertGreater(lines.index(INDEX_HEADING),
                           lines.index(RULES_HEADING))

    def test_every_hidden_skill_has_exactly_one_bullet(self):
        section = '\n'.join(index_section())
        for name in HIDDEN:
            with self.subTest(skill=name):
                needle = '-> read ../%s/SKILL.md' % name
                self.assertEqual(section.count(needle), 1,
                                 'expected one %r bullet in the index' % needle)

    def test_every_index_path_exists(self):
        section = index_section()
        bullets = [line for line in section if line.startswith('- ')]
        self.assertTrue(bullets, 'the index section has no bullets')
        paths = set()
        for line in section:
            paths.update(SKILL_PATH.findall(line))
        self.assertTrue(paths, 'the index section names no skill path')
        for rel in sorted(paths):
            target = (INDEX.parent / rel).resolve()
            with self.subTest(path=rel):
                self.assertTrue(target.is_file(),
                                'index points at a missing file: %s' % target)

    def test_index_names_no_skill_that_stays_loadable(self):
        section = '\n'.join(index_section())
        for name in ('responsive-mode', 'valentin-mode'):
            self.assertNotIn('-> read ../%s/SKILL.md' % name, section)


if __name__ == '__main__':
    unittest.main()
