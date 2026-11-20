# Reconcile verification map

The parts of board sync this skill proves, each one check in `grade.py`. Read this, then the file for the check.

## Baseline preconditions

- `.claude/skills/verify-reconcile/run` runs on this server, where `hypertask` and `gh` are logged in.
- GitHub graphql budget above 200, because one board 15 dry run spends most of a hundred.
- Board 15 is free: no timer and no other session mid-reconcile (SOFT-2853).
- The cards in `cases/board15.json` still exist and sit where the file says.

## Driving conventions

- Only `run` drives reconcile. One run per board at a time.
- Dry run first, always. `--apply` is opt-in and bounded by `--limit`.
- A run reads the board, so it costs GitHub budget and real time. Do not loop it.

## Proof and skip reporting

- Each check reads reconcile's own lines: the plan lines, the summary, the github call count, the lock skip.
- A check that could not run is reported FAIL with its reason, never PASS. That includes a card missing from the output.
- A FAIL on `calls` or `cases` is a finding about the board or the script. Fix the script; do not soften the check.

## Features

| File | Checks | What it proves |
| --- | --- | --- |
| [dry-run.md](dry-run.md) | `finished`, `unknown` | A whole board is read and planned without a lock clash |
| [apply-converges.md](apply-converges.md) | `apply`, `settled`, `converged` | Moves land, and a second dry run plans none |
| [call-budget.md](call-budget.md) | `calls` | One dry run stays inside its GitHub budget |
| [user-bus.md](user-bus.md) | `bus` | Live worker reads reach the user session bus |
| [real-cards.md](real-cards.md) | `cases` | Named live cards end in the column they belong in |
