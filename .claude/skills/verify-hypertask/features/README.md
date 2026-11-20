# Hypertask skill verification map

Six checks, one per thing the hypertask skill must make a fresh chat do. Read this, then the file for the check.

## Baseline preconditions

- `~/.local/share/vstack` holds the skill under test, installed with `./install`.
- The scratch repo has no project notes; the chat writes them.
- Test login "VVM Test Agent" and scratch ticket SOFT-2849 (label `vvm-test`) exist on board 2060.
- `plan-pick --claude-helper` exits 0.

## Driving conventions

- Only `run` starts a chat. One run at a time.
- The prompt begins with `/hypertask`, never a tool name. A chat that sets itself up learned it from the skill.

## Proof and skip reporting

- Each check reads a side effect: a tool call, a board author field, the notes file, a ticket, a sync result.
- Report a check that could not run (no init line, gate closed) as not run, never as PASS.

## Features

| File | Check | Rule it proves |
| --- | --- | --- |
| [read.md](read.md) | `read` | The chat reads the skill |
| [login.md](login.md) | `login` | Own agent login, never Valentin's |
| [view.md](view.md) | `view` | Own view and label |
| [board-line.md](board-line.md) | `board line` | The board line, written by the chat |
| [ticket.md](ticket.md) | `ticket` | One ticket filed in the label |
| [sync.md](sync.md) | `sync` | Reconcile dry, then apply with the label |
