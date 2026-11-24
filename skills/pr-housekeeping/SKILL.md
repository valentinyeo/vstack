---
name: pr-housekeeping
description: >-
  Each loop tick, list this chat's own open PRs and drive them with pstack Babysit or Autopilot-full. Use at /pr-housekeeping or when a chat owns open PRs.
---

# PR housekeeping

Prior art: pstack `poteto-mode` Babysit and Autopilot-full own PR follow-up. This adds per-chat listing through `Owner chat:` in the body.

Follow pstack Babysit for the requested scope. Opening a PR alone does not start a babysit or authorize a merge. Under an Autopilot-full grant, one owner carries each PR through that playbook.

## Set up your own check

Add this to your loop:

```sh
~/.claude/skills/pr-housekeeping/pr-queue --mine "<your live chat name>"
```

Each tick, use Babysit in **drive** mode, or **Autopilot-full** for several rows. Nonzero means stale or cleanup pending. Resolve it or record the wait before new work.

Run before handing a worker its merge. The queue retains your observed PRs until local copies disappear. Run its named-branch repo-tidy command outside the worktree. Keep every hold; retry next tick. Changed tips or detached worktrees need ownership checks, not deletion.

Records cover matching current, projects and shared clones. Keep your loop alive after workers exit. Unobserved old merges need an explicit audit. No central cleanup runs.

Proof: `tests/test_pr_queue.py`. Gaps go to board 13556, label PR Housekeeping.
