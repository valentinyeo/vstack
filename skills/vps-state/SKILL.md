---
name: vps-state
description: >-
  Ask this shared VPS if it can take another chat, worker, build or test run right now, and see what this session can clean up. Use before starting any chat, worker, build or test run, and for housekeeping.
---

# vps-state

Prior art: checked pstack (`create-verification-skill`, `poteto-mode/playbooks/worktree-cleanup.md`); neither has a host-capacity skill. house-rules `fleet/runner` has a worker gate this mirrors.

Run `vps-state` from any directory. It reads /proc live on every call, never a cache, and answers in about a second.

## When to run

1. Before you start a chat, a worker, a build or a test run.
2. While you hold, every 10 minutes, to watch the numbers move.
3. When the machine feels slow, or you need disk back.

## How to read the verdict

Two answers, because different things bind them. Worker is bound by CPU, IO and memory. Chat is bound by memory first.

| Verdict | Obligation |
| --- | --- |
| ADD | Start it. The room line still caps how many. |
| CAREFUL | Start one, then run again before a second. |
| HOLD | Start nothing. |

The first line names the reason, for example `HOLD worker, CAREFUL chat: load5 30.24 is 1.68x 18 cores, cpu some60 26%`.

Flags: `--json` for every number, `--brief` for one line, `--can-launch chat|worker` for scripts and hooks (exit 0 ADD, 1 CAREFUL, 2 HOLD, 3 probe failure).

## What HOLD obliges

1. Start nothing new. Say you are holding, and why.
2. Finish, merge or close what you already have, and clean up your own scratch files.
3. Run vps-state again in 10 minutes.

## Housekeeping duty

The last section lists what this session may clean: its own worktrees whose branch is already in origin/main, its own /tmp entries older than two days, and the tools that sweep the host (the clean-up skill, `~/.local/bin/host-disk-sweep`, `~/.local/bin/tmp-cleanup`).

It reports, it never deletes. Clean only what this session made. Never touch another session's files, worktrees or /tmp entries.

## Reading the numbers

- `load5` per core above 1.0 means the queue is longer than the machine.
- cpu and io pressure are kernel averages of the share of time work waited.
- memory needs 24G free before another worker, and the room line leaves that reserve alone.
- disk above 90% used or under 80G free stops new builds.

If a line says unknown, that probe failed. Treat it as the worse verdict, never as ADD.
