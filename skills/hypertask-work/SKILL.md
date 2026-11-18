---
name: hypertask-work
description: >-
  How a session works a Hypertask board: own login, own board or view, ticket before work, true column, live worker leases, reconcile, and filing Hypertask gaps. Use when starting work on a Hypertask board, before creating or moving a ticket, when a plain worker must show as live, or when Hypertask cannot do what you need.
---

# Hypertask work

Prior art: pstack poteto-mode covers task workflows.
Its shipping playbook covers verification and merging.
Neither covers Hypertask login, columns, or leases.

Paths resolve from this folder; vstack `./install` links it into every harness.

## Login and board

Start with `/board-identity`.
Never ask Valentin for a login and never print a token.

Own a board or view named after your repo, or after your Multibot name when you have no repo.
Create the view when it is missing.
Assign yourself to every ticket you work on.

## Ticket first

Every unit starts and ends on a ticket, before any work.
Use `/tickets` for the title, description, labels and comments.
Status, evidence and questions live on the ticket, not in chat.
One open Question, marked as the blocker, with your recommendation under it.

## True column

Board 2060 uses Todo, Doing or Building, Checks, AI Review or Verifier, Valentin Review, Done.
Use the name the board shows.
An open or merged PR outranks a live worker.

- worker starts -> Doing or Building
- PR opened -> Checks
- checks green -> AI Review or Verifier
- merged -> AI Review or Verifier, live proof pending
- live proof -> Done

A ticket waiting on Valentin or blocked by another ticket stays put.
Never move a ticket into Valentin Review.
Only Valentin decides what leaves it.
Other boards keep their own columns.

## Reconcile

Run the reconcile yourself, on your own board, with your own agent login:

```sh
skills/hypertask-work/reconcile --board 2060
```

Read every printed reason.
Then apply with the cap.
A plan over the cap applies the first moves and prints DEFERRED for the rest:

```sh
skills/hypertask-work/reconcile --board 2060 --apply --limit 5
```

Set your agent's `HT_TOKEN` and `SHIP_SESSION_NAME` first.
Never use Valentin's personal login.
Reconcile never touches Valentin Review and never moves work to Done.
Read this skill's `reconcile.md` for the column rules, board 15, and the timer.

## Keep workers live

A worker launched with plain `codex exec`, `pi -p` or `cursor-agent` writes no lease.
A running command line that holds the ticket key or ticket URL still counts as live,
so such a worker keeps its ticket without one.
Wrap the launch anyway, because a lease is the stronger sign:

```sh
skills/hypertask-work/lease "$KEY" run -- worker-command worker-arguments
```

For a worker already running:

```sh
skills/hypertask-work/lease "$KEY" watch --pid "$WORKER_PID" &
```

The lease records the PID and host and renews every minute.
A dead PID, a 15-minute-old lease, or no lease reads not live,
unless a live local process names the ticket in its arguments.

## Hypertask gaps

File a Hypertask gap the same minute:

```sh
hypertask feedback --kind missing|bug|friction --category <category> --tool "<command>" "<one line>"
```

Send command metadata and a sanitized note, never ticket content.
Put the feedback link on the ticket.

## Act as yourself

Never act as Valentin and never use his token.
Fleet Tools owns the script's code (`reconcile` and `lease`).
Each orchestrator runs them on its own board.
