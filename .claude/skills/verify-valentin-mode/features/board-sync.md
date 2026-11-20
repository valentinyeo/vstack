# Board sync

Valentin mode syncs a board two ways, and either one counts.

The current way: the lease syncs the card when its worker starts and ends, and a Stop hook runs `reconcile --label <label> --apply` after a turn. The manual way: a dry run, then `--apply --limit 5`.

## Sub-features

- `sync.card`: the chat runs a worker through `lease <ticket> run -- ...`, and the ticket's agent log gains one `fleet/reconcile` activity at or after `started_at`. Nothing else is typed: the lease's own `reconcile --ticket <key> --apply --limit 1` moves one card.
- `sync.dry` (manual): `reconcile --board 2060 --label vvm-test` without `--apply`.
- `sync.apply` (manual): then the same with `--apply --limit 5`, and its result is not an error.
- `sync.never-uncapped`: a `reconcile --apply` that names no `--label` and no `--ticket` fails the check, because it can move real tickets. A `--ticket` apply moves that one card and passes.

## How to get to it (user POV)

- Ask the chat to sync the board. The project's `CLAUDE.md` line `Hypertask board: 2060, label: vvm-test` names the board and label.

## Driving it with run

Preconditions: `run` names the chat, so the lease and the Stop hook find the test login (see [login.md](login.md)). A `reconcile --apply` on board 2060 also refuses without a `SHIP_SESSION_NAME` agent login.

- Action: `run`. Result: `stream.jsonl` holds the lease Bash call and its result, and `agent-log.json` holds the card sync.
- Check: a dry run appears before an apply with a clean result, or a lease worker run has a `fleet/reconcile` activity on the ticket.

## Gotchas

- A second run at the same time gets `SKIP ... already running` from the board lock.
- A GitHub rate limit makes reconcile stop cleanly. Read the result before rerunning.
- The lease sync writes as the chat's login. When the agent log shows another author, `login` fails even though `board sync` passes: the sync happened, as the wrong agent.
