#!/usr/bin/env python3
"""Grade one verify-reconcile run from its evidence directory.

Reads the files `run` saved, prints one PASS/FAIL line per check, then
VERDICT PASS or VERDICT FAIL. Exit 0 on PASS, 1 on FAIL, 2 on usage or missing
evidence. Reads reconcile's own output; never talks to the board itself.
"""
import argparse
import json
import re
import sys
from pathlib import Path

PASS = 'PASS'
FAIL = 'FAIL'
PLAN_LINE = re.compile(r'^(PLAN|KEEP|MOVE|DEFERRED)\s+(\S+)\s+(.+?)\s+->\s+(.+?)\s+\|\s*(.*)$')
SUMMARY = re.compile(r'^(DRY RUN|PREVIEW)\s+board=(\d+)\s+tickets=(\d+)\s+unknown=(\d+)\s*$')
CALLS = re.compile(r'reconcile: github calls=(\d+)\s+\(graphql=(\d+), rest=(\d+)\)')
LOCK_SKIP = re.compile(r'^\s*SKIP\s+board=\S+.*reconciliation already running', re.M)
BUS_FAILURE = 'Failed to connect to bus'
TRACEBACK = 'Traceback (most recent call last)'
MOVES = ('PLAN', 'MOVE')
DEFAULT_BOARD = 15
DEFAULT_BUDGET = 30


def read_text(path):
    try:
        return path.read_text(errors='replace')
    except OSError:
        return ''


def read_json(path, default):
    try:
        value = json.loads(read_text(path))
    except ValueError:
        return default
    return value


def read_cases(path):
    """The case list, and the reason it could not be read (None when it could)."""
    text = read_text(path)
    if not text.strip():
        return [], None
    try:
        value = json.loads(text)
    except ValueError:
        return None, 'cases.json is not valid JSON'
    if not isinstance(value, list):
        return None, 'cases.json is not a list of cases'
    return value, None


def plan_rows(text):
    """Every PLAN/KEEP/MOVE/DEFERRED line, in the order reconcile printed it."""
    rows = []
    for line in text.splitlines():
        match = PLAN_LINE.match(line.strip())
        if match is None:
            continue
        action, ticket, source, column, reason = match.groups()
        rows.append({'action': action, 'ticket': ticket, 'from': source.strip(),
                     'to': column.strip(), 'reason': reason.strip()})
    return rows


def summary(text):
    """The DRY RUN or PREVIEW summary line as a dict, else None."""
    for line in text.splitlines():
        match = SUMMARY.match(line.strip())
        if match is None:
            continue
        return {'kind': match.group(1), 'board': int(match.group(2)),
                'tickets': int(match.group(3)), 'unknown': int(match.group(4))}
    return None


def github_calls(text):
    """The github calls total from stderr, else None."""
    match = CALLS.search(text)
    return int(match.group(1)) if match else None


def final_columns(rows):
    """Ticket -> the column it ends the run in. A KEEP or DEFERRED card stays put."""
    columns = {}
    for row in rows:
        columns[row['ticket']] = row['to'] if row['action'] in MOVES else row['from']
    return columns


def planned_moves(rows):
    return [row for row in rows if row['action'] in MOVES]


def moved(rows):
    return [row['ticket'] for row in rows if row['action'] == 'MOVE']


def check_finished(dry1, board):
    if LOCK_SKIP.search(dry1):
        return FAIL, 'the board lock was held; another run owns this board'
    line = summary(dry1)
    if line is None:
        return FAIL, 'the dry run wrote no DRY RUN summary line'
    if line['board'] != board:
        return FAIL, 'the dry run read board %d, not board %d' % (line['board'], board)
    return PASS, '%s board=%d finished, %d tickets' % (line['kind'], line['board'], line['tickets'])


def check_bus(dry1, dry1_err):
    if BUS_FAILURE in dry1 or BUS_FAILURE in dry1_err:
        return FAIL, 'systemctl --user could not reach the session bus'
    return PASS, 'no session bus failure'


