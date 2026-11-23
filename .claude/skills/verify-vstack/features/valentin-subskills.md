# Valentin mode's sub-rules

A fresh chat follows the sub-rules valentin mode sets: plain words before a ticket comment, `report-page` before a report, a ticket for each ask, the long-chat handover's first line, and `pr-queue --mine`.

## Sub-features

- `plain-words` reads the plain-words skill before it comments on a ticket.
- `report` reads report-page before it writes an HTML page.
- `ticket` files a ticket before it starts the work.
- `handover` writes the handover file with the right first line.
- `prs` runs `pr-queue` with `--mine` and its chat name.

## How to get to it (user POV)

- Load `/valentin-mode`, then ask for one of those jobs.
- The rules apply without the user naming them.
- A `--break` run strips the rule's source and the same check fails.

## Driving it with verify-vstack

This feature is proved by its own skill. Read `.claude/skills/verify-valentin-subskills/SKILL.md` and run one scenario at a time.

Preconditions:

- Each scenario is one cheap Sonnet chat, graded from its ordered tool calls.

## Gotchas

- Read the `--break` verdict on any PR, and say which scenarios ran live.
- A FAIL is a finding about the chat, not a broken check.
