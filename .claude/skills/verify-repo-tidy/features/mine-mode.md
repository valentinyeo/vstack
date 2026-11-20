# Mine mode

## Sub-features

- `--mine SESSION_CWD` resolves the repo that holds that path, including when
  the path is inside one of its worktrees, and reads only that repo.
- A path outside any git repo makes the command exit 0 and print nothing. That
  is what the Stop hook relies on.
- Every gate still applies. Mine mode scopes the repo, it does not skip a check.

## How to get to it (user POV)

- After your own merge: `repo-tidy --apply --mine $PWD`. Only your repo is read.

## Driving it with run

- Action: the sandbox builds a second repo, `other`, with one shipped worktree
  and no PR data. `run` does not use it; `tests/test_repo_tidy.py` drives mine
  mode against it and needs `other-done` still there and no `other:` line in the
  output.

## Gotchas

- The neighbour repo's origin is a local path, so it has no GitHub slug. That is
  on purpose: mine mode must not need gh at all to be safe.
- `--mine` prints no log line, because the hook redirects it to a file.
