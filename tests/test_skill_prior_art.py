"""Every vstack skill names the pstack gap it fills, and every executable names its pstack source and root cause.

vstack is a personal-mode layer on pstack. A skill that does not say which pstack skill it
extends, and what that skill leaves out, is either a copy of pstack or a contradiction of it.
An executable that does not say which pstack skill or principle it implements, and which root
cause it fixes, is usually recovery machinery for a symptom (VSTA-114, Valentin 2026-11-22).
"""
import os
import re
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'config/tool-registry.txt'
SKILL_BODY_LINES = 15

# pstack skill and principle names, pinned from the installed pstack 0.15.46.
# CI's checks job does not install pstack, so this list is the source there; an installed
# pstack on a developer machine adds its names as well.
PSTACK_NAMES = frozenset("""
architect arena automate-me benchmark-checklist blast-radius bro correct
create-formal-verification-skill create-verification-skill figure-it-out how
in-your-own-words interrogate ketchup ketchup-video maintain-formal-verification-skill
maintain-verification-skill make-bot-ui no-comments poteto-help poteto-mode
principle-attack-the-premise principle-boundary-discipline principle-build-the-lever
principle-encode-lessons-in-structure principle-exhaust-the-design-space
principle-experience-first principle-explain-the-number principle-fix-root-causes
principle-foundational-thinking principle-guard-the-context-window
principle-laziness-protocol principle-make-operations-idempotent
principle-migrate-callers-then-delete-legacy-apis principle-minimize-reader-load
principle-model-the-domain principle-never-block-on-the-human
principle-outcome-oriented-execution principle-prove-it-works
principle-redesign-from-first-principles
principle-separate-before-serializing-shared-state
principle-sequence-verifiable-units principle-subtract-before-you-add
principle-test-behavior-not-implementation principle-type-system-discipline recall
reflect setup-pstack sharpen show-me-your-work statechart swarm tdd teach
technical-writing typescript-best-practices unslop why
""".split())

PSTACK_HOME = Path.home() / '.claude/plugins/cache/cursor-plugins/pstack'
BACKTICK = re.compile(r'`([a-z0-9][a-z0-9-]*)')
AFTER_PSTACK = re.compile(r'pstack:?\s+`?([a-z0-9][a-z0-9-]*)')
GAP_WORDS = re.compile(
    r'\b(gap|only|checked|neither|enforces|adds|beyond|leaves|missing|no|not|replaces)\b', re.I)
EXECUTABLE_DIRS = ('skills', 'tools', 'hooks', 'scripts')
RULE = ('cite the pstack skill or principle it implements and the root cause first '
        '(pstack principle-fix-root-causes, principle-attack-the-premise)')


def pstack_names():
    names = set(PSTACK_NAMES)
    if PSTACK_HOME.is_dir():
        versions = [v for v in PSTACK_HOME.iterdir() if (v / 'skills').is_dir()]
        for version in versions:
            names.update(p.name for p in (version / 'skills').iterdir() if p.is_dir())
    return frozenset(names)


def body_lines(path):
    lines = path.read_text(errors='ignore').splitlines()
    if lines and lines[0].strip() == '---':
        for index, line in enumerate(lines[1:], 1):
            if line.strip() == '---':
                return lines[index + 1:]
    return lines


def named_pstack_skills(line, names):
    found = {n for n in BACKTICK.findall(line) if n in names}
    found.update(n for n in AFTER_PSTACK.findall(line) if n in names)
    return found


def names_anywhere(text, names):
    return {n for n in names if re.search(rf'(?<![\w-]){re.escape(n)}(?![\w-])', text)}


def executables():
    found = set()
    for folder in EXECUTABLE_DIRS:
        for path in (ROOT / folder).rglob('*'):
            if not path.is_file() or '.git' in path.parts:
                continue
            relative = path.relative_to(ROOT).as_posix()
            if os.access(path, os.X_OK) or path.read_bytes()[:2] == b'#!':
                found.add(relative)
    return sorted(found)


