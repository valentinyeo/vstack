# Responsive mode answers and finishes

A chat in responsive mode answers every message quickly and still finishes the job, including a job that ends in a pushed commit.

## Sub-features

- `fast` answers within about 60 seconds of each message.
- `mid-turn` answers a side question at the next tool result.
- `finish` ends with the commit pushed to origin, not with a claim.
- `complete` ends the turn with each item done, tracked or waiting on Valentin.

## How to get to it (user POV)

- Say `/responsive-mode`, or let valentin mode load it.
- Send a job, then two side questions while it runs.
- Check origin for the pushed commit.

## Driving it with verify-vstack

This feature is proved by its own skill. Read `.claude/skills/verify-responsive-mode/SKILL.md` and run its `run`.

Preconditions:

- Timestamps prove speed. Origin proves the finish, so the grade reads the remote, never the chat's words.

## Gotchas

- A fast reply with an unfinished job is a FAIL for this feature, not a partial pass.
- One Sonnet chat per run, gated on pace.
