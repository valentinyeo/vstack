# One ticket

## Sub-feature

- `ticket.one`: exactly one task on board 2060 carries label `vvm-test` and was created at or after `started_at`.

## How to get there (user POV)

The prompt asks the chat to file one ticket in its label for the tiny job.

## Driving it with run

- Action: `run`. Result: `tasks.json` from `task list --project 2060 --label vvm-test`.
- Check: the count of new tasks is exactly one.

## Gotchas

- SOFT-2849 carries the label and is older, so it never counts.
- Zero tickets fails; two or more fails.
- The ticket stays on the board. `run` prints its key so the owner can archive it.
