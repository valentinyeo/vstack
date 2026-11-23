# Worktree and branch cleanup

`repo-tidy` removes exactly the worktrees and branches whose work already shipped, and leaves every other one alone.

## Sub-features

- `shipped` removes a merged, clean, idle worktree.
- `dirty` keeps uncommitted work.
- `unpushed` keeps local commits.
- `in-use` keeps a worktree a process holds.
- `branch` deletes the branch with its worktree.
- `mine` selects one named branch, including within a shared repo.
- `cleanup-follow-up` retains this chat's observed PR after merge, with a nonzero queue exit until its copies are gone.

## How to get to it (user POV)

- Run repo-tidy after your own merge, with `--mine "<main checkout>" --branch "<your merged branch>"`. Retry holds on your own loop; never scope a chat cleanup to all branches.
- Point it at one repo, or let it walk the repos you name.
- Read the survivors before trusting the run.

## Driving it with verify-vstack

Read `.claude/skills/verify-repo-tidy/SKILL.md` and run its `run` for the deletion gates. For branch scope, run `tests/test_repo_tidy.py`'s `TestMine`. For follow-up, run `tests/test_pr_queue.py`'s `CleanupLifecycleTests`. That journey observes an open PR, simulates its merge, checks the queue's nonzero exit and cleanup command, removes only its own branch, then checks exit 0. It also tests holds, another chat, a detached worktree, a reused branch, a worker's later push, separate chat and worker clones, and a failed GitHub read. All repos and state live in temporary directories.

Preconditions:

- It builds a throwaway git world with every state and grades the survivors, so no real repo is at risk.

## Gotchas

- Never kill by process name; tidy only what it can prove shipped.
- A branch whose patch landed under a different SHA still counts as shipped only when the check says so.
