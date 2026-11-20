# Board sync (reconcile) plan

Goal: boards stay true by themselves. No chat moves a card by hand.

Reconcile is a service, not a central syncer. Each chat runs it on its own board and label, under its own login. A chat that sees a wrong card reports it to the owner, who fixes the tool for every chat.

Owner: Hypertask Reconciler (vstack chat `live-2a735a3c`). It maintains the script and never runs `--apply` on other chats' cards. Workers write all code through `plan-pick --run`.

## Why the tool keeps breaking

Eleven fixes landed in two days, and each one patched a symptom.
Every fix assumed that each board can keep its own ordered rule list.
That assumption is wrong. The two lists disagree on two things:

- Board 2060 ranks an open PR above a live worker. Board 15 ranks the worker first.
- Board 2060 applies the 2h grace only after the hard evidence. Board 15 applies it first.

So the same facts give different answers on each board.
A fix on one board never reaches the other.
The answer is one rule model with one evidence order: PR, then worker, then idle.
The rules speak in stages, never in column names.

## Boards belong to their chats

Each chat designs its own board and columns. The script never assumes a layout.
The one fixed rule from Valentin: every board has a verification column.
A board says which of its columns plays which stage in its repo's `board.yml`.
That file already exists in the agent template (`roles:` maps a role to a real column).
Reconcile reads that map. A column the map does not name is left alone.
A board whose map has no verification column fails with one clear line and moves nothing.
The owner of reconcile never edits another chat's board or its map.

## Landing order

All of these PRs edit `skills/hypertask-work/reconcile`. They land one at a time, in this order, each rebased on the one before it.

| # | PR | Ticket | Depends on |
| --- | --- | --- | --- |
| 1 | #135 a grep is not a worker | SOFT-2799 | none |
| 2 | board 15 catches stale, PR-first, grace on idle only | HTPR-9521 | 1 |
| 3 | verify-reconcile skill (new files only) | SOFT-2920 | none, lands any time |
| 4 | one rule model plus an exhaustive model check | SOFT-2921 | 2 |
| 5 | loud failure without a user bus; under 30 GitHub calls | SOFT-2919 | 4 |
| 6 | board 15 apply accepts any agent's own login | SOFT-2919 | 5 |
| 7 | label runs do not block the board lock | SOFT-2853 | 6 |

PR 1 comes before PR 2. Once board 15 counts processes, a plain `grep HTPR-NNNN` would hold a stale card in In Progress. That is bug 1 in reverse. PR 1 stops it.

## PR 1: a grep is not a worker (#135)

- [ ] Fix its one red check (skill-lint / pstack-verifier) and rebase on main.
- [ ] Unit: `python3 -m unittest discover -s tests` passes.
- [ ] Live: board 2060 dry run shows no ticket held in Doing by a grep.

## PR 2: board 15 rules (HTPR-9521)

- [ ] Rebased on PR 1. Board 15 reads leases and processes through PR 1's `is_worker`.
- [ ] Unit: one test per real card, built as facts through the rule function. These cards are HTPR-9514, HTPR-9511 (stale In Progress goes to Backlog), HTPR-9387 (open PR inside the grace goes to AI Review) and HTPR-7742 (worker plus open PR goes to AI Review).
- [ ] Unit: an idle card in Verification Backlog is kept.
- [ ] Live: `verify-reconcile --board 15` dry run has unknown=0. No card with a live plan-pick worker is planned out of In Progress.

## PR 3: verify-reconcile (SOFT-2920)

- [ ] Proof run pasted in the PR: one dry run on board 15, and one with no user bus that must FAIL `bus`.
- [ ] Live cases list only cards whose current column differs from the expected one. A case that passes under the old code proves nothing. Real-card regressions live in unit fixtures (PR 2), not here.

## PR 4: one rule model and a model check

- [ ] Change: one evidence order for every board, written in stages (backlog, in progress, checks, review, verification). The per-board rule lists and the hardcoded board 15 and 2060 configs are deleted. Each board's stage map comes from its repo's `board.yml` `roles:`, which gains a required `verification` role.
- [ ] Unit: a board with no verification role fails loudly and moves nothing. A column no role names is never moved.
- [ ] Unit (model check): enumerate every fact combination. That covers column, alive, PR states (none, open red, open green, merged pass, merged no pass), waiting, blocked, verification, and age (under 2h, over 2h). For each, on both boards:
  - Fixed point: after the planned move, with age reset to 0, the next plan is KEEP. The same holds once age passes 2h. No card flip-flops.
  - Hard evidence (open or merged PR, live worker) moves a card even inside the grace.
  - A protected or unmanaged column never moves.
  - Both boards rank PR over worker over idle the same way.
- [ ] Ticket SOFT-2921 runs pstack `create-formal-verification-skill` (valentin mode: sync work is formal). This exhaustive check is its first deliverable.
- [ ] Live: `verify-reconcile --board 15 --apply` then the second dry run plans no moves for the cards it moved.

## PR 5: loud on a missing bus, fewer calls (SOFT-2919)

- [ ] Change: set `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` defaults when missing. If worker facts still cannot be read, exit non-zero with one clear line. Never print 348 UNKNOWN lines.
- [ ] Change: read PR state from the search result. Drop the per-PR `read_product_pull` calls.
- [ ] Perf: metric is `github calls=` from stderr on `reconcile --board 15`. Baseline on main: 79, measured by HT Product Lead on 20 Nov. Fails above 30.
- [ ] Live: `env -u XDG_RUNTIME_DIR -u DBUS_SESSION_BUS_ADDRESS verify-reconcile --board 15 --keep-bus` passes `bus` and `unknown`.

## PR 6: board 15 apply login

- [ ] `require_board15_agent` accepts any agent login, never a person's. Today it allows only vcc and HT Product Lead.
- [ ] Live: a chat's own `--label <its label> --apply --limit 1` run on board 15 moves one card and logs it under that chat's agent.

## PR 7: lock (SOFT-2853)

- [ ] A label run never blocks a whole-board run for longer than its own run.
- [ ] Unit: two label runs and one board run, started together, all finish or SKIP with a clear line.

## After every PR

- The owner runs `verify-reconcile` on boards 15 and 2060 before the change goes live.
- Each chat runs `verify-reconcile --label <its label>` in its own loop.
- Every card a chat reports as wrong becomes a unit fixture first, then a fix.
- Done means a second dry run after apply plans no moves.
