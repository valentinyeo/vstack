# repo-tidy cleans exactly the shipped work

`skills/repo-tidy/repo-tidy` removes exactly the worktrees and branches whose work shipped, and nothing else. There is no live service to drive: the app is a git repo on disk, so the sandbox is the app and every gate gets its own worktree in it. The proof bar is one apply run on a world holding a worktree in every state.

## Sub-features

- `worktrees`: exactly the four shipped and idle sandbox worktrees go (`merged-clean`, `squash-clean`, `ignored-clean`, `closed-stale`). Ten others stay: wip edit, untracked scratch, unpushed commit, open PR, merged PR whose tip is not the worktree HEAD, closed PR three days old, a live process, a file touched now, a lease file, and a detached HEAD whose commit is on no remote ref.
- `outside`: a worktree outside the projects root is reported, never removed.
- `main-worktree`: the main checkout is always still there.
- `commits`: every held commit is still reachable after the run, and every commit that existed at build time is still in the object database.
- `branches`: local branches go when their tip is in the base or a merged PR carries it, or when their PR closed unmerged more than 30 days ago with the tip matching the remote. Unpushed commits, open PRs, closed PRs under 30 days and branches a surviving worktree still holds stay.
- `remote-branches`: a merged PR's head commit or a tip already in the base is deleted on origin. The default branch, open-PR, protected, different-tip and closed-unmerged branches stay. Branches with no PR are reported as `STALE` with a count and the ten oldest names, never deleted.
- `github-setting`: when `delete_branch_on_merge` is false and the owner is valentinyeo or hypertask-ai, the apply run patches it to true; a dry run prints `SET`. Any other owner, or a setting already true, is left alone.
- `mine`: `--mine SESSION_CWD --branch BRANCH` resolves that path's repo and selects only the named branch and its worktree, including within a shared repo. A path outside any git repo exits 0 without output. Every gate still applies. A missing named worktree loses only its own registration through normal `git worktree remove`, with no shared prune or force, and locked registrations stay.
- `cleanup-follow-up`: this chat's observed PR stays visible after merge, with a nonzero queue exit until its copies are gone.
- `cap`: `--max-remove N` is one deletion budget per repo per run, covering worktree, then local branch, then remote branch deletions. Everything over it prints `DEFER` and the summary prints a `DEFERRED` count.

## How to get to it (user POV)

- Run repo-tidy in a repo. It prints one line per worktree with `REMOVE` or `HOLD` and the reason, then `DELETE branch`, `KEEP branch`, `DELETE remote`, `KEEP remote` and `STALE remote` lines with reasons, then a summary such as `local branches deleted 8 kept 14`.
- Run repo-tidy after your own merge, with `--mine "<main checkout>" --branch "<your merged branch>"`. Only your repo is read, and a held item is retried on your own loop, never by scoping a chat cleanup to all branches.
- The summary's `SET`/`PATCH` line means the next merge on that repo deletes its head branch by itself.

## Driving it with verify-vstack


Preconditions:

- `python3` and `git` only. No network, no gh login, no board. One run takes about ten seconds.
- The world is built fresh each run, so a leftover from an earlier run cannot make a check pass. A `verdict.txt` from an earlier run is not proof.

- **Doctor first.** `run` needs `skills/repo-tidy/repo-tidy` executable, `python3` and `git` on `PATH`, the sandbox builder present, and git working from the temp directory. It exits 3 before building anything when one fails.
- **Real run.** Run `.claude/skills/verify-vstack/tools/repo-tidy/run`. It builds a bare origin, one clone, fifteen worktrees, a fake gh serving fixture PR data and a live `sleep` process sitting in one worktree, then a dry run into `dry.out`, a snapshot into `before.json`, the apply run into `apply.json`, and grades.
- **The fake gh.** It is a `PATH` shim, so the real code path runs: it answers PR and setting reads from a fixture and appends every write to a call log. An unhandled call exits 2, so a change in how repo-tidy calls gh fails loudly instead of silently deleting nothing. `github-setting` needs exactly one line, `PATCH repos/valentinyeo/sandbox delete_branch_on_merge=true`.
- **Mine mode and the cap** are driven by `tests/test_repo_tidy.py`: it drives `--mine` against the neighbour repo `other` (needs `other-done` still there and no `other:` line in the output) and `--apply --max-remove 1` on a fresh sandbox (needs exactly one worktree gone plus a `DEFERRED` line). `run` uses the default cap, so its verdict covers the uncapped path.
- **Evidence.** Every run keeps `~/.local/state/verify-repo-tidy/<run-id>/`: `meta.json`, `doctor.txt`, `expect.json`, `dry.out`, `dry.err`, `before.json`, `apply.json`, `apply.err`, `after.json`, `verdict.txt` and `verdict.json`. Grading reads the repo itself: worktree list, branch refs, remote refs in the bare origin, and `git rev-list --all`.
- **Cleanup.** `run` removes its sandbox and kills the `sleep` it started, never the evidence. `--keep-sandbox` keeps the world for poking at, and `--root /tmp/rt` chooses where it goes.

## Gotchas

- The sandbox backdates worktree files three hours, and only the `recent` case looks freshly touched. Without that the 2 hour gate would hold everything.
- `--apply --json` is the graded run. The human `dry.out` is kept for the transcript, not for grading.
- The in-use case needs a real process: `run` starts `sleep 900` with its cwd inside that worktree and kills it on exit.
- A dry run cannot delete a branch that a worktree this run plans to remove still holds. repo-tidy counts that worktree as already gone, so the dry plan matches the apply run.
- Squash merges never make a branch an ancestor of the base, so the merged PR's head commit is the only signal. A broken gh holds every squash-merged branch.
- Protection is read from the fixture through the fake gh. If the shim call breaks, protection silently becomes an empty list and a protected branch gets pushed away.
- The sandbox owner must be one repo-tidy may change: it is `valentinyeo/sandbox`, not `sandbox/origin`, or the gate correctly skips the write.
- The neighbour repo's origin is a local path with no GitHub slug, on purpose: mine mode must not need gh at all to be safe. `--mine` prints no log line because the hook redirects it to a file.
- The cap is shared, so a big worktree count can defer every branch deletion in that repo. The next run picks them up. That is the point of a cap.
- A check that cannot read the world is FAIL, never PASS, and a FAIL is a finding about repo-tidy: fix the script, never the grade.
