# Real cards

Named live tickets whose column reconcile must settle on. This is the check that catches a rule table gone wrong.

## Sub-features

- `cases.known-card`: each ticket in `cases.json` appears in the run's plan lines.
- `cases.column`: the column that card ends the run in equals `expect`. A `KEEP` leaves it in its own column; a `PLAN` or `MOVE` puts it in the `to` column.

## How to get to it (user POV)

- The board shows a ticket in the wrong column. You name that ticket and the column it belongs in, then run the check with the cases file.

## Driving it with run

- Action: `run --board 15 --cases .claude/skills/verify-reconcile/cases/board15.json`. Result: `cases.json` is copied into the evidence directory.
- Check: `cases`, against `dry1` for a dry run and `dry2` with `--apply`, so the grade reads the state after any moves.

## Gotchas

- Live cards drift. When a card legitimately moves on, update `cases/board15.json` in the same PR that explains why. Never edit a case to turn a FAIL into a PASS.
- On board 15, "Verification Backlog" is an unmanaged column: reconcile keeps idle cards there and prints `unknown column; kept`. HTPR-9514 and HTPR-9511 sit there today and must stay.
- A ticket missing from the output fails `cases` rather than passing quietly. Look for its `UNKNOWN` line first; a bus or read failure hides the card.
- The seed file is three cards. Add another when a rule keeps breaking on a specific column, and keep the file short so one failure is easy to read.
