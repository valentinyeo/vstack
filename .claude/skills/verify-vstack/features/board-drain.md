# Board drain re-arms itself

A chat restarted after a crash turns its own drain loop back on: it reads loop status, arms a watcher and a safety cron over its view, records the job id, then syncs and passes `drain-check`.

## Sub-features

- `status` reads an expired loop owned by a chat process that is gone.
- `arm` starts the watcher and the safety cron or plan-paced cron at least every 2 hours.
- `record` writes the job id where the loop state expects it.
- `check` passes `drain-check`.

## How to get to it (user POV)

- Start or restart a chat that works a Hypertask view.
- Say `/board-drain`, or let valentin mode load at session start.
- After a crash, the same chat starts again in the same Multibot slot.

## Driving it with verify-vstack

This feature is proved by its own skill. Read `.claude/skills/verify-board-drain/SKILL.md` and run its `run`; this map never repeats those steps.

Preconditions:

- Loop state on disk is expired and owned by a dead process, so `loop-state status` exits 2.
- It starts one headless test chat in a scratch project and grades the side effects, not the chat's claims.

## Gotchas

- A loop that exists but whose owner is alive is not the case under test.
- Evidence lives under `~/.local/state/verify-board-drain/`; keep it, remove only the scratch project.
