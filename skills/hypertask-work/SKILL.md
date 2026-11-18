---
name: hypertask-work
description: How a session works a Hypertask board: own login, own board or view, ticket before work, true column, live worker leases, reconcile, and filing Hypertask gaps. Use when starting work on a Hypertask board, before creating or moving a ticket, when a plain worker must show as live, or when Hypertask cannot do what you need.
---

# Hypertask work

Paths resolve from this skill's folder. vstack `./install` links the folder into every harness.

## Login and board

Start with `~/.local/share/house-rules/skills/board-identity/SKILL.md`.
Never ask Valentin for a login and never print a token.

Own a board or a view named after your repo, or after your Multibot name when you have no repo.
Create the view when it is missing.
Assign yourself to every ticket you work on.

## Ticket first

Every unit starts and ends on a ticket, before any work.
Use `~/.local/share/house-rules/skills/tickets/SKILL.md` for the title, description, labels and comments.
Status, evidence and questions live on the ticket, not in chat.
One open Question, marked as the blocker, with your recommendation under it.

## True column

Board 2060 uses Todo, Doing, Checks, AI Review, Valentin Review, Done.
Move the ticket the moment its work moves:

- start work -> Doing
- PR opened -> Checks
- checks green -> AI Review
- merged -> AI Review, live proof pending
- live proof -> Done

Never move a ticket into Valentin Review.
Only Valentin decides what leaves it.
Other boards keep their own columns.

## Reconcile

Run the reconcile yourself, on your own board, with your own agent login:

```sh
skills/hypertask-work/reconcile --board 2060
```

Read every printed reason.
Then apply with the cap:

```sh
skills/hypertask-work/reconcile --board 2060 --apply --limit 5
```

Set your agent's `HT_TOKEN` and `SHIP_SESSION_NAME` first.
Never use Valentin's personal login.
Reconcile never touches Valentin Review and never moves work to Done.
Read this skill's `reconcile.md` for the column rules, board 15, and the timer.

## Keep workers live

A worker launched with plain `codex exec`, `pi -p` or `cursor-agent` writes no lease.
Reconcile then sees the ticket as dead and sends it back to Todo.

Wrap the launch in one line:

```sh
skills/hypertask-work/lease "$KEY" run -- worker-command worker-arguments
```

For a worker already running:

```sh
skills/hypertask-work/lease "$KEY" watch --pid "$WORKER_PID" &
```

The lease records the PID and host and renews every sixty seconds.
A dead PID, a lease older than fifteen minutes, or no lease reads not live.

## Hypertask gaps

When Hypertask cannot do what you need, file it the same minute:

```sh
hypertask feedback --kind missing|bug|friction --category <category> --tool "<command>" "<one line>"
```

Send command metadata and a sanitized note. Never ticket, board or comment content.
Put the feedback link on the ticket.

## Act as yourself

Never act as Valentin and never use his token.
The Poteto advisor owns `reconcile` and `lease`.
Each orchestrator runs them on its own board.
