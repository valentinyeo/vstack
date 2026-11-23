# Hypertask setup and a worked task

With only the hypertask skill, a fresh chat sets itself up on a board and works a task: it uses its own agent login, makes its view and label, writes the board line, files one ticket, then syncs the board dry and applied.

## Sub-features

- `login` uses the chat's own agent token, never Valentin's.
- `wire` writes the project's board line.
- `ticket` files one ticket in its own label.
- `sync` runs dry, then applies.

## How to get to it (user POV)

- Start a fresh chat in an empty project.
- Say `/hypertask` and ask for setup on a board plus one small job.
- A chat that already has a board line skips the wiring step.

## Driving it with verify-vstack

This feature is proved by its own skill. Read `.claude/skills/verify-hypertask/SKILL.md` and run its `run`.

Preconditions:

- It starts one headless chat in an empty scratch repo with no `CLAUDE.md`, so the chat must write the board line itself.

## Gotchas

- Never reuse another agent's token.
- One board sync at a time: the lock is per board.
- A test run files one ticket in label `vvm-test`; archive it by hand afterwards.
