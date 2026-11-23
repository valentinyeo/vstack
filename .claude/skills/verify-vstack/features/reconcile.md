# Board sync reads a board right

`skills/hypertask-work/reconcile` reads a real board and plans the moves that make each card match its column, then converges when applied.

## Sub-features

- `dry-run` plans moves without writing.
- `apply` writes them, bounded by `--limit`.
- `converge` plans nothing on a second dry run.
- `calls` stays inside the GitHub budget of one dry run.

## How to get to it (user POV)

- Run reconcile from a chat that owns a board view.
- Read the plan lines before applying anything.
- Apply with a label or a ticket scope, never bare.

## Driving it with verify-vstack

This feature is proved by its own skill. Read `.claude/skills/verify-reconcile/SKILL.md` and run its `run`.

Preconditions:

- The proof bar is apply, then a second dry run that plans no moves. A dry run alone proves nothing.

## Gotchas

- A bare `--apply` can move real tickets. Always scope it.
- GitHub graphql budget above 200 before a board 15 run.
