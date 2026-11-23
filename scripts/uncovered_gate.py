#!/usr/bin/env python3
"""uncovered_gate: a pass cannot stand while changed product files went unexercised.

  uncovered_gate --selection PATH [--verdict PASS|PASS+NOTES|FAIL]
  uncovered_gate --selection PATH --list
  uncovered_gate --self-test

A verifier that plans journeys from a feature map also records what it could not map. That
list is the selection's `unmapped` array, or its `uncovered` prose in the form
`Unmapped files: a, b`. This gate names the entries that are product code: files a journey
was supposed to drive. Documentation, changelog entries, ticket titles, CI plumbing and
tests are not product code, so an uncovered one never fails a pass.

Exit 0 when the verdict stands, 1 when it was demoted to FAIL, 2 on a usage or file error.
Every vstack verifier reads its verdict through scripts/verdict.py, which runs this gate
before it lets a PASS or PASS+NOTES stand. A selection that records no coverage at all fails
closed: an unreadable record is not evidence that everything was covered.
pstack: skills/correct/SKILL.md step 2, a check whose error names the fix.
Root cause: https://app.hypertask.ai/detail/project-13556/145
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PASSING = ('PASS', 'PASS+NOTES')
DEMOTED = 'FAIL'
NAMED = 10

# Not product code: no journey can drive these, so an uncovered one is not a defect.
# Each pattern is (regex, what the class is), read against a repo-relative path.
NOT_PRODUCT = (
    (re.compile(r'^(?:docs?|documentation)/'), 'documentation'),
    (re.compile(r'\.(?:md|mdx|txt|rst|adoc)$'), 'documentation'),
    (re.compile(r'^(?:changelog\.d|changelog|news)/|^CHANGELOG'), 'changelog entry'),
    (re.compile(r'^tools/ticket-titles/'), 'ticket title'),
    (re.compile(r'^(?:\.github|\.circleci|\.buildkite|ci)/'), 'CI plumbing'),
    (re.compile(r'^(?:tests?|__tests__|spec)/'), 'tests'),
    (re.compile(r'(?:^|/)(?:test|spec)_[^/]+$|\.(?:test|spec)\.[^/]+$|(?:^|/)conftest\.py$'),
     'tests'),
    (re.compile(r'^(?:LICENSE|NOTICE|COPYING|AUTHORS)(?:\.\w+)?$|^\.(?:gitignore|gitattributes'
                r'|editorconfig|prettierrc|eslintrc)$'), 'repo plumbing'),
)

# A selection's own prose, kept because some verifiers write only this line.
UNMAPPED_PROSE = re.compile(r'^Unmapped files:[ \t]*(.*)$', re.M)
UNREADABLE_FIX = ('Write the changed files no journey exercises in the selection\'s unmapped list, '
                  'or as "Unmapped files: a, b", then re-run the verifier.')


def unreadable(selection):
    """Why this selection says nothing a gate can trust, or None when its coverage is readable.

    A selection is a verifier's own record of what it planned and what it could not map. One
    that records neither is not evidence of full coverage, so a pass built on it fails closed."""
    if isinstance(selection.get('unmapped'), list):
        return None
    if 'unmapped' in selection:
        return 'the unmapped field is not a list of paths'
    if 'uncovered' in selection and not str(selection.get('uncovered') or '').strip():
        return None
    prose = str(selection.get('uncovered') or '')
    if not prose.strip():
        return 'the selection records no coverage at all: no unmapped list and no uncovered text'
    if UNMAPPED_PROSE.search(prose):
        return None
    return 'the uncovered text is not in the form "Unmapped files: a, b"'


def product_files(selection):
    """The changed paths a journey should have driven, sorted, without the rest."""
    paths = list(selection.get('unmapped') or [])
    if not paths:
        prose = UNMAPPED_PROSE.findall(str(selection.get('uncovered') or ''))
        paths = [name.strip() for line in prose for name in line.split(',')]
    unique = {path.strip().lstrip('./') for path in paths if path and path.strip()}
    return sorted(path for path in unique if not not_product(path))


def not_product(path):
    """Why no journey can exercise this path, or None when it is product code."""
    for pattern, reason in NOT_PRODUCT:
        if pattern.search(path):
            return reason
    return None


def reason(paths):
    """The one-line FAIL that names the fix, not just the mistake."""
    named = ', '.join(paths[:NAMED])
    if len(paths) > NAMED:
        named += f' and {len(paths) - NAMED} more'
    return (f'{DEMOTED}: {len(paths)} changed product file{"s" if len(paths) > 1 else ""} no planned '
            f'journey exercises: {named}. Add or select a journey that exercises '
            f'{"them" if len(paths) > 1 else "it"}, then re-run the verifier.')


def gate(selection, verdict):
    """(the verdict that stands, why it was demoted or ''). FAIL and BLOCKED always stand."""
    if verdict not in PASSING:
        return verdict, ''
    unread = unreadable(selection)
    if unread:
        return DEMOTED, f'{DEMOTED}: {unread}. {UNREADABLE_FIX}'
    paths = product_files(selection)
    return (DEMOTED, reason(paths)) if paths else (verdict, '')


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as problem:
        raise SystemExit(f'uncovered_gate: cannot read selection {path}: {problem}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--selection', metavar='PATH', help='the verifier selection.json')
    parser.add_argument('--verdict', default='PASS', metavar='TOKEN',
                        help='the verdict the verifier gave: PASS, PASS+NOTES or FAIL')
    parser.add_argument('--list', action='store_true',
                        help='print the uncovered product files, one per line')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        return subprocess.call([sys.executable, '-m', 'unittest', 'tests.test_uncovered_gate'],
                               cwd=Path(__file__).resolve().parents[1])
    if not args.selection:
        parser.error('name a selection with --selection PATH')
    selection = load(args.selection)
    if args.list:
        for path in product_files(selection):
            print(path)
        return 0
    standing, why = gate(selection, args.verdict)
    print(standing, flush=True)
    if why:
        print(why, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
