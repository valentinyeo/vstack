---
name: repo-tidy
description: >-
  Remove git worktrees and branches whose work already shipped, across many repos at once, with gates that protect uncommitted, unpushed and in-use work. Use after a merge your session made, or when dead worktrees fill the disk.
---

# repo-tidy

Prior art: pstack `poteto-mode` was checked. Its `worktree-cleanup` playbook
cleans one repo interactively with user confirmation. The clean-up skill covers one session in hypertask
only. Neither is the multi-repo, gated, repeated apply, and neither reaches a
project's other folders. That gap is this skill.

Dry run by default. `--apply` removes.

## Run it on your own repo

1. After your session merges something: `"$HOME/.local/bin/repo-tidy" --apply --mine "$PWD" --branch "<your merged branch>"`. It removes
   only that branch and its worktree, never another chat's copies in the same repo.
2. Starting on a project: `"$HOME/.local/bin/repo-tidy" --apply --project "$PWD"`. It reads this
   project alone and clears what earlier chats left behind: the folder of every
   merged branch, and every old `repo-<ticket>` clone whose work shipped. No other
   project is touched.
3. Read only, any time: `"$HOME/.local/bin/repo-tidy" --all` prints each repo as it finishes.
   `--apply --all` is there when you mean it. Nothing runs it on a timer, and
   nobody sweeps other chats' repos for them. It runs at `nice` 10, four repos
   at once by default (`--jobs 1..8`), and one when `vps-state --can-launch
   worker` says HOLD or cannot answer, two when it says CAREFUL.

## Set up your own check

After each merge, run `"$HOME/.local/bin/repo-tidy" --apply --mine "<main checkout>" --branch "<your merged branch>"` from outside the finished worktree. On a new project, run `"$HOME/.local/bin/repo-tidy" --apply --project "<main checkout>"` once and read the holds. Keep every gate. Retry held items on your own next loop tick. PR housekeeping retains your observed PR as `cleanup` until its local refs are gone, even after a worker exits. No timer cleans other chats' work.

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

## A project's other folders

A chat's copy belongs to the project, not to the chat that left it, so
`--apply --project .` reads the project's own folders and no other's. A folder
counts as this project's when its git admin sits under this repo's
`.git/worktrees/`, or when its origin remote is this project's. Three kinds go
through the same four gates:

- A registered worktree, which git already lists.
- A worktree folder whose registration is gone: a copy of this repo's own admin.
  Git no longer knows it, so the normal worktree pass cannot reach it.
- A standalone clone in a sibling folder, the old `repo-<ticket>` copies. Its own
tip is what shipped or did not, judged against the base, the remote and the merged
PR list exactly as a worktree's is.

The main checkout is never a candidate, and a folder of another project is
skipped by remote. `--mine` never reaches any of these: another chat's live copy
is not this chat's cleanup.

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
"$HOME/.local/bin/repo-tidy" --apply --mine "$PWD" --branch my-branch # your merge only
"$HOME/.local/bin/repo-tidy" --apply --project .   # this project's folders only
"$HOME/.local/bin/repo-tidy" --quick               # local git only, one TIDY line per owed cleanup
"$HOME/.local/bin/repo-tidy" --apply --all        # every repo, when you mean it
"$HOME/.local/bin/repo-tidy" --all --json         # machine readable
```

`--quick` asks GitHub nothing, fetches nothing and writes no log, so a loop tick
can run it. It prints one `TIDY <path>` line per folder that already passes the
local gates, and `tidy: PASS` when there are none. `skills/board-drain/drain-check`
runs it, so a merge that kept its folder shows up as a finding without anyone
remembering it. What local git cannot see, such as a squash merge, waits for the
gated `--apply` run; `--quick` never removes anything.

## Proof

`.claude/skills/verify-vstack/tools/repo-tidy/run` builds a throwaway git world with every
state and grades a real apply run. `tests/test_repo_tidy.py` covers each gate,
the cap, a broken gh, a repo mid-rebase, the sibling folders, `--project`,
`--quick`, and an 800-worktree dry run under 60 seconds.
`tests/test_repo_tidy_hygiene.py` covers the disk pass: an idle worktree's output goes,
a recent one's and a live process's stay, a tracked file inside `dist/` is held, a
entries in /tmp for the project are cleaned while a recent one, another project's, a bare
name and a symlink stay, and a second run removes nothing.
