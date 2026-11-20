# Board line

## Sub-feature

- `board line`: the scratch repo's notes hold `Hypertask board: 2060`.

The line is per repo, so the label part is optional. When the line names a label, it must be `vvm-test`.

## How to get there (user POV)

The prompt asks for setup in a repo with no notes, so the chat has to create them.

## Driving it with run

- Action: `run`. Result: `notes.md`, copied from the scratch project's CLAUDE.md or AGENTS.md.
- Check: one line matches `Hypertask board: 2060` with no label or with `label: vvm-test`.

## Gotchas

- A line for another board, or a label for another chat, fails.
