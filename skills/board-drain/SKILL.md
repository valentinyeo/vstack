---
name: board-drain
description: "board drain;drain my board;drain loop;is my loop armed;work my view. /board-drain: a chat runs pstack Autopilot-full on its own Hypertask view, armed and checked until every ticket is done, waiting on Valentin, or blocked. Use at session start, after a restart or handover, when valentin-mode loads, or when drain-check fails."
---

# Board drain

Prior art: pstack poteto-mode Autopilot-full with a verifier that never wrote the code. `/hypertask` owns columns and reconcile, not which queue you drain or what counts as waiting on Valentin.

## The loop is Autopilot-full

The queue is your own view: `Hypertask board: <id>` in your agent notes, labelled from your chat name. Add it when missing.
The loop prompt:

```text
/pstack:poteto-mode full autopilot on this queue: every workable ticket in my view <view URL>. each item is independent. done when skills/board-drain/drain-check --board <id> --label <label> passes.
```

Owners start through `~/.local/bin/plan-pick --run` in `../hypertask-work/lease`, never as Claude chats; columns follow `/hypertask` and references/board.md, never Valentin Review. Read the lease's last line and its exit status: `worker exited 75: nothing ran, waiting for a lane` means no lane was free, so report waiting, not started. A launch command ending in `| tail` hands bash `tail`'s 0 and hides that status; keep the status with `set -o pipefail` or no pipe.

## Arm

Session crons die with the chat; recurring ones expire in 7 days. Arm at session start, restart, handover, valentin-mode load, or any drain-check fail:

1. `./loop-state status --name "<your Multibot name>"`. Exit 0: already armed.
2. **Claude Code:** `./watch --board <id> --label <label> --name "<name>"` as a background Bash job (`run_in_background`, 7200000 ms). It pulses `loop-state` every 3m and keeps polling across changes and heartbeats; `board-drain-guard` holds Stop and pushes Valentin after 10m dead (VSTA-151).
3. Arm a safety cron at the larger of 6h and `~/.local/bin/plan-pick --loop-interval` (at least 2h) with the loop prompt. Record: `./loop-state arm --name "<name>" --every <interval> --job <id> --board <id> --label <label>`.
4. **Codex or chats without background jobs:** one recurring job on `~/.local/bin/plan-pick --loop-interval` (at least 2h) with the loop prompt; record with `loop-state arm`.
5. If a crash or restart kills the watcher, restart step 2.

`watch` arms independent 15-minute sync via `board-sync@<name-slug>.timer`; for `sync timer off`, run `./loop-state timer --board <id> --label <label> --name "<name>"`.

On changes, sync failures or heartbeats, `watch` sends its own tab the change and `run drain-check` via `mp-send`, matching its tmux to agent-host `sid`. It keeps polling, coalescing wakes to one per 60s. If delivery is unavailable or fails, it prints and exits 0; the tracked job wakes the chat. Re-arm step 2.

Never delete the loop for an empty Todo; a tick with nothing new stays quiet.

## Each tick adds

1. **Sync.** `./sync --board <id> --label <label> --name "<name>"` (references/sync.md): preview, then `--apply --limit 5`. Usage or non-zero exit prints `sync: FAIL` until it works.
2. **New tickets.** A workable ownerless Todo ticket gets an owner.
3. **Waits.** Read the newest comments on each waiting ticket first. Valentin's yes makes it workable: clear the mark, assign an owner.
4. **Check.** `./drain-check --board <id> --label <label> --state-name "<name>"`.
5. **Re-arm.** `loop-state status` exit 3 means expiry within a day: arm, record a fresh loop, delete the old.
6. **Daily.** `/hypertask checkup` once a day.

## What counts as waiting

Only a set waiting-on mark naming Valentin, or a blocker comment, counts; a chat's memory does not. An unmarked ticket is workable. Mark a real wait.

BlockedBy open tickets stay out via links, not memory. drain-check reads `task relations` per unmarked Todo and prints `blocked: <KEY> by ...`; news, not a fail.

## drain-check fails

- **loop off:** workable Todo, nothing alive in Doing. Re-arm, then give the named ticket an owner.
- **unassigned:** a ticket in a working column with no agent. Assign your login: `task assign <KEY> --self`.
- **stalled:** Doing ticket, no live owner. Fresh plan-pick owner; tickets moved across boards get a new key, so check the old lease first.
- **orphan PR:** a card of yours with an open PR and no live helper. Start a helper on that PR before any new ticket.
- **stuck:** a Checks card whose PR is red with no push and no live worker for an hour. Check the lease first; if none, start a fresh plan-pick owner that fixes the PR or closes it.
- **stale:** a workable Todo ticket idle over two hours. Give it an owner; note the gap on your role ticket.
- **over cap:** more than 10 cards in Checks+AI Review, the two columns `/hypertask` owns. Finish those first: this one fails, and **loop off** and **stale** stay quiet until the board drains, so it is the only work to do. `lease <KEY> run` refuses a non-urgent Todo start with exit 75 and one `lease: <KEY> held: ...` line; an urgent ticket may still start.
- **answered:** Valentin replied after the waiting-on mark. Clear the mark and work it.
- **not armed** or **watcher dead since <time>:** the chat restarted, the loop expired, or the watcher stopped pulsing. Arm it.
- **sync failed** or **sync stale:** the last sync broke or is over 45 minutes old. Fix it, then `./sync --board <id> --label <label> --name "<name>"`.
- **sync skipped:** the chat is over its gh budget. `./sync` prints one `sync skipped: gh budget (wait until HH:MM UTC)` line and exits 0, and the watcher keeps watching. Nothing to fix; a skip is never `sync failed`. If the skips outlast 45 minutes it reads as **sync stale** instead.

A `vps-state` HOLD turns **loop off** and **stale** into one non-failing `held:` line. When plan-pick last found no free worker lane (a `lane` failure with exit 75 in `~/.local/state/token-ladder/rung-attempts.json`, or the null-lane row it logs in `launches.jsonl` when no lane is left, either under 30 minutes old, with no launch since), **loop off**, **stale** and **stalled** collapse into one non-failing `held: no worker lane since <HH:MM UTC>` line; a server HOLD wins. `--no-load` skips both probes.

A board-rule break prints as `rule-break: <ticket> <rule>: <fix>` and passes; add its rule id to `FAIL_RULES` in drain-check to make it fail.

A fail that returns is a gap: file it on board 13556, label Board Drain Loop, with the output.

## Rules

- Your login and your tickets only. Never move another chat's tickets.
- Never move a ticket into Valentin Review, or to Done without a PASS verdict or live proof.
- Reconcile bugs go to Hypertask Reconciler; PR follow-up follows the PR owner rules in valentin-mode.