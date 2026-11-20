---
name: board-drain
description: "board drain;drain my board;drain loop;is my loop armed;work my view. /board-drain: a chat runs pstack Autopilot-full on its own Hypertask view as the queue, and keeps that loop armed and checked until every ticket is done, waiting on Valentin, or blocked. Use at session start, after a restart or handover, when valentin-mode loads, or when drain-check fails."
---

# Board drain

Prior art: pstack poteto-mode Autopilot-full runs a queue: one owner per item from build to merge, a verifier that never wrote the code, and an audit loop that judges agents by side effects and replaces stuck ones. Autonomous-run says a loop needs a check that can pass or fail. vstack hypertask-work owns columns and the reconcile. None of them says which queue a chat drains, how its loop survives a restart or expiry, or what counts as waiting on Valentin. Only those gaps are here.

Each chat runs this on itself. Nobody drains another chat's board.
Paths resolve from this folder.

## The loop is Autopilot-full

The queue is your own view: `Hypertask board: <id>, label: <label>` from your agent notes. Add the line when it is missing.
The loop prompt, word for word:

```text
/pstack:poteto-mode full autopilot on this queue: every workable ticket in my view <view URL>. each item is independent. done when skills/board-drain/drain-check --board <id> --label <label> passes.
```

Autopilot-full does the work: owners, proof, verdicts, merges, stuck agents. Two house mappings apply. Owners start through `~/.local/bin/plan-pick --run`, wrapped in `../hypertask-work/lease`, never as Claude chats. A ticket's column follows `hypertask-work`, never Valentin Review.

## Arm

Loops die silently. A session cron dies with the chat, and a recurring cron expires after 7 days. Deleting it because Todo "looks done" kills it too. Arm at session start, after a restart or handover, when valentin-mode loads, and on every drain-check fail:

1. `./loop-state status --name "<your Multibot name>"`. Exit 0: already armed.
2. Otherwise arm the loop prompt every 15 minutes. Claude Code: `/loop 15m <prompt>`. Codex or another harness: a recurring job the harness reports back on.
3. Record it: `./loop-state arm --name "<name>" --every 15m --job <job id> --board <id> --label <label>`.

Never delete the loop because Todo looks empty. A tick with nothing new stays quiet, per Autopilot-full.

## Each tick adds

On top of Autopilot-full's audit:

1. **Sync.** `./sync --board <id> --label <label> --name "<name>"` runs the reconcile preview, then `--apply --limit 5`, as your own login. Read each reason. A usage error or non-zero exit prints `sync: FAIL`, and drain-check reports it until a sync succeeds.
2. **New tickets join the queue.** A workable Todo ticket with no owner gets one.
3. **Waits.** Read the newest comments on each waiting ticket first. Valentin's yes makes it workable: clear the mark and give it an owner.
4. **Check.** `./drain-check --board <id> --label <label> --state-name "<name>"`.
5. **Re-arm.** `loop-state status` exit 3 means expiry within a day: arm a fresh loop, record it, then delete the old one.
6. **Daily.** `/hypertask-checkup` once a day.

## What counts as waiting

Only a set waiting-on mark naming Valentin, or a blocker comment, counts. A chat's memory that "this waits on Valentin" does not. An unmarked ticket is workable, and drain-check treats it so. Mark a real wait the moment you ask him.

## drain-check fails

Each line names its fix:

- **loop off:** workable Todo, nothing alive in Doing. Re-arm, then give the named ticket an owner.
- **stalled:** a Doing ticket with no live owner. Replace it with a fresh plan-pick owner.
- **stale:** a workable ticket idle in Todo over two hours. Give it an owner, and note the gap on your role ticket.
- **answered:** Valentin replied after the waiting-on mark. Clear the mark and work it.
- **not armed:** this chat restarted or the loop expired. Arm it.
- **sync failed** or **sync stale:** the last board sync broke or is over 45 minutes old. Fix the named cause, then run `./sync`.

A fail that returns on the next tick is a gap in this skill. File it on board 13556, label Board Drain Loop, with the drain-check output. That role turns repeated gaps into new checks here.

## Rules

- Your own login and your own tickets only. Never move another chat's tickets.
- Never move a ticket into Valentin Review, and never to Done without live proof.
- Reconcile bugs go to Hypertask Reconciler. PR follow-up stays with the PR owner rules in valentin-mode.
