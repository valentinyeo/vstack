# Boards, columns and leases

## Columns

Use the name the board shows. Never invent a column.

Software Factory board 2060:

| Column | What it means |
|---|---|
| Verification Backlog | A verification ticket with the `verification` label, not started. |
| Todo | Ready, nobody on it. |
| Doing (or Building) | A live worker is on it. |
| Checks | A PR is open and its checks run, fail or are missing. |
| AI Review (or Verifier) | Checks are green, or a PR is merged and live proof is pending. |
| Valentin Review | His call. Only he moves a ticket out. |
| Done | Live, with proof. |

Board 15 (Hypertask product) uses Backlog, In Progress and AI Review, and keeps its own protected columns. Any other board keeps its own columns; the reconcile reads them.

Ticket keys carry the board prefix: `VSTA-` on 13556, `SOFT-` on 2060, `HTPR-` on 15.

## True column

Move the ticket the moment its stage moves. The PR outranks a live worker.

- worker starts -> Doing or Building
- PR opened -> Checks
- checks green -> AI Review or Verifier
- merged -> AI Review or Verifier, live proof pending
- live proof -> Done

A ticket waiting on Valentin, or blocked by another ticket, stays where it is. Never move a ticket into Valentin Review. Other boards keep their own columns; use the name the board shows, including the `Building` and `Verifier` aliases.

Verification tickets carry the label `verification` and start in Verification Backlog. The reconcile moves a labelled ticket out of Todo into that column, and an unlabelled one back to Todo. An open or merged PR still outranks the label.

## Protected columns

Valentin Review, Done and Not now never move. On board 15 the protected columns are UX needed, UX Sign-off, Agent Blocked (Infra), Valentin Review, QA and every Flag column. On any board, a column the reconcile does not recognise stays put.

## Manual override

```bash
hypertask task move <ticket> --section "<name>"
```

A hand move is allowed when the board is wrong and the reconcile will not fix it in time. Say why in an agent-lane note. A hand move is also a gap in the reconcile: report it (see `sync.md`).

## Worker leases

A launch through the lease writes a lease; a plain agent launch writes none. Wrap the launch:

```bash
skills/hypertask-work/lease "$KEY" run -- worker-command worker-arguments
```

An already running worker:

```bash
skills/hypertask-work/lease "$KEY" watch --pid "$WORKER_PID" &
```

Manual lifecycle:

```bash
skills/hypertask-work/lease "$KEY" start --pid "$WORKER_PID"
skills/hypertask-work/lease "$KEY" beat --pid "$WORKER_PID"
skills/hypertask-work/lease "$KEY" end --pid "$WORKER_PID"
```

The lease records the worker PID and host and renews every minute. It lives in `~/.local/state/fleet/leases/<KEY>.json` with `pid`, `host`, `started` and `last_beat`. A live worker cannot replace another worker's lease.

A worker is live when the lease is fresh and its PID exists, or when a live agent CLI process (`hax`, `pi`, `codex`, `cursor-agent`, `claude`, `opencode`, `gemini`) names the ticket in its arguments and is not under another worker's lease. A dead PID, a lease older than 15 minutes, a search, a grep or any other command that only reads the ticket is not a live worker.

The lease syncs the card when the worker starts and ends, and takes the ticket as its agent when the ticket has no agent assignee. See `sync.md`.
