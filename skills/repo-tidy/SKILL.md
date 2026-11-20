---
name: repo-tidy
description: >-
  Remove git worktrees and branches whose work already shipped, across many repos at once, with gates that protect uncommitted, unpushed and in-use work. Use after a merge your session made, for the daily VPS sweep, or when dead worktrees fill the disk.
---

# repo-tidy

Prior art: pstack's worktree-cleanup playbook and its worktree-audit.sh are
read-only audits for one repo. The clean-up skill covers one session in
hypertask only. This adds the multi-repo, gated, ongoing apply.

Dry run by default. `--apply` removes.

## When to run

1. After a merge your session made: `repo-tidy --apply --mine $PWD`. It reads
   only the one repo you are in. The Stop hook does this for you.
2. VPS Admin, daily: `repo-tidy --apply --all`. Every repo under the projects
   root, plus the two shared checkouts.
3. Any time, read only: `repo-tidy --all` prints the plan.

Every session cleans its own repo after it ships. Nobody waits for the daily
sweep to tidy the worktree they just finished with.

## The gates

An item goes only when all four hold. One miss means it stays and gets a line.

- Shipped. Its tip is already in the base branch, or a merged PR carries exactly
  that commit (squash merges), or its PR closed unmerged more than 14 days ago
  and the commit is on the remote.
- Clean. No tracked edit. Untracked files block it unless every one is
  gitignored build output.
- Not in use. No process has its cwd or an open file under it, no tmux pane
  sits in it, no file in it was touched in the last 2 hours, and no lease file
  in the local state directory names it.
- Restorable. A detached HEAD whose commit is on no remote ref stays.

Branches follow the same rule. A local branch survives while a worktree still
has it checked out, while it holds commits on no remote ref, or while its PR is
open. Remote branches go only when a merged PR's head commit is the remote tip,
or the tip is already in the base. Protected branches and the default branch are
never pushed away.

A repo mid-rebase or mid-merge is skipped whole. Nothing in the vcc evidence
directory is touched. Nothing outside a registered worktree under the projects
root is deleted, so worktrees elsewhere are reported, not removed.

`--max-remove N` (default 200) caps one repo per run. The cap is what keeps a
bug from emptying a repo, so leave it on.

## Reading the output

One summary line per repo, then one line per item: REMOVE, HOLD, DELETE, KEEP,
STALE, SET, SKIP, DEFER. Each names its reason. Nothing is deleted for a reason
you cannot read.

```
hypertask: worktrees would-remove 12 held 3 (wip 1, in-use 1, unshipped 1) | local branches deleted 40 kept 22 | remote deleted 9 stale-unPR'd 14 | freed ~2.1 GB
```

`--json` prints full detail, and every run writes it to the local state
directory under repo-tidy.

## Commands

```
repo-tidy                      # dry run, this repo
repo-tidy --all                # dry run, every repo
repo-tidy --apply --mine $PWD  # this repo, after your merge
repo-tidy --apply --all        # the daily sweep
repo-tidy --all --json         # machine readable
```

## Proof

`.claude/skills/verify-repo-tidy/run` builds a throwaway git world with every
state and grades a real apply run. `tests/test_repo_tidy.py` covers each gate,
the cap, a broken gh, a repo mid-rebase, and an 800-worktree dry run under 60
seconds.
