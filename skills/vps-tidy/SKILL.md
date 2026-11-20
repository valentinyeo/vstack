---
name: vps-tidy
description: >-
  Delete stale temp files, caches and docker leftovers, and stop stray programs on this shared VPS. Dry run by default. Use when vps-state says HOLD or CAREFUL for disk or memory, after your own work ends, or when disk is low.
---

# vps-tidy

Prior art: checked pstack poteto-mode/playbooks/worktree-cleanup.md (macOS simulators and caches only, nothing on a Linux host and no processes) and the old host cleaners named in docs/housekeeping-map.md.

Run it from any directory. It needs no board login, no timer and no shared instance. Any chat can run it, and two runs cannot overlap because one lock covers both.

## Run it

```sh
~/.local/bin/vps-tidy                    # dry run: the plan, nothing deleted
~/.local/bin/vps-tidy --apply            # do the plan
~/.local/bin/vps-tidy --only tmp,processes --apply
~/.local/bin/vps-tidy --json             # the same plan as data
```

Parts: tmp, evidence, caches, docker, tmux, processes. `--only files` means the first four (not tmux).

Every run prints one line per candidate with its rule and a keep reason, then the disk figure, what it removed, and what it would free. `--apply` deletes through a trash directory, rechecks inode, device and mtime first, sends `SIGTERM` and then `SIGKILL` after 10 seconds, and writes one JSON line per action to a run log under the state directory.

## When to run

1. When vps-state says HOLD or CAREFUL because of disk or memory, run it dry to see what is safe, then run it with `--apply`.
2. After your own work ends, so your scratch files, caches and stray dev servers do not outlive your ticket.
3. When disk free is under 80 GB, on your own loop, as below.

## Set up your own check

Nobody runs this for you, and a maintainer never runs it for another chat. Add it to your own loop or Stop hook, next to your vps-state check:

```sh
vps_state=$(~/.local/bin/vps-state --json)
free_gb=$(printf '%s' "$vps_state" | python3 -c 'import json,sys; print(json.load(sys.stdin)["facts"]["disk"]["free_gb"])')
if [ "${free_gb%%.*}" -lt 80 ]; then
  ~/.local/bin/vps-tidy --apply --only tmp,processes
fi
```

That keeps your own temp files and orphaned programs in check without a central timer. Add more parts (`evidence,caches,docker`) if your chat writes them.

## What it never touches

- gh-shared-cache and gh-shared-cache-app, whatever their age.
- Git worktrees, branches and `.git` directories. repo-tidy owns those, including node_modules inside a worktree.
- vcc-evidence as a cache: a video stays unless the board read succeeds and the ticket is not open.
- Another user's files or processes. Only your uid.
- claude, tmux, codex, pi and interactive shells, and any process tree holding one of them.
- Live chat tmux: `live-*`, `term-*`, `projects*`, `mp-*`, fleet roster names, attached sessions, and any server younger than 24 hours or with a busy pane.
- A symlink, a mount point, a foreign owner, a special file, or a path a process holds open.
- Anything under a config, ssh, claude or codex directory: those names are on its never-touch list.

It also never posts to a board. When disk is over 85% used it prints the alarm line, and a chat has to file the ticket.

## Read the report

- `remove` and `kill` are the plan. With `--apply` the result column says `removed`, `killed`, `kept` or `failed`.
- `keep` always names why: too fresh, wrong owner, wrong name, held open, protected, or the wrong rule.
- `budget reached` means the scan stopped on time. Run it again; the next run starts over and continues.
- `failed` above zero means a command or a removal did not work. Read the log line, it names the error.

## Faults

A Hypertask bug goes to hypertask feedback. A bug in this tool or its rules goes to a board 2060 ticket with label Poteto.