def check_unknown(dry1):
    line = summary(dry1)
    if line is None:
        return FAIL, 'no summary line, so the unknown count is not known'
    if line['unknown']:
        return FAIL, '%d tickets were not read (unknown=%d)' % (line['unknown'], line['unknown'])
    return PASS, 'unknown=0'


def check_calls(runs, budget):
    seen = [(name, github_calls(text)) for name, text in runs]
    seen = [(name, count) for name, count in seen if count is not None]
    if not seen:
        return FAIL, 'no "reconcile: github calls=" line in any run'
    name, worst = max(seen, key=lambda item: item[1])
    if worst > budget:
        return FAIL, '%s made %d github calls, over budget %d' % (name, worst, budget)
    return PASS, '%s made %d github calls, within budget %d' % (name, worst, budget)


def proving_cases(cases, read_rows):
    """The cases whose card sat outside its expected column when the board was read.

    A card already in the column it belongs in shows nothing about the rule that
    put it there, so it cannot prove a fix.
    """
    started = {row['ticket']: row['from'] for row in read_rows}
    proving = []
    for case in cases:
        ticket, expect = case.get('ticket'), case.get('expect')
        column = started.get(ticket)
        if column is not None and column != expect:
            proving.append(case)
    return proving


def check_cases(cases, unreadable, rows, source, read_rows):
    if unreadable is not None:
        return FAIL, unreadable
    if not cases:
        return PASS, 'no cases file, so no card columns to check'
    columns = final_columns(rows)
    if not rows:
        return FAIL, 'no plan lines in %s, so no card column can be read' % source
    for case in cases:
        ticket = case.get('ticket')
        expect = case.get('expect')
        if not isinstance(ticket, str) or not isinstance(expect, str):
            return FAIL, 'a case is missing ticket or expect'
        if ticket not in columns:
            return FAIL, '%s is not in %s, so its column cannot be read' % (ticket, source)
        if columns[ticket] != expect:
            return FAIL, '%s ended in %s, expected %s' % (ticket, columns[ticket], expect)
    proving = proving_cases(cases, read_rows)
    if not proving:
        return FAIL, ('every case was already in the column it belongs in when the '
                      'board was read, so no case proves the reconcile rule')
    return PASS, '%d cards in the expected columns in %s, %d of them started outside' % (
        len(cases), source, len(proving))


def check_apply(apply_out, apply_err):
    if TRACEBACK in apply_out or TRACEBACK in apply_err:
        return FAIL, 'the apply run hit a traceback'
    line = summary(apply_out)
    if line is None:
        return FAIL, 'the apply run wrote no PREVIEW summary line'
    if line['kind'] != 'PREVIEW':
        return FAIL, 'the apply run printed %s instead of PREVIEW' % line['kind']
    return PASS, 'the apply run finished its PREVIEW'


def check_settled(apply_ran, dry2_ran, apply_rows, dry2_rows):
    if not apply_ran:
        return FAIL, 'the apply run wrote no PREVIEW summary, so settling cannot be read'
    if not dry2_ran:
        return FAIL, 'the second dry run wrote no summary line, so settling cannot be read'
    applied = moved(apply_rows)
    if not applied:
        return PASS, 'the apply run moved nothing, so nothing can be re-planned'
    again = {row['ticket'] for row in planned_moves(dry2_rows)}
    repeated = [ticket for ticket in applied if ticket in again]
    if repeated:
        return FAIL, '%s moved in apply and is planned again in dry2' % ', '.join(repeated)
    return PASS, 'none of the %d moved cards is planned again' % len(applied)


def check_converged(apply_ran, dry2_ran, dry1_rows, apply_rows, dry2_rows, limit):
    if not apply_ran:
        return FAIL, 'the apply run wrote no PREVIEW summary, so convergence cannot be read'
    if not dry2_ran:
        return FAIL, 'the second dry run wrote no summary line, so convergence cannot be read'
    before = len(planned_moves(dry1_rows))
    after = len(planned_moves(dry2_rows))
    applied = len(moved(apply_rows))
    if before <= limit:
        if after:
            return FAIL, 'dry1 planned %d moves, inside limit %d, but dry2 still plans %d' % (
                before, limit, after)
        return PASS, 'dry1 planned %d moves, dry2 plans none' % before
    allowed = before - applied
    if after <= allowed:
        return PASS, 'dry1 planned %d, apply moved %d, dry2 plans %d' % (before, applied, after)
    return FAIL, 'dry1 planned %d, apply moved %d, dry2 still plans %d (over %d)' % (
        before, applied, after, allowed)


