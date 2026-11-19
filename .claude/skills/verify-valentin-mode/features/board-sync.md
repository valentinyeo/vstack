# Board sync

In its own loop, a chat runs the reconcile for its project's board and label: a dry run, then `--apply --limit 5`.

## Sub-features

- `sync.dry`: `reconcile --board 2060 --label vvm-test` without `--apply`.
- `sync.apply`: then the same with `--apply --limit 5`, and its result is not an error.

## How to get to it (user POV)

- Ask the chat to sync the board. The project's `CLAUDE.md` line `Hypertask board: 2060, label: vvm-test` names the board and label.

## Driving it with run

Preconditions: `SHIP_SESSION_NAME` set to an agent login, because `--apply` on board 2060 refuses without one.

- Action: `run`. Result: `stream.jsonl` holds both Bash calls and their results.
- Check: a dry run appears before an apply, and the apply's result has no `error:` line.

## Gotchas

- A second run at the same time gets `SKIP ... already running` from the board lock.
- A GitHub rate limit makes reconcile stop cleanly. Read the result before rerunning.
