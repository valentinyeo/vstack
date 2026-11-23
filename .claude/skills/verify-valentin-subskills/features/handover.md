# The long-chat handover

## Sub-features

- `long-chat/SKILL.md` read before the handover file is written.
- `~/.local/state/long-chat/<session>.md` starts with the handover's required first line.

## How to get to it (user POV)

The chat is long enough to need a handover. The rule is that the chat writes the handover file in the long-chat shape, first line included.

## Driving it with run

```sh
.claude/skills/verify-valentin-subskills/run --scenario handover
```

PASS when the handover file starts with the required first line and `long-chat/SKILL.md` was read before it was written.

## Gotchas

- Read the installed state path, not a copy inside the scratch repo.
- `--break handover` removes the handover rule, so the same run must FAIL.
