---
name: board-drain
description: "board drain;drain my board;drain loop;is my loop armed;work my view. /board-drain: a chat runs pstack Autopilot-full on its own Hypertask view, armed and checked until every ticket is done, waiting on Valentin, or blocked. Use at session start, after a restart or handover, when valentin-mode loads, or when drain-check fails."
---

# Board drain

Prior art: pstack poteto-mode Autopilot-full runs one owner per item, a verifier that never wrote the code, an audit loop for stuck agents. The `/hypertask` skill owns columns and the reconcile; neither says which queue a chat drains or what counts as waiting on Valentin. Each chat drains only its own view.

## The loop is Autopilot-full

The queue is your own view: `Hypertask board: <id>` in your agent notes, labelled from your chat name. Add it when missing.
The loop prompt:

```text
/pstack:poteto-mode full autopilot on this queue: every workable ticket in my view <view URL>. each item is independent. done when skills/board-drain/drain-check --board <id> --label <label> passes.
```

Two mappings: owners start through `~/.local/bin/plan-pick --run`, wrapped in `../hypertask-work/lease`, never as Claude chats; a ticket's column follows the `/hypertask` skill, references/board.md, never Valentin Review.

## Arm

Loops die silently: a session cron dies with the chat, a recurring one expires in 7 days. Arm at session start, after a restart or handover, when valentin-mode loads, and on any drain-check fail:

1. `./loop-state status --name "<your Multibot name>"`. Exit 0: already armed.
2. Otherwise, Claude Code: start `./watch --board <id> --label <label> --name "<name>"` as a tracked background Bash job, `run_in_background` with a 7200000 ms timeout. It polls your view every 3 minutes; its exit on a change is your next tick.
3. Arm a safety cron every 6 hours that runs the loop prompt if the watcher dies, recorded with: `./loop-state arm --name "<name>" --every 6h --job <job id> --board <id> --label <label>`.
4. Codex or a harness without tracked background jobs: keep the loop prompt on a 15-minute recurring job (`/loop 15m <prompt>`), recorded with `--every 15m`.
5. Every tick ends by starting a fresh watcher (step 2).

The 2h heartbeat wakes a silent chat twice a day.

Never delete the loop for an empty Todo; a tick with nothing new stays quiet.

## Each tick adds

1. **Sync.** `./sync --board <id> --label <label> --name "<name>"` runs the reconcile preview, then `--apply --limit 5`, as your own login (references/sync.md); read each reason. A usage error or non-zero exit prints `sync: FAIL`, which drain-check reports until a sync works.
2. **New tickets.** A workable ownerless Todo ticket gets an owner.
3. **Waits.** Read the newest comments on each waiting ticket first. Valentin's yes makes it workable: clear the mark, assign an owner.
4. **Check.** `./drain-check --board <id> --label <label> --state-name "<name>"`.
5. **Re-arm.** `loop-state status` exit 3 means expiry within a day: arm, record a fresh loop, delete the old.
6. **Daily.** `/hypertask checkup` once a day.

## What counts as waiting

Only a set waiting-on mark naming Valentin, or a blocker comment, counts; a chat's memory does not. An unmarked ticket is workable. Mark a real wait.

A ticket BlockedBy an open ticket stays outside the drain by its links, not by memory. drain-check reads `task relations` once per unmarked Todo ticket and prints `blocked: <KEY> by <KEY>, <KEY>`; that line is news, not a fail.

## drain-check fails

- **loop off:** workable Todo, nothing alive in Doing. Re-arm, then give the named ticket an owner.
- **unassigned:** a ticket in a working column with no agent. Assign your login: `task assign <KEY> --self`.
- **stalled:** a Doing ticket with no live owner. Replace it with a fresh plan-pick owner. A ticket moved in from another board gets a new key, so a worker started under the old key is invisible here: check that lease first.
- **stale:** a workable Todo ticket idle over two hours. Give it an owner; note the gap on your role ticket.
- **answered:** Valentin replied after the waiting-on mark. Clear the mark and work it.
- **not armed** or **watcher dead:** this chat restarted, the loop expired, or the watcher died. Arm it.
- **sync failed** or **sync stale:** the last sync broke or is over 45 minutes old. Fix it, then `./sync`.

A `vps-state` HOLD turns **loop off** and **stale** into one non-failing `held:` line; `--no-load` skips the probe.

A fail that returns is a gap here: file it on board 13556, label Board Drain Loop, with the output; repeated gaps become new checks.

## Rules

- Your login and your tickets only. Never move another chat's tickets.
- Never move a ticket into Valentin Review, or to Done without live proof.
- Reconcile bugs go to Hypertask Reconciler; PR follow-up follows the PR owner rules in valentin-mode.
