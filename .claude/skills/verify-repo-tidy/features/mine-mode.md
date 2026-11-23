# Mine mode

## Sub-features

- `--mine SESSION_CWD --branch BRANCH` resolves that path's repo and selects only the named branch and its worktree.
- A path outside any git repo exits 0 without output.
- Every gate still applies. Mine mode skips no check.

## How to get to it (user POV)

- After your own merge: `repo-tidy --apply --mine "$PWD" --branch "<your merged branch>"`. Only your repo is read.

## Driving it with run

- Action: the sandbox builds a second repo, `other`, with one shipped worktree
  and no PR data. `run` does not use it; `tests/test_repo_tidy.py` drives mine
  mode against it and needs `other-done` still there and no `other:` line in the
  output.

## Gotchas

- A sibling worktree in the same repo also survives. `--mine` requires `--branch`; an unscoped old call fails before doing anything.
- The neighbour repo's origin is a local path, so it has no GitHub slug. That is
  on purpose: mine mode must not need gh at all to be safe.
- `--mine` prints no log-path line. It still saves the gate results.
