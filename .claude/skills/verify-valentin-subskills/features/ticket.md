# A ticket for every new ask

## Sub-features

- A board ticket created before the ask's file is written.

## How to get to it (user POV)

Valentin asks for a small piece of work. The rule is that each ask becomes a ticket and a worker, so the ticket exists before the work lands.

## Driving it with run

```sh
.claude/skills/verify-valentin-subskills/run --scenario ticket
```

PASS when a board ticket is created before the ask's file is written in the stream.

## Gotchas

- The scratch repo's fake board resolves writes to the test login; a ticket on another board does not count.
- `--break ticket` removes the ticket rule, so the same run must FAIL.
