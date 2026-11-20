# GitHub setting

## Sub-features

- When `delete_branch_on_merge` is false and the owner is valentinyeo or
  hypertask-ai, the apply run patches it to true. On a dry run it prints SET.
- Any other owner is left alone, and so is a setting that is already true.

## How to get to it (user POV)

- The summary prints SET with the owner/repo. The next merge on that repo
  deletes its head branch by itself, so repos stop accumulating dead branches.

## Driving it with run

- Action: `run`. The fake gh appends every write to gh-calls.log. Grade needs
  exactly one line: `PATCH repos/valentinyeo/sandbox delete_branch_on_merge=true`.

## Gotchas

- The sandbox owner must be one repo-tidy is allowed to change. It is
  valentinyeo/sandbox, not sandbox/origin, or the gate correctly skips the write.
- A broken gh must produce no write at all. Grade fails if it sees one.
