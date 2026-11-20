# Real cards

A live ticket you name, whose column reconcile must settle on. This is the check that catches a rule table gone wrong, and it proves something only when the card starts in the wrong column.

## Sub-features

- `cases.known-card`: each ticket in `cases.json` appears in the run's plan lines.
- `cases.column`: the column that card ends the run in equals `expect`. A `KEEP` leaves it in its own column; a `PLAN` or `MOVE` puts it in the `to` column.
- `cases.proves`: at least one case names a card that sat outside `expect` when the board was read. A card already in place says nothing about the rule that left it there.

## How to get to it (user POV)

- The board shows a ticket in the wrong column. You name that ticket and the column it belongs in, then run the check with a temp cases file.

## Driving it

Cases are written per report. Nothing is shipped in this skill, because a card parked in its right column passes with or without the fix.

```sh
cat > /tmp/cases.json <<< '[{"ticket": "HTPR-9387", "expect": "AI Review"}]'
.claude/skills/verify-reconcile/run --board 15 --cases /tmp/cases.json
```

- Before the fix: `cases` FAILs. That run is the report, and it says the card is out of place.
- After the fix: run the same file on the fix branch with `--script /path/to/fix-branch/skills/hypertask-work/reconcile`. `cases` PASSes.
- Paste both verdicts on the fix PR. The two together are the proof; either one alone is not.
- Action: `--cases FILE`. Result: `cases.json` is copied into the evidence directory.
- Check: `cases`, against `dry1` for a dry run and `dry2` with `--apply`, so the grade reads the state after any moves.

## Gotchas

- A case for a card that is already in its column FAILs on purpose: it cannot prove the fix. Write the case while the card is still out of place.
- A regression you never want back belongs in `tests/test_hypertask_work.py` as a unit test, not here. Live cases are for one report each.
- A ticket missing from the output fails `cases` rather than passing quietly. Look for its `UNKNOWN` line first; a bus or read failure hides the card.
- Keep the temp file to one or two cards so one failure is easy to read.
