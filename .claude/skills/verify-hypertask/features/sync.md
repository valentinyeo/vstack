# Board sync

In its own loop, the chat runs the reconcile for board 2060 and label `vvm-test`: a dry run, then `--apply --limit 5`.

## Sub-features

- `sync.dry`: `reconcile --board 2060 --label vvm-test` without `--apply`.
- `sync.apply`: then the same with `--apply --limit 5`, and its result is not an error.

## Driving it with run

Preconditions: `SHIP_SESSION_NAME` names an agent login, because `--apply` on board 2060 refuses without one.

- Action: `run`. Result: `stream.jsonl` holds both Bash calls and their results.
- Check: a dry run appears before an apply, and the apply result has no error line.

## Gotchas

- An apply without `--label vvm-test` fails, because it can move real tickets.
- A second run at the same time gets `SKIP ... already running` from the board lock.