def grade(evidence):
    meta = read_json(evidence / 'meta.json', None)
    applying = isinstance(meta, dict) and meta.get('apply') is True
    limit = meta.get('limit') if isinstance(meta, dict) else None
    limit = limit if isinstance(limit, int) and limit > 0 else 5
    budget = meta.get('call_budget') if isinstance(meta, dict) else None
    budget = budget if isinstance(budget, int) and budget > 0 else DEFAULT_BUDGET
    board = meta.get('board') if isinstance(meta, dict) else None
    board = board if isinstance(board, int) else DEFAULT_BOARD
    cases, unreadable_cases = read_cases(evidence / 'cases.json')

    dry1 = read_text(evidence / 'dry1.out')
    dry1_err = read_text(evidence / 'dry1.err')
    dry1_rows = plan_rows(dry1)

    checks = [
        ('finished', check_finished(dry1, board)),
        ('bus', check_bus(dry1, dry1_err)),
        ('unknown', check_unknown(dry1)),
    ]

    runs = [('dry1', dry1_err)]
    if applying:
        apply_out = read_text(evidence / 'apply.out')
        apply_err = read_text(evidence / 'apply.err')
        dry2 = read_text(evidence / 'dry2.out')
        dry2_err = read_text(evidence / 'dry2.err')
        apply_rows = plan_rows(apply_out)
        dry2_rows = plan_rows(dry2)
        runs += [('apply', apply_err), ('dry2', dry2_err)]
        target_rows, target_name = dry2_rows, 'dry2'
    else:
        apply_out = apply_err = dry2 = dry2_err = ''
        apply_rows = dry2_rows = []
        target_rows, target_name = dry1_rows, 'dry1'

    checks.append(('calls', check_calls(runs, budget)))
    checks.append(('cases', check_cases(cases, unreadable_cases, target_rows, target_name,
                                       dry1_rows)))
    if applying:
        apply_ran = summary(apply_out) is not None
        dry2_ran = summary(dry2) is not None
        checks += [
            ('apply', check_apply(apply_out, apply_err)),
            ('settled', check_settled(apply_ran, dry2_ran, apply_rows, dry2_rows)),
            ('converged', check_converged(apply_ran, dry2_ran, dry1_rows, apply_rows,
                                         dry2_rows, limit)),
        ]
    return board, applying, checks


def main(argv):
    parser = argparse.ArgumentParser(description='Grade a verify-reconcile run.')
    parser.add_argument('evidence', help='evidence directory written by run')
    args = parser.parse_args(argv)

    evidence = Path(args.evidence).expanduser()
    if not evidence.is_dir():
        print('grade.py: evidence directory not found: %s' % evidence, file=sys.stderr)
        return 2
    if not (evidence / 'dry1.out').is_file():
        print('grade.py: no dry1.out in %s' % evidence, file=sys.stderr)
        return 2
    if not isinstance(read_json(evidence / 'meta.json', None), dict):
        print('grade.py: no readable meta.json in %s' % evidence, file=sys.stderr)
        return 2

    board, applying, checks = grade(evidence)
    verdict = PASS if all(result[0] == PASS for _name, result in checks) else FAIL

    lines = ['%s %s: %s' % (result[0], name, result[1]) for name, result in checks]
    lines.append('VERDICT %s' % verdict)
    output = '\n'.join(lines) + '\n'

    (evidence / 'verdict.txt').write_text(output)
    payload = {
        'verdict': verdict,
        'board': board,
        'apply': applying,
        'checks': [
            {'name': name, 'pass': result[0] == PASS, 'reason': result[1]}
            for name, result in checks
        ],
    }
    (evidence / 'verdict.json').write_text(json.dumps(payload, indent=2) + '\n')

    sys.stdout.write(output)
    return 0 if verdict == PASS else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
