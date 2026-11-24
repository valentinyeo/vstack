---
name: hypertask
description: >-
  Everything an agent needs to work with Hypertask: its own agent login, the
  hypertask CLI, tickets and comments, columns and worker leases, views and
  labels, board sync, the checkup, and what to file a ticket for. Use for any
  Hypertask work: filing, onboarding or writing a ticket, comments, boards,
  views, agent login, board sync, the checkup, or when Hypertask cannot do
  what you need.
---

# Hypertask

Prior art: pstack `poteto-mode` was checked for task workflow rules; it covers shipping, not board login, columns or leases. This skill replaces vstack's `hypertask-work` and `hypertask-checkup`, house-rules' `board-identity` and `tickets`, and the local ticket skill.

## Always on

- Act only as your own agent login. Never write as Valentin and never use his token.
- No login of your own means no board write. Get the login first.
- One unit of work, one ticket. It starts before the work and ends in Done with proof.
- Never delete a ticket. Archive it, or move it to Done.
- A Hypertask command that fails unexpectedly is a fault. File `hypertask feedback` the same minute, then keep working.
- Every real step on a ticket gets one short people comment in plain words, so Valentin can follow it without the agent lane.
- Read the one reference file for the topic you are on. Do not work from memory of an old skill.

## Map

| Read | When |
|---|---|
| `references/identity.md` | Before your first board write: own login, one name everywhere, adding yourself to a board, assignment. |
| `references/cli.md` | Any Hypertask command: shapes, `--json`, `--help`, capabilities, attachments, the feedback flags. |
| `references/tickets.md` | Filing, onboarding or writing a ticket or comment: parts, labels, Questions, the guard. |
| `references/board.md` | Creating or moving a ticket: columns, true column, protected columns, manual overrides, worker leases. |
| `references/views.md` | Setting up your own view and label, or reading a board line. |
| `references/sync.md` | Setting up or debugging board sync: lease events, the board watcher, status records, reconcile flags, reporting a miss. |
| `references/checkup.md` | Running the checkup: the checks and what each one fixes. |
| `references/board-lint-rules.md` | Board rule ids, what enforces each, and the read-only lint command. |

## Three commands

**File a ticket from one line.** `/hypertask <the problem or ask>` files one ticket on the project's board, as you, with a brain tag, then onboards it. Read `references/tickets.md` first.

**Onboard a ticket by id.** `/hypertask VSTA-33` or a ticket URL sets you up on that ticket: read it, move it to its working column, put your name on it, print the `/rename` line. Read `references/tickets.md` first.

**Run the checkup.** `/hypertask checkup` health-checks your own board and view, fixes your gaps, and reports one line per check. Read `references/checkup.md` first.
