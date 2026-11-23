# Plain words before a ticket comment

## Sub-features

- `unjargon/SKILL.md` read, or `pospeak/SKILL.md`, before the first ticket comment write.

## How to get to it (user POV)

Valentin asks for a ticket comment about a change. The rule is that the chat writes it in plain words, so it reads the plain-words skill first.

## Driving it with run

```sh
.claude/skills/verify-valentin-subskills/run --scenario plain-words
```

PASS when a read of `unjargon/SKILL.md` or `pospeak/SKILL.md` comes before the first ticket comment write in the stream.

## Gotchas

- The chat reads skills through its own tool names; match the read by path suffix, not by a fixed tool.
- `--break plain-words` renames the `unjargon` rule line away, so the same run must FAIL.
