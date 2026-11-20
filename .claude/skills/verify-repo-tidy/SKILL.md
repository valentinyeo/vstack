---
name: verify-repo-tidy
description: >-
  Prove that skills/repo-tidy/repo-tidy removes exactly the shipped, clean and idle worktrees and branches, and nothing else. Builds a throwaway git world with every state, drives a real apply run, and grades the survivors. Use after any change to repo-tidy, as proof on such a PR, and when a repo looks like it was cleaned wrong.
---

# Verify repo-tidy

Prior art: pstack create-verification-skill and this repo's verify-reconcile.
This one has no live service to drive. Its app is a git repo on disk, so the
sandbox is the app, and every gate gets its own worktree in it.

The proof bar: one apply run on a world holding a worktree in every state. The
four shipped and idle ones go. Every other one stays, with its branch and its
commits, and the GitHub setting is written once.

Read `features/README.md` for the map.

## Launch

```sh
.claude/skills/verify-repo-tidy/run
.claude/skills/verify-repo-tidy/run --keep-sandbox --root /tmp/rt
```

`run` builds everything itself. Nothing to install, no network, no gh login and
no board. It takes about ten seconds.

## Doctor

doctor.txt holds one line per check:

- `skills/repo-tidy/repo-tidy` exists and is executable;
- `python3` and `git` are on PATH;
- the sandbox builder is present;
- git can work from the temp directory.

Exit 3 when a check fails, before anything is built.

## Drive

Only `run` drives. In order:

1. Makes the evidence directory and its meta.json.
2. Builds the world from the sandbox builder: a bare origin, one clone, fifteen
   worktrees, a fake gh serving fixture PR data, and a live `sleep` process
   sitting in one of them.
3. Dry run into dry.out, then a snapshot into before.json.
4. Apply run into apply.json.
5. Grades, prints the verdict, exits with its code.

The fake gh is a PATH shim, so the real code path runs. It answers the PR and
setting reads from a fixture file and appends every write to a call log.

## Evidence

Every run keeps the local state directory under verify-repo-tidy:

| File | What it proves |
| --- | --- |
| meta.json | sandbox path, script and git sha |
| doctor.txt | the sandbox was worth building |
| expect.json | what the builder says must go and must stay |
| dry.out, dry.err | the plan, and the human summary line |
| before.json | the world after the dry run, unchanged |
| apply.json, apply.err | what the apply run did, as JSON |
| after.json | the world after the apply run |
| verdict.txt, verdict.json | one PASS/FAIL line per check, then the verdict |

Grading reads the repo, not repo-tidy's claims. It lists worktrees, branches and
remote refs again, checks every held commit is still reachable, and checks the
fake gh saw exactly one setting write. On a PR, attach verdict.txt.

## Cleanup

`run` removes its sandbox and kills the `sleep` it started. Evidence stays. Use
`--keep-sandbox` when you want to poke at the world yourself, then delete the
directory it names.

## When it runs

Every change to `skills/repo-tidy/` runs it, with the verdict on the PR.
`tests/test_repo_tidy.py` runs the same builder in CI on every path.
