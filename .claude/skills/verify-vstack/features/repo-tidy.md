# Worktree and branch cleanup

`repo-tidy` removes exactly the worktrees and branches whose work already shipped, and leaves every other one alone.

## Sub-features

- `shipped` removes a merged, clean, idle worktree.
- `dirty` keeps uncommitted work.
- `unpushed` keeps local commits.
- `in-use` keeps a worktree a process holds.
- `branch` deletes the branch with its worktree.

## How to get to it (user POV)

- Run repo-tidy after a merge your own session made.
- Point it at one repo, or let it walk the repos you name.
- Read the survivors before trusting the run.

## Driving it with verify-vstack

This feature is proved by its own skill. Read `.claude/skills/verify-repo-tidy/SKILL.md` and run its `run`.

Preconditions:

- It builds a throwaway git world with every state and grades the survivors, so no real repo is at risk.

## Gotchas

- Never kill by process name; tidy only what it can prove shipped.
- A branch whose patch landed under a different SHA still counts as shipped only when the check says so.
