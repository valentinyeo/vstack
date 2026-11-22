# Board lint rules

Read-only checker: `skills/hypertask-work/board-lint --board <id>`. No board writes. One line per break: ticket, rule id, owning chat, fix.

| Rule | What it checks | Enforced by |
|---|---|---|
| `agent-assignee` | Open ticket with no agent assignee, or assignee name not a live chat; skips waiting on Valentin or BlockedBy (`identity.md`, `board.md`) | board-lint |
| `true-column` | Card not in the column reconcile would move it to (`board.md` true column) | board-lint; reconcile applies the fix |
| `done-proof` | Done without live proof (`board.md`); merged PR alone is not Done on factory boards | board-lint |
| `unlinked-work` | Open PR or live worker naming no ticket on this board | written only (fixture-tested); ticket-scoped PR discovery cannot see unlinked open PRs yet |
| `duplicate-title` | Likely duplicate open tickets (same normalized title) | written only; lint prints suggestion |
| `stale-idle` | Open ticket idle past column stale age (`sectionChangedAt`, not `updatedAt`) | board-lint |
| `human-board-write` | On boards 15 or 4060, Valentin user wrote where an agent did the work | none yet when author type missing |
| `label-assignee` | A label that names a live chat or armed loop label does not match the agent assignee; app or classification labels are ignored (`views.md`) | board-lint |
| `sync-record` | Missing or stale board-drain sync record (`sync.md` checkup) | board-lint |
| `no-owner-label` | Open Todo with no chat label (`views.md` label every ticket) | board-lint |
| `unnamed-identity` | Agent assignee is ship-identity fallback `Valentins Claude Code CLI` (`identity.md`) | board-lint |
| `ticket-split` | One ticket hiding two units of work | written only |