---
name: verify-reconcile
description: >-
  Prove that skills/hypertask-work/reconcile still reads a real board and plans the right moves. Drives the script on board 15 or 2060, saves what it printed, and grades it PASS or FAIL per check: finished, bus, unknown, github calls, live card columns, and with --apply, settled and converged. Use after any change to skills/hypertask-work/reconcile, as proof on such a PR, and whenever a chat suspects a board drifted.
---

# Verify reconcile

Prior art: checked pstack (create-verification-skill), this repo's `verify-valentin-mode` and `hypertask-work`. `verify-valentin-mode` proves a fresh chat uses reconcile; this proves reconcile itself reads a board right. It is the `verify-<app>` skill create-verification-skill asks for, with the board sync script as the app.

The proof bar: run `--apply`, then a second dry run plans no moves. A dry run alone shows what reconcile would do, not that it did it.

Read `features/README.md` for the map.

## Launch

```sh
.claude/skills/verify-reconcile/run --board 15 --cases .claude/skills/verify-reconcile/cases/board15.json
.claude/skills/verify-reconcile/run --board 15 --apply --limit 5   # needs the board 15 login
```

`run` does, in order:

1. Makes `~/.local/state/verify-reconcile/<run-id>/` and writes its meta.json.
2. Runs the doctor. Exit 3 when it fails.
3. Sets the user session bus, unless `--keep-bus`.
4. Dry run into dry1.out and dry1.err.
5. With `--apply`: the apply run, then a second dry run.
6. Scrubs tokens, grades, prints the verdict, exits with its code.

Flags: `--board` (default 15), `--label`, `--script` (default this checkout's copy, so a PR branch can be verified), `--apply` (off by default), `--limit` (default 5), `--cases`, `--call-budget` (default 30), `--keep-bus`.

A board 15 dry run takes about two minutes and 80 to 140 GitHub calls.

## Doctor

doctor.txt holds one line per check:

- the script exists and is executable;
- `gh api rate_limit` has more than 200 graphql calls left;
- the board lock is free. The path is read out of the script's own `lock_path`, never guessed;
- with `--apply`: `HT_TOKEN` is set and `SHIP_SESSION_NAME` is an agent login, not Valentin's.

## Drive

Only `run` drives. To regrade a saved run, with no new board read:

```sh
.claude/skills/verify-reconcile/grade.py ~/.local/state/verify-reconcile/<run-id>
```

## Evidence

Every run keeps `~/.local/state/verify-reconcile/<run-id>/`:

| File | What it proves |
| --- | --- |
| meta.json | board, label, apply, limit, call budget, script and git sha |
| doctor.txt | the board was worth driving |
| cases.json | the cards whose columns were checked |
| dry1.out, dry1.err | what one dry run planned, and its github call count |
| apply.out, apply.err | what the apply run moved |
| dry2.out, dry2.err | what a second dry run planned after the moves |
| verdict.txt, verdict.json | one PASS/FAIL line per check, then the verdict |

Grading reads the script's own output lines, never a chat's claim. On a PR or ticket, attach the verdict.txt file.

## Cleanup

`run` deletes nothing. It leaves every evidence directory in place and starts no long-lived process: each reconcile call ends before the next starts.

## When it runs

Every change to `skills/hypertask-work/reconcile` or its docs runs it here, with both verdicts on the PR. GitHub CI runs only `tests/test_verify_reconcile.py`: the live run needs this server's board login and GitHub budget.

## Gotchas

- `calls` FAILs today. Board 15's dry run makes 80 to 140 GitHub calls against a budget of 30 until SOFT-2919 lands. That is the known baseline, not a broken check.
- Live cards move. Update `cases/board15.json` when one legitimately changes column, and never edit it to make a run pass.
- One run per board at a time, because both share the board lock (SOFT-2853). A held lock fails the doctor before any board read.
- Never run `--apply` on board 15 here until the reconciler login may: `require_board15_agent` refuses any agent but the vcc or HT Product Lead token.
