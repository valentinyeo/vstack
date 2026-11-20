# Dry run

One full read of a board: every managed ticket gets a `PLAN` or `KEEP` line, then a `DRY RUN` summary.

## Sub-features

- `dry-run.finished`: the run printed `DRY RUN board=N tickets=N unknown=N`.
- `dry-run.no-lock`: no `SKIP board=... | reconciliation already running` line.
- `dry-run.unknown-zero`: `unknown=0`, so no ticket failed to read.

## How to get to it (user POV)

- Run the board sync by hand, or wait for its timer. Nothing moves; it only says what it would do.

## Driving it with run

- Action: `run --board 15`. Result: `dry1.out` holds the plan lines and the summary, `dry1.err` the phases and the call count.
- Check: `finished` needs a summary line and no lock skip. `unknown` needs `unknown=0`.

## Gotchas

- One run per board at a time. Both runs take the same board lock, so a second one gets the SKIP line and fails `finished` (SOFT-2853). Check for a running timer before you start.
- Board 15 has 366 tickets at the time of writing, so a dry run takes about two minutes. Do not kill it early; a half-read board reports wrong unknowns.
- A non-zero `unknown` fails the run even when the moves it did plan are right. Read the `UNKNOWN` lines before rerunning.
