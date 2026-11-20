# Cap

## Sub-features

- `--max-remove N` is one deletion budget per repo per run. It covers worktree
  removals, local branch deletions and remote branch deletions, in that order.
- Everything over the cap is not deleted. Each item prints DEFER, and the
  summary prints a DEFERRED count.

## How to get to it (user POV)

- Leave the default 200 on. A bug that puts every worktree in the remove bucket
  then costs 200 worktrees, not a whole repo.

## Driving it with run

- Action: `tests/test_repo_tidy.py` runs `--apply --max-remove 1` on a fresh
  sandbox and needs exactly one worktree gone plus a DEFERRED line. `run` uses
  the default cap, so its verdict covers the uncapped path.

## Gotchas

- The budget is shared, so a big worktree count can defer every branch deletion
  in that repo. The next run picks them up. That is the point of a cap.
- A dry run applies the same cap, so the plan you read is the plan that applies.
