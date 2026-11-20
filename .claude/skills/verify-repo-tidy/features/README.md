# repo-tidy verification map

The parts of repo-tidy this skill proves, one file each. Read this, then the
file for the feature.

## Baseline preconditions

- `python3` and `git` only. No network, no gh login, no board.
- The sandbox is built fresh each run, so a leftover from an earlier run cannot
  make a check pass.
- `verdict.txt` from an earlier run is not proof. Rerun after any code change.

## Driving conventions

- Only `run` drives. It builds, drives and grades in one call.
- The fake gh is a PATH shim. It answers reads from a fixture and logs writes.
  An unhandled call makes it exit 2, so a change in how repo-tidy calls gh fails
  loudly instead of silently deleting nothing.
- Worktree files are backdated three hours at build time. Only the `recent` case
  looks freshly touched. Without that, the 2 hour gate would hold everything.

## Proof and skip reporting

- Every check reads the git repo itself: worktree list, branch refs, remote refs
  in the bare origin, and `git rev-list --all`.
- A check that cannot read the world is FAIL, never PASS.
- A FAIL is a finding about repo-tidy. Fix the script, never the grade.

## Features

| File | Checks | What it proves |
| --- | --- | --- |
| [worktrees.md](worktrees.md) | `worktrees`, `outside`, `main-worktree`, `commits` | Shipped, clean and idle worktrees go; every other state stays, with its commits |
| [local-branches.md](local-branches.md) | `branches` | Merged branches go, unpushed and open-PR branches stay |
| [remote-branches.md](remote-branches.md) | `remote-branches` | Merged remote branches go, protected, open-PR and stale ones stay |
| [github-setting.md](github-setting.md) | `github-setting` | The merge setting is written once, only for our owners |
| [mine-mode.md](mine-mode.md) | `mine` | `--mine` reads one repo and leaves the neighbour alone |
| [cap.md](cap.md) | `cap` | `--max-remove` caps a run and the rest is reported deferred |
