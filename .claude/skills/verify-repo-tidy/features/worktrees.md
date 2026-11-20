# Worktrees

The core of repo-tidy: a worktree goes only when its work shipped, it is clean,
nobody is using it, and its commit is not stranded.

## Sub-features

- `worktrees`: exactly the four shipped and idle sandbox worktrees are gone
  (`merged-clean`, `squash-clean`, `ignored-clean`, `closed-stale`). All ten
  others are still registered: wip edit, untracked scratch, unpushed commit,
  open PR, merged PR whose tip is not the worktree HEAD, closed PR three days
  old, a live process, a file touched now, a lease file, and a detached HEAD
  with a commit on no remote ref.
- `outside`: a worktree outside the projects root is reported, never removed.
- `main-worktree`: the main checkout is always still there.
- `commits`: every held commit is still reachable after the run, and every commit
  that existed at build time is still in the object database.

## How to get to it (user POV)

- Run repo-tidy in a repo. It lists one line per worktree, with REMOVE or HOLD
  and the reason. With `--apply` the REMOVE lines happen.

## Driving it with run

- Action: `run`. Result: `expect.json` names what must go and stay, `apply.json`
  holds what repo-tidy says it did, `after.json` holds what the repo looks like
  now. Grade compares the three.

## Gotchas

- The sandbox backdates worktree files. A freshly built world looks used to the
  2 hour gate, and every case would be held.
- `--apply --json` is the graded run. The human `dry.out` is kept for the
  transcript, not for grading.
- The in-use case needs a real process. `run` starts `sleep 900` with its cwd
  inside that worktree and kills it on exit.