def parse_registry():
    """Return (entries, expiring): entries path -> (pstack, why); expiring path -> date."""
    entries, expiring = {}, {}
    for number, raw in enumerate(REGISTRY.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('expires:'):
            _, rest = line.split(':', 1)
            when, path = (part.strip() for part in rest.split('|', 1))
            expiring[path] = (date.fromisoformat(when), number)
            continue
        fields = [field.strip() for field in line.split('|')]
        if len(fields) != 3:
            raise AssertionError(
                f'{REGISTRY}:{number}: expected `<path> | pstack: <name> | why: <url or enforces ...>`, got {raw!r}')
        path, pstack, why = fields
        entries[path] = (pstack.removeprefix('pstack:').strip(),
                         why.removeprefix('why:').strip(), number)
    return entries, expiring


class SkillPriorArt(unittest.TestCase):
    names = pstack_names()

    def test_every_skill_states_the_pstack_gap_it_fills(self):
        for path in sorted((ROOT / 'skills').rglob('SKILL.md')):
            with self.subTest(skill=str(path.relative_to(ROOT))):
                lines = [line for line in body_lines(path)[:SKILL_BODY_LINES] if line.strip()]
                prior = next((line for line in lines if line.startswith('Prior art:')), None)
                self.assertIsNotNone(
                    prior,
                    f'{path.relative_to(ROOT)}: add a line starting "Prior art:" in the first '
                    f'{SKILL_BODY_LINES} body lines that names the pstack skill this one extends '
                    f'and the gap it fills, or says it only enforces a named pstack rule')
                self.assertTrue(
                    named_pstack_skills(prior, self.names),
                    f'{path.relative_to(ROOT)}: the "Prior art:" line names no pstack skill. '
                    f'Name one in backticks, for example `unslop` or `poteto-mode`')
                self.assertRegex(
                    prior, GAP_WORDS,
                    f'{path.relative_to(ROOT)}: the "Prior art:" line names a pstack skill but does '
                    f'not say the gap it fills or that it only enforces a pstack rule')

    def test_every_executable_is_registered_with_its_pstack_source_and_root_cause(self):
        entries, _ = parse_registry()
        for path in executables():
            with self.subTest(executable=path):
                self.assertIn(
                    path, entries,
                    f'{path}: add a line to config/tool-registry.txt: `{path} | pstack: <skill> | '
                    f'why: <ticket URL or enforces <rule>>`. {RULE}')

    def test_every_registry_line_names_a_pstack_source_and_a_root_cause(self):
        entries, expiring = parse_registry()
        today = date.today()
        for path, (pstack, why, number) in sorted(entries.items()):
            with self.subTest(entry=path):
                where = f'{REGISTRY.relative_to(ROOT)}:{number} ({path})'
                self.assertTrue(pstack, f'{where}: empty pstack field. {RULE}')
                self.assertTrue(why, f'{where}: empty why field. {RULE}')
                self.assertTrue(
                    pstack == 'none' or names_anywhere(pstack, self.names),
                    f'{where}: "{pstack}" is not a pstack skill or principle. {RULE}')
                self.assertTrue(
                    why == 'none' or why.lower().startswith('enforces ')
                    or why.startswith('https://app.hypertask.ai/detail/'),
                    f'{where}: why must be a root-cause ticket URL or "enforces <pstack rule>". {RULE}')
                if pstack != 'none' and why != 'none':
                    continue
                self.assertIn(
                    path, expiring,
                    f'{where}: no pstack source and no root cause. Delete the file, or write '
                    f'`pstack: <skill> | why: <ticket URL>`. Temporary only: add '
                    f'`expires: <YYYY-MM-DD> | {path}` to config/tool-registry.txt. {RULE}')
                expires, line = expiring[path]
                self.assertGreater(
                    expires, today,
                    f'{where}: the exception expired on {expires}. Delete the file or justify it '
                    f'with a real pstack source and root cause (line {line})')


if __name__ == '__main__':
    unittest.main()
