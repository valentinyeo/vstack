# Board lint rules

Read-only checker: `skills/hypertask-work/board-lint --board <id>`. No board writes. One line per break: ticket, rule id, owning chat, fix.
Each chat also runs it inside its own drain check, on its own label, where each break prints as a warning line.

| Rule | What it checks | Enforced by |
|---|---|---|
| `agent-assignee` | Open ticket with no agent assignee, a person assignee, a revoked agent, an agent name no Multibot chat ever had, or Doing with no live worker; skips waiting on Valentin or BlockedBy (`identity.md`, `board.md`) | board-lint |
| `true-column` | Card not in the column reconcile would move it to (`board.md` true column) | board-lint; reconcile applies the fix |
| `done-proof` | Done without a PASS verdict on the merged head and without a Done comment with evidence (`board.md`) | board-lint |
| `merged-no-pass` | A merged PR with no PASS on its head (`board.md`); the card plans back to Todo (or Backlog on board 15) | board-lint; drain-check warns |
| `unlinked-work` | Open PR or live worker naming no ticket on this board | written only (fixture-tested); ticket-scoped PR discovery cannot see unlinked open PRs yet |
| `duplicate-title` | Likely duplicate open tickets (same normalized title) | written only; lint prints suggestion |
| `stale-idle` | Open ticket idle past column stale age (`sectionChangedAt`, not `updatedAt`) | board-lint |
| `human-board-write` | On boards 15 or 4060, Valentin user wrote where an agent did the work | none yet when author type missing |
| `label-assignee` | A label that names a live chat or armed loop label does not match the agent assignee; app or classification labels are ignored (`views.md`) | board-lint |
| `sync-record` | Missing or stale board-drain sync record (`sync.md` checkup) | board-lint |
| `no-owner-label` | Open Todo with no chat label (`views.md` label every ticket) | board-lint |
| `unnamed-identity` | Agent assignee is ship-identity fallback `Valentins Claude Code CLI` (`identity.md`) | board-lint |
| `view-filter` | A label that names a chat has no view, or its view does not filter on that label: missing filter shows the whole board (`views.md`) | board-lint; fix with `hypertask view update <view id> --label "<label>"` as the chat's own login |
| `view-owner` | A chat's view is owned by a person, not the chat's agent (`views.md`) | board-lint; report only, recreate the view as the agent login |
| `ticket-split` | One ticket hiding two units of work | written only |
| `agent-lane-results` | `hypertask activity add` carrying results, verdicts, proof, done summaries, or screenshot/video links instead of coordination chatter (`tickets.md`) | `hooks/agent-lane-guard.py` (PreToolUse hook and worker shim) |