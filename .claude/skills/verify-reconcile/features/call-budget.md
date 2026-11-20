# Call budget

How much GitHub budget one dry run spends. Reconcile prints it on stderr.

## Sub-features

- `calls.one-line`: stderr carries `reconcile: github calls=N (graphql=N, rest=N)`.
- `calls.within-budget`: that total is at or below `--call-budget`, default 30.

## How to get to it (user POV)

- After a sync, read its stderr. A run that spends less budget can run more often without eating GitHub's hourly allowance.

## Driving it with run

- Action: `run --board 15`. Result: `dry1.err` ends with the github calls line. With `--apply` the apply run and `dry2.err` carry theirs too.
- Check: `calls` takes the highest total across the runs and compares it with the budget in `meta.json`. The reason names the run and both numbers.

## Gotchas

- Today's board 15 baseline is 80 to 140 github calls on a cold run, so `calls` FAILs against the default 30 until SOFT-2919 lands. That is expected. A run straight after another one came in at 28 to 29; a low number is never a reason to weaken the check.
- `gh api rate_limit` is free and is not counted, which is why the doctor can always probe the budget.
- The call count covers `gh` only. Hypertask reads are timed per phase and are not in this number.
