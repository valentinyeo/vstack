# The host verdict

`vps-state` answers whether this server can take another chat, worker, build or test run, and a second read of the host agrees with every number it prints.

## Sub-features

- `json` and `brief` answer in machine and human form.
- `can-launch` answers for chat and worker separately.
- `hook` prints the SessionStart line.

## How to get to it (user POV)

- Ask for housekeeping, or before starting a chat, worker, build or test run.
- Read the brief block, or call `--json` from a script.
- The SessionStart hook prints it as a chat opens.

## Driving it with verify-vstack

This feature is proved by its own skill. Read `.claude/skills/verify-vps-state/SKILL.md` and run its `run`.

Preconditions:

- No server to start: `run` takes `--script` to pick the copy to drive, then re-reads load, memory and disk with `nproc`, `/proc/loadavg`, `free` and `df`.

## Gotchas

- A verdict with no comparison against the host is not proof.
- Exit 3 means the doctor failed, not that the host is fine.
