---
name: pr-housekeeping
description: >-
  Each loop tick, list this chat's own open PRs and drive them with pstack Babysit or Autopilot-full. Use at /pr-housekeeping or when a chat owns open PRs.
---

# PR housekeeping

Prior art: pstack `poteto-mode` **Babysit** and **Autopilot-full** drive conflicts, threads, CI and merge prep; the older `hypertask-triage` `pr-queue` reads from the board. This skill only adds per-chat listing via `Owner chat:` in the PR body.

Whoever opens a PR carries it to merge or closes it with a reason. Never open a second PR for one ticket.

Each tick: run `pr-queue --mine "<your live chat name>"`, then Babysit in **drive** mode on each row, or **Autopilot-full** when several need owners in parallel.

## Set up your own check

Once per chat, add this to your loop or loop playbook:

```sh
~/.claude/skills/pr-housekeeping/pr-queue --mine "<your live chat name>"
```

A nonzero exit means one of your PRs is stale: finish it, close it with a reason, or note why it waits on the ticket before new work.

Proof: `tests/test_pr_queue.py` (fixtures only). Gaps go to board 13556, label PR Housekeeping.