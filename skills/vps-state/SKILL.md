---
name: vps-state
description: >-
  Ask this shared VPS if it can take another chat, worker, build or test run right now, and see what this session can clean up. Use before starting any chat, worker, build or test run, and for housekeeping.
---

# vps-state

Prior art: checked pstack (`create-verification-skill`, `poteto-mode/playbooks/worktree-cleanup.md`); neither has a host-capacity skill. house-rules fleet/runner has a worker gate this mirrors.

Run `"$HOME/.local/bin/vps-state"` from any directory. It reads /proc live on every call, never a cache, and answers in about a second. Name it by full path: a Claude Code Bash shell's PATH carries no ~/.local/bin, so a bare command name exits 127 there.

## Set up your own check

No central enforcer runs this for you. Set up your own check, once, for your own chat.

1. In your own loop or launcher, run `"$HOME/.local/bin/vps-state" --can-launch worker` before you start a worker, or `--can-launch chat` before a chat. Exit 0 means start. Exit 1 means start one and ask again before a second. Exit 2 means hold. Further rules are in [What HOLD obliges](#what-hold-obliges).
2. Optional: have the answer print as your session opens. Add this to your own project's `.claude/settings.json`. `install` puts the hook file at that path. It does not register it for you.

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "\"$HOME/.local/share/vstack/hooks/run-hook\" \"$HOME/.claude/hooks/vps-state-hook\"" } ] }
    ]
  }
}
```

If that file already has a `SessionStart` list, add this entry to the list. `run-hook` warns and exits 0 for a missing or non-executable script, so the session still opens.

## When to run

1. Before you start a chat, a worker, a build or a test run.
2. While you hold, every 10 minutes, to watch the numbers move.
3. When the machine feels slow, or you need disk back.
4. When your launcher reports HOLD and you want to see why.

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
3. Run `"$HOME/.local/bin/vps-state"` again in 10 minutes.

## Housekeeping duty

The last section lists what this session may clean: its own worktrees whose branch is already in origin/main, its own /tmp entries older than two days, and the clean-up skill for the rest.

It reports, it never deletes. Clean only what this session made. Never touch another session's files, worktrees or /tmp entries.

## Reading the numbers

- `load5` per core above 1.0 means the queue is longer than the machine.
- cpu and io pressure are kernel averages of the share of time work waited.
- memory needs 24G free before another worker, and the room line leaves that reserve alone.
- disk at 85% used or more stops ADD (it answers CAREFUL, never HOLD): a worker still starts, and the line names `repo-tidy --prune-caches --project .` then `vps-tidy --apply`, the two commands that hand the space back. Under 80G free also stops new builds. On a small disk both free-GB floors shrink with it: ADD needs more than 20% of the disk free, HOLD below 7.5%, and a 400G or larger disk keeps the 80G and 30G numbers.

If a line says unknown, that probe failed. Answer CAREFUL at best, never ADD.
