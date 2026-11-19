#!/usr/bin/env python3
"""verdict: read one PASS, PASS+NOTES or FAIL out of a verifier's own answer.

  verdict PATH|-,...   print the verdict, exit 0 for a pass and 1 otherwise
  verdict --self-test

A verifier may answer in any of three forms, and the last one in its text wins:
  a bare line       PASS
  a prefixed line   VERDICT: PASS
  a JSON field      {"verdict": "PASS"}

A bare line inside a fenced code block is quoted evidence, not an answer, unless the
answer has no other verdict and that fence holds the verdict alone.
A JSON verdict counts only as JSON: a line holding a JSON object, or a lone
"verdict": "<x>" field of a printed object. The same text quoted mid-sentence is an
example, not the answer.
Text with none of them reads as FAIL, and the caller prints why.
Every vstack verifier workflow reads its verdict through this file.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

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


def boxed(text):
    """Verdicts set alone in a fence, e.g. a line ``` then PASS then ```: (offset, verdict) in text order."""
    found, offset, block, start = [], 0, None, 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if FENCE.match(stripped):
            if block is None:
                block, start = [], offset
            else:
                body = [b for b in block if b]
                if len(body) == 1 and body[0] in VERDICTS:
                    found.append((start, body[0]))
                block = None
        elif block is not None:
            block.append(stripped)
        offset += len(line)
    return found


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
    found = occurrences(text or '') or boxed(text or '')
    return (found[-1][1], '') if found else (None, MISSING)


def read_source(path):
    return sys.stdin.read() if path == '-' else Path(path).read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', metavar='PATH|-',
                        help='File holding a verifier answer, or - for stdin')
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
    print(verdict)
    return 0 if verdict in PASSING else 1


if __name__ == '__main__':
    sys.exit(main())
