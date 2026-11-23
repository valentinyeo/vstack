# Valentin mode's three tools

A chat that loads `/valentin-mode` uses three tools: its own board login, the subscription pacer, and the board sync. A chat that never loads it must not start it.

## Sub-features

- `loaded` starts only from the slash command, never on its own.
- `login` writes the board as the chat's own agent.
- `pacer` starts workers through `plan-pick --run`.
- `sync` runs reconcile for its own view.

## How to get to it (user POV)

- Type `/valentin-mode` at the start of a chat.
- Give it a small job that needs a worker and a board note.
- Watch the version line in its first reply.

## Driving it with verify-vstack

This feature is proved by its own skill. Read `.claude/skills/verify-valentin-mode/SKILL.md` and run its `run`, which also has a `--break no-valentin-mode` run that must FAIL.

Preconditions:

- It starts one headless chat in a scratch project and grades the pacer log, the board writes and the hook lines.

## Gotchas

- Never run a test chat with user hooks off; the identity guard goes too.
- The break run must FAIL; a break run that passes means the check is broken.
