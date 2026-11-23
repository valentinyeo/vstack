#!/usr/bin/env python3
"""Grade one verify-vstack run from its evidence folder. No chat, no network.

Doctor checks must all pass. Drive may be PASS or SKIP: a gated live chat makes Doctor the
merge gate, and a skipped Drive is reported as skipped, never as PASS.

pstack create-verification-skill, "Evidence": grade the side effects, not the claims.
Root cause: VSTA-137, https://app.hypertask.ai/detail/project-13556/137

grade.py EVIDENCE_DIR
"""
import json
import sys
from pathlib import Path


def lines(path):
    try:
        return [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]
    except OSError:
        return []


def main(argv):
    if len(argv) != 2:
        print('usage: grade.py EVIDENCE_DIR', file=sys.stderr)
        return 2
    evidence = Path(argv[1])
    checks, problems = [], []

    doctor = lines(evidence / 'doctor.txt')
    if not doctor:
        problems.append('doctor.txt is missing: nothing was checked')
    for line in doctor:
        if not line.startswith('CHECK '):
            continue
        _, name, status, *rest = line.split(' ', 3)
        checks.append(f'{name} {status} ' + (rest[0] if rest else ''))
        if status != 'PASS':
            problems.append(f'{name}: ' + (rest[0] if rest else 'failed'))

    drive = lines(evidence / 'drive.txt')
    if not drive:
        checks.append('drive SKIP no drive.txt: run stopped before Drive')
    else:
        verdict = drive[0]
        detail = verdict.split(' ', 2)[2] if len(verdict.split(' ', 2)) > 2 else ''
        checks.append('drive ' + ' '.join(verdict.split(' ')[1:]))
        if verdict.startswith('DRIVE FAIL'):
            problems.append('drive: ' + detail)
        elif verdict.startswith('DRIVE SKIP'):
            checks.append('drive-skip-reason ' + detail)

    verdict = 'FAIL' if problems else 'PASS'
    report = [f'{name}' for name in checks] + [f'FAIL {problem}' for problem in problems]
    report.append(f'VERDICT {verdict}')
    (evidence / 'verdict.txt').write_text('\n'.join(report) + '\n')
    (evidence / 'verdict.json').write_text(json.dumps(
        {'verdict': verdict, 'checks': checks, 'problems': problems}, indent=2) + '\n')
    print('\n'.join(report))
    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
