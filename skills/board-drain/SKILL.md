---
name: board-drain
description: "board drain;drain my board;drain loop;is my loop armed;work my view. /board-drain: a chat runs pstack Autopilot-full on its own Hypertask view as the queue, keeps it armed and checked until every ticket is done, waiting on Valentin, or blocked. Use at session start, after a restart or handover, when valentin-mode loads, or when drain-check fails."
---

# Board drain

Prior art: pstack poteto-mode Autopilot-full runs a queue: one owner per item from build to merge, a verifier that never wrote the code, an audit loop that replaces stuck agents by side effects. Autonomous-run needs a check that can pass or fail. vstack hypertask-work owns columns and the reconcile. None says which queue a chat drains, how the loop survives restarts or expiry, or what counts as waiting on Valentin. Only those gaps are here.

Each chat runs this on itself; nobody drains another chat's board. Paths resolve from this folder.

## The loop is Autopilot-full

The queue is your own view: `Hypertask board: <id>, label: <label>` from your agent notes. Add the line when missing.
The loop prompt, word for word:

```text
/pstack:poteto-mode full autopilot on this queue: every workable ticket in my view <view URL>. each item is independent. done when skills/board-drain/drain-check --board <id> --label <label> passes.
```

Autopilot-full does the work: owners, proof, verdicts, merges, stuck agents. Two house mappings apply: owners start through `~/.local/bin/plan-pick --run`, wrapped in `../hypertask-work/lease`, never as Claude chats; a ticket's column follows `hypertask-work`, never Valentin Review.

## Arm

Loops die silently: a session cron dies with the chat, a recurring cron expires after 7 days, and deleting it when Todo "looks done" kills it. Arm at session start, after a restart or handover, when valentin-mode loads, and on any drain-check fail:

1. `./loop-state status --name "<your Multibot name>"`. Exit 0: already armed.
2. Otherwise arm it every 15 minutes. Claude Code: `/loop 15m <prompt>`. Another harness: a recurring job it reports back on.
3. Record it: `./loop-state arm --name "<name>" --every 15m --job <job id>`.

Never delete it for an empty Todo; a tick with nothing new stays quiet.

## Each tick adds

On top of Autopilot-full's audit:

1. **Sync.** `./sync --board <id> --label <label> --name "<name>"` runs the reconcile preview, then `--apply --limit 5`, as your own login; read each reason. A usage error or non-zero exit prints `sync: FAIL`, reported by drain-check until a sync succeeds.
2. **New tickets.** A workable ownerless Todo ticket gets an owner.
3. **Waits.** Read the newest comments on each waiting ticket first. Valentin's yes makes it workable: clear the mark, give it an owner.
4. **Check.** `./drain-check --board <id> --label <label> --state-name "<name>"`.
5. **Re-arm.** `loop-state status` exit 3 means expiry within a day: arm a fresh loop, record it, delete the old.
6. **Daily.** `/hypertask-checkup` once a day.

## What counts as waiting

Only a set waiting-on mark naming Valentin, or a blocker comment, counts; a chat's memory that "this waits on Valentin" does not. An unmarked ticket is workable; drain-check treats it so. Mark a real wait the moment you ask him.

## drain-check fails

- **loop off:** workable Todo, nothing alive in Doing. Re-arm, then give the named ticket an owner.
- **unassigned:** a ticket in a working column (Doing, Building, Checks, AI Review, Verifier) with no agent. Assign your own agent login: `task assign <KEY> --self`.
- **stalled:** a Doing ticket with no live owner. Replace it with a fresh plan-pick owner. A ticket moved in from another board gets a new key nothing records, so a worker started under the old key is invisible here. Check the old key's lease by hand before you restart a worker.
- **stale:** a workable Todo ticket idle over two hours. Give it an owner; note the gap on your role ticket.
- **answered:** Valentin replied after the waiting-on mark. Clear the mark and work it.
- **not armed:** this chat restarted or the loop expired. Arm it.
- **sync failed** or **sync stale:** the last board sync broke or is over 45 minutes old. Fix it, then run `./sync`.

A fail that returns is a gap in this skill. File it on board 13556, label Board Drain Loop, with the drain-check output; that role turns repeated gaps into new checks here.

## Rules

- Your own login and your own tickets only. Never move another chat's tickets.
- Never move a ticket into Valentin Review, or to Done without live proof.
- Reconcile bugs go to Hypertask Reconciler; PR follow-up follows the PR owner rules in valentin-mode.
