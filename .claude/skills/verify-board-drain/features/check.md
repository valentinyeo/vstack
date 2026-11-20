# Check

The tick ends with `./drain-check --board <id> --label <label> --state-name "<chat>"`, which names the fix for every finding: `loop off`, `stalled`, `stale`, `answered`, `not armed`, `sync failed`, `sync stale`.

## Sub-features

- `check.run`: a `Bash` call runs `drain-check` with `--state-name`, so the chat's own loop state is part of the check.
- `check.clean`: the run does not need a passing drain-check. A ticket that is waiting, stalled or stale on board 2060 is out of this skill's hands and does not fail it.
- `check.no-writes`: no `task move`, `task update`, `comment add` or `plan-pick --run` ran during the test.

## How to get to it (user POV)

- The chat finishes a tick, or wants to know whether the queue is moving.
- It runs the check and reads the findings, instead of assuming the loop is fine.

## Driving it with run

Preconditions: `BOARD_DRAIN_STATE_DIR` points at the scratch state, so the check reads the loop the chat just armed, not a real chat's.

- Action: `run`. Result: `stream.jsonl` holds the `drain-check` call and its output.
- Check `checked`: a `Bash` call whose command runs `drain-check` with `--state-name`.
- Check `no-writes`: no command moves, updates, comments or starts a worker. The prompt forbids it; the check proves the chat obeyed.

## Gotchas

- The test chat is told `arming, syncing and checking is enough`. It may report findings on board 2060; it may not act on them. An acting chat fails `no-writes`.
- `drain-check` exits 2 on a crash or a usage error and 1 on findings. The check grades the call, not the exit code, because a real finding on the test label is not a failure of board drain.
- A measured run got `drain-check: hypertask --json failed: plan-pick worker: no board login` because `hypertask` resolved to a worker shim on `PATH`; `sync` in the same chat logged in fine. `checked` still passes on the call. Read `status-before-exit` first when every board call in a run fails.
- A chat that runs `drain-check` without `--state-name` proves less: it never reads its own loop. That fails `checked`.
