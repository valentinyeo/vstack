# Board drain verification map

The restart a chat survives, split into the three things it must do on its own, each proved by one or two checks in `grade.py`. Read this, then the file for the check.

## Baseline preconditions

- `~/.local/share/vstack/skills/board-drain` holds the board drain under test, installed with `./install`, and is symlinked from `~/.claude/skills/board-drain` so `/board-drain` is a command.
- Test login "VVM Test Agent" (board 2060) exists; board 2060 carries the label `vvm-test` as the test queue.
- `plan-pick --claude-helper` exits 0.
- Claude Code's `CronCreate` tool is enabled.

## Driving conventions

- Only `run` starts a chat. One run at a time, because the board sync takes a lock per board.
- One seeded fact: `<scratch>/state/vbd-test-chat.json` is an expired loop from a dead chat process. `loop-state status --name "VBD Test Chat"` must exit 2 before the chat starts.
- The prompt names the restart, never a script. A chat that reads, arms, records, syncs and checks learned that from `skills/board-drain/SKILL.md`.

## Proof and skip reporting

- Every check reads a side effect: the stream's tool calls, or the state file the chat left on disk.
- A check that could not run (no stream, a run that fails the gate) reports FAIL with the reason, never as PASS.

## Features

| File | Checks | Feature |
| --- | --- | --- |
| [restart-rearm.md](restart-rearm.md) | `loaded`, `status-read`, `armed`, `recorded` | The loop is armed again after a restart, and recorded |
| [sync.md](sync.md) | `synced` | The tick syncs the board as the chat's own login |
| [check.md](check.md) | `checked`, `no-writes` | drain-check runs on the chat's own state, and nothing else moves |
