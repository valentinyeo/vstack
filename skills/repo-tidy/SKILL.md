---
name: repo-tidy
description: >-
  Remove git worktrees and branches whose work already shipped, across many repos at once, with gates that protect uncommitted, unpushed and in-use work. Use after a merge your session made, or when dead worktrees fill the disk.
---

# repo-tidy

Prior art: pstack `poteto-mode` was checked. Its worktree-cleanup playbook is a
read-only audit for one repo. The clean-up skill covers one session in hypertask
only. Neither is the multi-repo, gated, repeated apply. That gap is this skill.

Dry run by default. `--apply` removes.

## Run it on your own repo

1. After your session merges something: `"$HOME/.local/bin/repo-tidy" --apply --mine $PWD`. It reads
   only the one repo you are in.
2. Read only, any time: `"$HOME/.local/bin/repo-tidy" --all` prints each repo as it finishes.
   `--apply --all` is there when you mean it. Nothing runs it on a timer, and
   nobody sweeps other chats' repos for them. It runs at `nice` 10, four repos
   at once by default (`--jobs 1..8`), and one when `vps-state --can-launch
   worker` says HOLD or cannot answer, two when it says CAREFUL.

## Set up your own check

Nobody registers this for you. Pick either or both.

1. In your own loop, after each merge, run `"$HOME/.local/bin/repo-tidy" --apply --mine "$PWD"`.
2. Add the Stop hook to your own project's .claude/settings.local.json. It tidies
   that repo when a turn ends, at most once per 30 minutes per repo:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.local/share/vstack/hooks/repo-tidy-stop"
          }
        ]
      }
    ]
  }
}
```

The hook is `hooks/repo-tidy-stop`, and it finds the script beside itself, so the
checkout path above works with no install step. A shared install also links it
at ~/.claude/hooks/repo-tidy-stop, which is the older path settings call. Never
run this repo's ./install for it: that repoints shared skills for every chat on
this host.

## The gates

An item goes only when all four hold. One miss means it stays and gets a line.

- Shipped. Its tip is already in the base branch, or a merged PR carries exactly
  that commit (squash merges), or its PR closed unmerged more than 14 days ago
  and the commit is on the remote.
- Clean. No tracked edit. Untracked files block it unless every one is
  gitignored build output.
- Not in use. No process has its cwd or an open file under it, no tmux pane
  sits in it, no file in it was touched in the last 2 hours, and no lease file
  in the local state directory names it.
- Restorable. A detached HEAD whose commit is on no remote ref stays.

Branches follow the same rule. A local branch survives while a worktree still
has it checked out, while it holds commits on no remote ref, or while its PR is
open. Remote branches go only when a merged PR's head commit is the remote tip,
or the tip is already in the base. Protected branches and the default branch are
never pushed away.

A repo mid-rebase or mid-merge is skipped whole. Nothing in the vcc evidence
directory is touched. Nothing outside a registered worktree under the projects
root is deleted, so worktrees elsewhere are reported, not removed.

`--max-remove N` (default 200) caps one repo per run. The cap is what keeps a
bug from emptying a repo, so leave it on.

## Reading the output

One summary line per repo, then one line per item: REMOVE, HOLD, DELETE, KEEP,
STALE, SET, SKIP, DEFER. Each names its reason. Nothing is deleted for a reason
you cannot read.

```
hypertask: worktrees would-remove 12 held 3 (wip 1, in-use 1, unshipped 1) | local branches deleted 40 kept 22 | remote deleted 9 stale-unPR'd 14 | freed ~2.1 GB
```

`--json` prints full detail, and every run writes it to the local state
directory under repo-tidy.

## Commands

```
"$HOME/.local/bin/repo-tidy"                      # dry run, this repo
"$HOME/.local/bin/repo-tidy" --all                # dry run, every repo
"$HOME/.local/bin/repo-tidy" --apply --mine $PWD  # this repo, after your merge
"$HOME/.local/bin/repo-tidy" --apply --all        # every repo, when you mean it
"$HOME/.local/bin/repo-tidy" --all --json         # machine readable
```

## Proof

`.claude/skills/verify-repo-tidy/run` builds a throwaway git world with every
state and grades a real apply run. `tests/test_repo_tidy.py` covers each gate,
the cap, a broken gh, a repo mid-rebase, and an 800-worktree dry run under 60
seconds.
