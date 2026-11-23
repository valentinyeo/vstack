# Board sync reads a real board

`skills/hypertask-work/reconcile` reads a real board and plans the right moves: one full dry run of board 15, and with `--apply --limit 5` the moves land and a second dry run plans none. The proof bar is the apply then the second dry run, because a dry run alone shows what reconcile would do, not that it did it.

## Sub-features

- `dry-run.finished`: the run printed `DRY RUN board=N tickets=N unknown=N` and no `SKIP ... reconciliation already running` line.
- `dry-run.unknown-zero`: `unknown=0`, so no ticket failed to read.
- `bus.reachable`: the first dry run prints no `Failed to connect to bus`, and `run` sets `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` when they are unset.
- `calls.within-budget`: stderr's `reconcile: github calls=N (graphql=N, rest=N)` total is at or below `--call-budget`, default 30.
- `apply.ran`: the apply run printed `PREVIEW board=N tickets=N unknown=N` and no traceback.
- `apply.settled`: no card the apply run MOVEd is planned again in the second dry run.
- `apply.converged`: the second dry run plans fewer moves than the first, and none when the first fit inside the limit.
- `cases.known-card`: each ticket named in the cases file appears in the run's plan lines.
- `cases.column`: the column that card ends the run in equals its `expect`.
- `cases.proves`: at least one case names a card that sat outside `expect` when the board was read.

## How to get to it (user POV)

- Run the board sync by hand, or wait for its timer. Nothing moves; it says what it would do.
- A chat runs the board sync with `--apply --limit 5`, the cards move to their true columns, and a manual sync afterwards reports nothing to do.
- Name a ticket that shows in the wrong column and the column it belongs in, then run the check with a temp cases file.
- From a chat started by a timer with no login session, the same sync should still know which tickets have a live worker.

## Driving it with verify-vstack

Preconditions:

- This server, where `hypertask` and `gh` are logged in. One board 15 dry run takes about two minutes and spends most of a hundred GitHub graphql calls, so the budget must be above 200.
- Board 15 is free: no timer and no other session mid-reconcile (SOFT-2853). A held lock fails the doctor before any board read.
- Any case names a card that sits in a column other than the one it belongs in, because an already-correct card proves nothing.

- **Doctor first.** `run` writes `~/.local/state/verify-reconcile/<run-id>/meta.json`, sets the user session bus unless `--keep-bus`, and stops with exit 3 unless the script is executable, `gh api rate_limit` has more than 200 graphql calls left, the board lock is free (path read from the script's own `lock_path`), and with `--apply` `HT_TOKEN` plus a `SHIP_SESSION_NAME` agent login are set.
- **Dry run.** Run `.claude/skills/verify-vstack/tools/reconcile/run --board 15`. It writes `dry1.out` and `dry1.err`, then grades `finished`, `unknown`, `bus` and `calls`.
- **Apply and converge.** Run `.claude/skills/verify-vstack/tools/reconcile/run --board 15 --apply --limit 5` with the board 15 login. It adds the apply run and a second dry run (`apply.out`, `apply.err`, `dry2.out`, `dry2.err`) and grades `apply`, `settled` and `converged`.
- **Name live cards.** Write the temp cases file and pass it, never shipping one in the skill:

  ```sh
  cat > /tmp/cases.json <<< '[{"ticket": "HTPR-9387", "expect": "AI Review"}]'
  .claude/skills/verify-vstack/tools/reconcile/run --board 15 --cases /tmp/cases.json
  ```

  Before the fix, `cases` FAILs; that run is the report. After the fix, run the same file with `--script /path/to/fix-branch/skills/hypertask-work/reconcile` and `cases` PASSes. Paste both verdicts on the fix PR. A regression you never want back belongs in `tests/test_hypertask_work.py` as a unit test.
- **Prove the bus check itself.** Run `env -u XDG_RUNTIME_DIR -u DBUS_SESSION_BUS_ADDRESS .claude/skills/verify-vstack/tools/reconcile/run --board 15 --keep-bus`. It must FAIL `bus`, because a check that never fails is not a check.
- **Evidence.** `meta.json` (board, label, apply, limit, call budget, script and git sha), `doctor.txt`, `cases.json`, `dry1.*`, `apply.*`, `dry2.*`, `verdict.txt` and `verdict.json`. Attach `verdict.txt` to the PR or ticket. `run` deletes nothing and starts no long-lived process.
- **Regrade a saved run.** Run `.claude/skills/verify-vstack/tools/reconcile/grade.py ~/.local/state/verify-reconcile/<run-id>`.

## Gotchas

- `calls` FAILs today. Board 15's dry run makes 80 to 140 GitHub calls against a budget of 30 until SOFT-2919 lands. That is the known baseline, not a broken check. A run straight after another came in at 28 to 29; a low number is never a reason to weaken the check.
- `gh api rate_limit` is free and is not counted, which is why the doctor can always probe the budget. The call count covers `gh` only, not Hypertask reads.
- Without the bus every ticket read fails with `systemctl --user failed: Failed to connect to bus: No medium found`. On board 15 that was 224 UNKNOWN lines in one run, which also fails `unknown`.
- `--keep-bus` is for proving the check, never for a proof run on a PR. A bus address set to the wrong uid fails the same way; `run` builds both paths from `id -u`.
- Board 15 has 366 tickets at the time of writing, so a dry run takes about two minutes. A half-read board reports wrong unknowns, so do not kill it early.
- On board 15 `--apply` needs the HT Product Lead or vcc token: `require_board15_agent` refuses any other agent, so the Hypertask Reconciler login cannot apply there yet. A dry run needs no token.
- Reconcile re-reads each ticket before it moves it and prints `SKIP ... changed since preview` when the board moved underneath. That is not a failure; the second dry run catches what is left.
- Board 15 caps its own limit at 5, whatever `--limit` says. `converged` reads the limit from `meta.json`, so pass the limit you drove.
- A ticket missing from the output fails `cases` rather than passing quietly. Look for its `UNKNOWN` line first.
- A FAIL on `calls` or `cases` is a finding about the board or the script. Fix the script; do not soften the check.
