# Local branches

## Sub-features

- Deleted: branches whose tip is already in the base, whose tip a merged PR
  carries, and a local branch whose PR closed unmerged more than 30 days ago
  while its tip matches the remote.
- Kept: unpushed commits, open PRs, closed PRs under 30 days, and any branch a
  surviving worktree still has checked out.

## How to get to it (user POV)

- Look at the `DELETE branch` and `KEEP branch` lines. Each names its reason.
  The summary line counts them: `local branches deleted 8 kept 14`.

## Driving it with run

- Action: `run`. `after.json` lists refs/heads. Grade needs the eight deleted
  names gone and every kept name still present, `main` included.

## Gotchas

- A dry run cannot delete a branch that a worktree this run plans to remove still
  holds. repo-tidy counts that worktree as already gone, so the dry plan matches
  the apply run.
- Squash merges never make a branch an ancestor of the base. The merged PR's
  head commit is the only signal, so a broken gh holds every squash-merged
  branch.
