# Apply converges

The full proof: move a bounded number of cards, then look again and see nothing left to move.

## Sub-features

- `apply.ran`: the apply run printed `PREVIEW board=N tickets=N unknown=N` and no traceback.
- `apply.settled`: no card the apply run MOVEd is planned again in the second dry run.
- `apply.converged`: the second dry run plans fewer moves than the first, and none at all when the first fit inside the limit.

## How to get to it (user POV)

- A chat runs the board sync with `--apply --limit 5`. Over the next minutes the cards move to their true columns, and a manual sync afterwards reports nothing to do.

## Driving it with run

- Action: `run --board 15 --apply --limit 5`. Result: `apply.out` holds the `MOVE` lines, `dry2.out` the plan a second dry run makes.
- Check: `apply`, `settled` and `converged`. Together they are the proof bar: apply, then a second dry run shows no moves.

## Gotchas

- On board 15 `--apply` needs the HT Product Lead or vcc token: `require_board15_agent` refuses any other agent, so the Hypertask Reconciler login cannot apply on board 15 yet. A dry run there needs no token.
- `--apply` without `HT_TOKEN` in the environment stops before the doctor passes. That is intended; do not borrow a login to get past it.
- Reconcile re-reads each ticket before it moves it and prints `SKIP ... changed since preview` when the board moved underneath. That is not a failure; the second dry run catches what is left.
- Board 15 caps its own limit at 5, whatever `--limit` says. The `converged` check reads the limit from `meta.json`, so pass the same `--limit` you drove.
