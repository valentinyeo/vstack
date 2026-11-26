# Board drain re-arms itself

A chat restarted after a crash turns its own drain loop back on without being told: it reads its loop status, arms a loop over its own view, records the job id, syncs the board and passes `drain-check`. Session cron jobs die with the process and a recurring cron expires after 7 days, so the loop state on disk is expired and owned by a chat process that is gone.

## Sub-features

- `rearm.load`: the chat loads board drain through the `/board-drain` command or the `Skill` tool.
- `rearm.status`: it runs `loop-state status --name "<its name>"` before arming, because exit 0 means already armed.
- `rearm.arm`: either a `Bash` call running `skills/board-drain/watch --detach` (its own systemd --user unit), or a `Bash` call with `run_in_background: true` running `skills/board-drain/watch` with this chat's `--board` and `--label` plus a safety `CronCreate` of at most 6 hours, or a recurring cron on the plan pace (at least every 2 hours) carrying the loop prompt.
- `rearm.record`: `loop-state arm` writes `armed_at` in this run, `expires_at` about 7 days later and the job id the harness returned, without dropping `last_sync`.
- `sync.run`: `./sync --board <id> --label <label> --name "<chat>" --limit 5` runs the reconcile preview, then an apply of up to five moves.
- `sync.ok`: `last_sync.ok` is true and `at` is after the run started.
- `sync.kept`: the sync record survives the arming, because `loop-state arm` rewrites the file.
- `check.run`: a `Bash` call runs `./drain-check --board <id> --label <label> --state-name "<chat>"`, so the chat's own loop is part of the check.
- `check.clean`: the run does not need a passing drain-check. A waiting, stalled or stale ticket on board 2060 is not this skill's failure.
- `check.no-writes`: no `task move`, `task update`, `comment add` or `plan-pick --run` ran during the test.

## How to get to it (user POV)

- Start or restart a chat that works a Hypertask view, in the same Multibot slot it crashed in.
- Say `/board-drain`, or let valentin mode load at session start.
- The user asks the chat to keep its board work going. It should not need to be told to arm again.
- A tick starts, or `drain-check` prints `loop off`, `stalled`, `stale`, `answered`, `not armed`, `sync failed` or `sync stale`.

## Driving it with verify-vstack

Preconditions:

- Test login "VVM Test Agent" on board 2060, token at `~/.config/hypertask-agents/credentials/sessions/vvm-test-agent-agent-token` (server only, never print it). Recreate a lost login with the `/hypertask` identity steps, never another agent's token.
- Board 2060 carries label `vvm-test` as the test queue, with no real work on it.
- `~/.local/bin/plan-pick --claude-helper` exits 0.
- `~/.local/share/vstack/skills/board-drain` holds the board drain under test, installed with `./install` and linked so `/board-drain` is a command. On a PR, install the branch, then restore main.

- **Real run.** Run `.claude/skills/verify-vstack/tools/board-drain/run`. It gates on plan-pick, builds a scratch git repo in `/tmp/vbd-scratch.*` with this checkout's `skills/board-drain` and `skills/hypertask-work`, seeds `<scratch>/state/vbd-test-chat.json` with an expired loop from a dead chat, and refuses to start unless `loop-state status` exits 2 on it. It then starts `claude -p` with `BOARD_DRAIN_STATE_DIR=<scratch>/state`, `HT_TOKEN` from the token file and `SHIP_SESSION_NAME="VBD Test Chat"`, under `--model sonnet --output-format stream-json --verbose --max-turns 30` and a 15 minute timeout. The prompt starts with `/board-drain`, says the chat just restarted, and never names a script. Expect `VERDICT PASS`. One run takes 3 to 10 minutes.
- **Break run.** Run `.claude/skills/verify-vstack/tools/board-drain/run --break no-board-drain`. It drops the leading command and adds `--disable-slash-commands` with hooks left on, so no board drain exists for that chat. Expect `VERDICT FAIL` on `rearm.load`.
- **Read the checks.** `rearm.load`, `rearm.status`, `rearm.armed` and `rearm.recorded` read the stream's tool calls and the state file the chat left. `rearm.armed` takes either arm shape, matched to board `2060` and label `vvm-test`. `sync.synced` and `check.checked` read the same state and stream.
- **Evidence.** Every run keeps `~/.local/state/verify-board-drain/<run-id>/`: `stream.jsonl` (tokens scrubbed), `state-before.json` and `status-before.txt` (the seeded expired loop), `state.json` (the loop the chat left), `prompt.txt`, `verdict.txt` and `verdict.json`. Attach both verdict files to a PR.
- **Regrade a saved run.** Run `.claude/skills/verify-vstack/tools/board-drain/grade.py ~/.local/state/verify-board-drain/<run-id>`, which starts no new chat.
- **Cleanup.** `run` removes only its own `/tmp/vbd-scratch.*` folder, never the evidence. `--keep` keeps the scratch repo.

## Gotchas

- The watcher pulses into `loop-state` on every poll, so a restart or a kill leaves the time it died there. `loop-state status` reads that silence as `watcher dead since <time>`, and the chat's own `board-drain-guard` hook says so in its next turn (VSTA-151). A scratch chat that is not a Multibot chat has no tab, so the hook stays silent in a `run` and only the skill's own instructions drive the re-arm.
- `CronCreate` is available in `claude -p` (checked on 2.1.329) but often arrives through `ToolSearch` first. The chat searching for it is normal.
- Two arms, two shapes. Claude Code starts the watcher in the background and keeps a safety cron; Codex keeps a plan-paced cron. `armed` passes either; a watcher on another board or label, a one-shot job, or a cron firing more often than every 2 hours fails on purpose.
- A session-only cron dies with the chat. The state file survives a restart; a live job does not.
- Order matters. Syncing after arming still works because `loop-state arm` keeps `last_sync`.
- Dropping the command alone cannot fail. The installed description says "use after a restart", so a restarted chat loads board drain without being told (VSTA-4). The break removes the skill too.
- Keep user hooks on. `--setting-sources` would drop the guard against writing as Valentin.
- One run at a time: the board 2060 reconcile takes a lock, and a second run gets `already running`.
- `drain-check` exits 2 on a crash or usage error and 1 on findings. The check grades the call, not the exit code, because a real finding on the test label is not a board drain failure.
- A measured run got `drain-check: hypertask --json failed: plan-pick worker: no board login` because `hypertask` resolved to a worker shim on `PATH`, while `sync` logged in fine. Read `status-before-exit` first when every board call in a run fails.
