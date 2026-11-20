# Housekeeping

The report of what this session may clean, and the tools that sweep the host.

## Sub-features

- `cleanup`: the human block carries the section, names the clean-up skill, `~/.local/bin/host-disk-sweep` and `~/.local/bin/tmp-cleanup`, and states the rule: clean only what this session made, never another session's files.
- Merged worktrees: `git worktree list --porcelain` and `git branch --merged origin/main`, five second budget, no network and no `gh` call.
- /tmp: this user's top-level entries older than two days, with a count, a total and three names, read inside a five second budget.

## How to get to it (user POV)

- Run `vps-state` and read the last section. It never deletes anything.
- Then run the tool for what it listed, from the session that owns those files.

## Driving it with run

- Action: `run`. The full block is saved as `human.out`.
- Check: `cleanup` needs both the heading and the rule line in that saved block. A missing section fails, because it is the part a session reads when it must hold.
- `--no-cleanup` skips the scans and still prints the rules, so the duty survives a fast path.

## Gotchas

- The /tmp total adds top-level entry sizes only, never the contents of a directory. A big directory can show as 0M, so treat the count as the fact and the size as a hint.
- Under load the git scan can hit its five second budget and print unknown. That is a correct answer, not a failure.
- Worktrees whose PR was closed but not merged are not listed. Nothing here calls GitHub, so closing a PR is not evidence you can delete the branch.
- The section is a report. Deleting another session's worktree breaks its uncommitted work, and no check here can warn you in time.
