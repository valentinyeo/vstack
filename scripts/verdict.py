#!/usr/bin/env python3
"""verdict: read one PASS, PASS+NOTES or FAIL out of a verifier's own answer.

  verdict PATH|-,... [--selection PATH]   print the verdict, exit 0 for a pass and 1 otherwise
  verdict --self-test

A pass cannot stand while the verifier's own selection lists changed product files that no
journey exercised. uncovered_gate names those files and turns the pass into FAIL. The gate
reads --selection, or the selection.json beside the answer, or verifier-out/selection.json
beside the answer. A pass with no selection anywhere is unchanged.

A verifier may answer in any of three forms, and the last one in its text wins:
  a bare line       PASS
  a prefixed line   VERDICT: PASS
  a JSON field      {"verdict": "PASS"}

A bare line inside a fenced code block is quoted evidence, never an answer. A verifier
that answers only inside a fence reads as no verdict, and run-verifier tries the next model.
A JSON verdict counts only as JSON: a line holding a JSON object, or a lone
"verdict": "<x>" field of a printed object. The same text quoted mid-sentence is an
example, not the answer.
Text with none of them reads as FAIL, and the caller prints why.
Every vstack verifier workflow reads its verdict through this file.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import uncovered_gate
import video_proof_gate

VERDICTS = ('PASS+NOTES', 'PASS', 'FAIL')
PASSING = ('PASS', 'PASS+NOTES')
TOKEN = r'(PASS\+NOTES|PASS|FAIL)(?![\w+-])'
PREFIXED = re.compile(r'^[ \t]*VERDICT:[ \t]*' + TOKEN, re.M)
JSON_FIELD = re.compile(r'^[ \t]*"verdict"[ \t]*:[ \t]*"(PASS\+NOTES|PASS|FAIL)"[ \t]*,?[ \t]*\}?[ \t]*$', re.M)
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
MISSING = ('no verdict found: expected a bare PASS, PASS+NOTES or FAIL line, '
           'a VERDICT: <x> line, or JSON "verdict": "<x>"')


def json_verdicts(text):
    """(offset, verdict) for every JSON answer: a line that is a JSON object with a verdict,
    or a lone "verdict": "<x>" field line of a pretty-printed object.

    vstack#137 head 014d895's verifier wrote `{"verdict": "FAIL"}` inside a sentence about
    the parser while its real answer was `VERDICT: PASS`; matching that quote read FAIL out
    of a passing review (SOFT-2802, job 135627154998)."""
    found, offset = [], 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        value = None
        if stripped.startswith('{'):
            try:
                answer = json.loads(stripped.rstrip(','))
            except ValueError:
                answer = None
            value = answer.get('verdict') if isinstance(answer, dict) else None
        else:
            field = JSON_FIELD.match(stripped)
            value = field.group(1) if field else None
        if value in VERDICTS:
            found.append((offset, value))
        offset += len(line)
    return found


def occurrences(text):
    """(offset, verdict) for every accepted form, in text order."""
    found = [(match.start(), match.group(1)) for match in PREFIXED.finditer(text)]
    found += json_verdicts(text)
    offset, fenced = 0, False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if FENCE.match(stripped):
            fenced = not fenced
        elif not fenced and stripped in VERDICTS:
            found.append((offset, stripped))
        offset += len(line)
    return sorted(found)


def json_answer(text):
    """The JSON report a verifier ended with, bare or fenced, as a dict.

    Raises ValueError when the text holds no JSON object, so a caller can report it."""
    raw = (text or '').strip()
    fence = raw.find('```')
    if not raw.startswith('{') and fence != -1:
        raw = raw[fence:].split('\n', 1)[1].rsplit('```', 1)[0].strip()
    answer = json.loads(raw)
    if not isinstance(answer, dict):
        raise ValueError(f'JSON report is a {type(answer).__name__}, not an object')
    return answer


def find_verdict(text):
    """The last accepted verdict in text, as (verdict or None, reason when None).

    Fallback (SOFT-2802): an answer with no verdict outside fences may still box its verdict alone in a fence.
    vstack#134 head 8507974: glm wrote "Verdict below." then a fence holding only PASS."""
    found = occurrences(text or '')
    return (found[-1][1], '') if found else (None, MISSING)


def read_source(path):
    return sys.stdin.read() if path == '-' else Path(path).read_text()


SELECTIONS = ('selection.json', 'verifier-out/selection.json')


def find_selection(paths, named=None):
    """The selection a verifier wrote for this answer: --selection, else the conventional spots."""
    if named:
        return Path(named)
    for path in paths:
        if path == '-':
            continue
        folder = Path(path).resolve().parent
        for candidate in SELECTIONS:
            beside = folder / candidate
            if beside.is_file():
                return beside
    return None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', metavar='PATH|-',
                        help='File holding a verifier answer, or - for stdin')
    parser.add_argument('--selection', metavar='PATH',
                        help="the verifier's selection.json; default: the one beside the answer")
    parser.add_argument('--changed-files', metavar='PATH',
                        help='newline-separated changed file paths for the UI video proof gate')
    parser.add_argument('--pr-body', metavar='PATH',
                        help='pull request body file for the UI video proof gate')
    parser.add_argument('--event', metavar='PATH', default=os.environ.get('GITHUB_EVENT_PATH'),
                        help='GitHub event JSON holding pull_request.body')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        return subprocess.call([sys.executable, '-m', 'unittest', 'tests.test_verdict'],
                               cwd=Path(__file__).resolve().parents[1])
    if not args.paths:
        parser.error('name a file, or - for stdin')
    verdict, why = find_verdict('\n'.join(read_source(path) for path in args.paths))
    if not verdict:
        print(f'verdict: FAIL | {why}', file=sys.stderr)
        return 1
    selection = find_selection(args.paths, args.selection)
    if verdict in PASSING and selection:
        verdict, demoted = uncovered_gate.gate(uncovered_gate.load(selection), verdict)
        if demoted:
            print(verdict, flush=True)
            print(demoted, file=sys.stderr)
            return 1
    if verdict in PASSING and args.changed_files:
        changed = video_proof_gate.read_changed_files(path=args.changed_files)
        body = video_proof_gate.read_body(args.pr_body, args.event, allow_missing=True)
        verdict, demoted = video_proof_gate.gate(changed, body, verdict)
        if demoted:
            print(verdict, flush=True)
            print(demoted, file=sys.stderr)
            return 1
    print(verdict)
    return 0 if verdict in PASSING else 1

if __name__ == '__main__':
    sys.exit(main())
