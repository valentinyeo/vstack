pstack-verifier: FAIL @ 6c842d14146867f66f738dfa34d911d4b69d5135

Verifier model: deepseek-v4.1-flash, GitHub-hosted.

## What I read and ran

Read in full: `skills/hypertask-work/reconcile` (670 lines), `skills/hypertask-work/reconcile.md`, `tests/test_hypertask_work.py`, and the complete diff `3085247..6c842d1` (3 files, +216/−36). Head is still `6c842d1`; I edited no tracked files (`git status` shows only the pre-existing untracked `picker-base/`).

Commands:
- `python3 skills/hypertask-work/reconcile --self-test` → `Ran 59 tests … OK` (also with `RECONCILE_JOBS=4`)
- `python3 -m unittest tests.test_hypertask_work` → 59 OK; `tests.test_board_columns tests.test_fault_routes` → 11 OK; full `discover` suite → 122 OK
- Real scripts (head **and** base) run end-to-end against a scoped fixture in `/tmp/vf` (fake `gh`/`hypertask`/`systemctl`, `HOME`, `FLEET_LEASE_DIR`; no real writes): 7-ticket board, 25 old tickets, 105-PR pagination day, >1000-merge day, recent-merge-with-mid-branch, one PR naming two tickets, board 15 dry run, `--apply --limit 2`, `--section Doing`, empty board, unmanaged-only board, `--limit 0`, `--apply --section`, `--board 99`
- Failure injection: `gh` graphql down, malformed JSON, failing `gh pr view`; `RECONCILE_JOBS=1/0/abc/-`; determinism across `RECONCILE_JOBS=3/6/8` (byte-identical PLAN/KEEP)
- Live GitHub API checks of the two new query assumptions (network available): `head:codex` → 8, `head:codex/add-cloudflare-hosting-docs` → 1, `head:cloudflare` → 0 (prefix-only confirmed, also under `user:` scope); `is:merged merged:2026-10-30..2026-10-30` → the one PR merged that day, next day → 0

## Result against the spec

- **Done when — parity**: PLAN/KEEP identical to base in every fixture except the one class the body names as a tradeoff. Old merged PRs stay owned via title (`SOFT-1`), exact URL/branch scan, and the new `head:<KEY>` lookup (`SOFT-2`, `SOFT-7` missing `createdAt`, 25-ticket batch of 12, board 15 `HTPR-1`). A PR merged 2 days ago with the key mid-branch is still found by the window scan.
- **Done when — under 120 s**: not reproducible here (no board credentials). The proof's phase table matches the code's phases and call shape: my fixture shows exactly 32 branch searches (1 open + 31 merged days) and a working `old-heads` batch, so the reported 13.5 s branch phase is structurally consistent.
- **Done when — test**: `test_ticket_with_pr_merged_long_ago_still_owned` exists and covers both the keyed-search path and the prefix fallback; I verified the `head:` prefix semantics it depends on against live GitHub rather than trusting the mock.
- **Behaviour exercised, then attacked**: `--apply` makes the same two moves as base; graphql/malformed-JSON/`gh pr view` failures keep base's fail-closed exit codes, and a failed PR read is still UNKNOWN on its own ticket only; empty board issues no branch searches; timing table and one stderr line per phase work; `RECONCILE_TIMING` and bad flags behave as before.

## Notes (new at this head, all fail closed)

1. Documented tradeoff reproduced: a PR merged >30 days ago whose only link is a mid-name branch loses ownership (fixture `SOFT-3`: base `PLAN … AI Review`, head `KEEP Todo`). Their "identical diff" is board-state dependent; the loss class itself is disclosed.
2. An unparsable board `createdAt` now aborts the whole run (`fleet/reconcile: Invalid isoformat string`, rc=1, no PLAN/KEEP) instead of one ticket's UNKNOWN; base ignored `createdAt`. Same class: a search node lacking `number`/`repository` raises in `prefetch`, outside the per-ticket handler base used.
3. `RECONCILE_JOBS=abc` → import-time traceback; `RECONCILE_JOBS=0` → `max_workers must be greater than 0`. Both rc=1, no moves, no validation or message in the docs.
4. >1000 PRs merged on a single calendar day aborts the run (`GitHub branch search exceeds daily limit`); base completed that fixture. Unrealistic at these two owners' volume.
5. Concurrency raises GitHub secondary search-rate-limit exposure (32 branch searches plus parallel keyed batches); the author's real run completed.
6. `TIMING` is module-global and never cleared, so repeated `main()` calls in one process (tests) accumulate rows; `verifier_policy`/`systemctl` bypass `run()`, so the "external calls" column undercounts. Both cosmetic.
7. Unchanged base fault, reproduced identically at both heads: keyed search over 100 hits aborts with `SOFT-1: GitHub search truncated`.
8. Comments: the new docstrings are accurate and non-redundant; the `head_pulls` docstring's GitHub-behaviour claim turned out correct when checked live.

VERDICT: PASS+NOTES

Trace: https://github.com/valentinyeo/vstack/actions/runs/44386401119

