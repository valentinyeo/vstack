# The test guard holds

`hooks/test-timeout-guard.py` refuses a test or build command with no timeout in front of it, and lets a wrapped one through unchanged.

## Sub-features

- `block` refuses a bare runner and names the one-line fix.
- `allow` passes the same command once a timeout wraps it.
- `real` proves a real 5 second timeout kills a real 60 second sleep.

## How to get to it (user POV)

- Start a test or build command in any vstack chat.
- The guard runs before the command does.
- A refused command prints the fix in its error.

## Driving it with verify-vstack

This feature is proved by its own skill. Read `.claude/skills/verify-test-timeout/SKILL.md` and run its `run`.

Preconditions:

- It feeds the real hook real PreToolUse JSON, then measures one real timeout, so exit codes and one second count carry the verdict.

## Gotchas

- The guard is registered fail-open, so a missing link makes it stop running without an error. `CHECK wiring` proves the link; this feature proves the behaviour.
