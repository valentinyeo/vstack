# The chat's own pull requests

## Sub-features

- A `pr-queue` run that carries `--mine` and a chat name.

## How to get to it (user POV)

Valentin asks what is open for this chat. The rule is that the chat runs pr-housekeeping on its own PRs, never the whole queue.

## Driving it with run

```sh
.claude/skills/verify-valentin-subskills/run --scenario prs
```

PASS when a `pr-queue` run in the stream carries `--mine` and a chat name.

## Gotchas

- `pr-queue` may exit non-zero on an empty queue; grade the arguments, not the exit code.
- `--break prs` removes the pr-housekeeping rule, so the same run must FAIL.
