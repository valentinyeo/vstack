# Remote branches

## Sub-features

- Deleted on origin: a merged PR's head commit is the remote tip, or the tip is
  already in the base.
- Kept: the default branch, a branch with an open PR, a protected branch, a
  branch whose merged PR has a different tip (commits landed after the merge),
  and a branch whose PR closed unmerged.
- Reported only: branches with no PR at all. The count and the ten oldest names
  are printed, never deleted.

## How to get to it (user POV)

- Read the `DELETE remote`, `KEEP remote` and `STALE remote` lines. `STALE` means
  no PR exists, so no human ever said the work shipped.

## Driving it with run

- Action: `run`. Grade reads refs/heads in the bare origin, which is the only
  truth about what is still on the remote.

## Gotchas

- Protection is read from the fixture through the fake gh. If the shim call
  breaks, protection silently becomes an empty list and a protected branch gets
  pushed away. That is why the shim exits 2 on an unhandled call.
- A merge into main does not make the branch tip an ancestor when the merge was
  a squash or a rebase. Only the PR record covers those.
