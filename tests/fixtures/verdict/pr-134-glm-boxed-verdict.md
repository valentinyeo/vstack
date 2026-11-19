All checks done. Base-vs-head: full suite (178 tests) passes at head; the mandatory `test_pstack_sources.py` passes (2 tests, OK).

FAIL — none. Verdict below.

```
PASS
```

## Commands run and outputs

1. Mandatory check:
```
python3 -m unittest discover -s tests -p test_pstack_sources.py -v
Ran 2 tests in 0.002s
OK
```

2. Changed skill's own suite:
```
python3 -m unittest discover -s tests -p test_hypertask_work.py -v
Ran 104 tests in 1.373s
OK
```

3. Whole repo at head:
```
python3 -m unittest discover -s tests
Ran 178 tests in 8.941s
OK
```

4. Neighbouring contracts:
```
python3 -m unittest tests.test_column_verifier tests.test_board_columns tests.test_verdict \
  tests.test_pick_verifier_model tests.test_advisor_verdict
Ran 45 tests in 4.192s
OK
```

5. Catalog checkout matches the pin (`catalog-ref f524508f019ebe6e05d700919f39b929b0bbba92` in `.verifier-catalog/.git/HEAD` equals `.skill-lint.json`).

## Contract exercises (real skill, user-level)

- Batched reads: `read_pull_batch` handles 25-PR groups, split on refusal, per-repo failure marking. Suite: `test_prefetch_reads_prs_in_batches`, `test_a_refused_batch_splits_so_one_repository_hides_nothing`.
- Rate limit prose vs error: `test_only_error_text_counts_as_a_rate_limit`; a failed batch quoting a limit in data is not one (`test_a_failed_batch_quoting_a_rate_limit_in_data_is_not_one`).
- CLI clean stop: `--apply` with a spent budget stops before any board read (`test_spent_budget_skips_the_run_before_reading_the_board`, hyper log empty); a mid-run limit prints exactly one line and exits 0.
- Waiting-on-Valentin / blocked: `test_waiting_or_blocked_ticket_stays_put` — keeps column, and waitingOnUserId/blockerCommentId feed the keep row.
- Board 2060 merged work: merged PR with current-head PASS sits in "AI Review, live proof pending"; alias rows preserve the pending stage (`test_board_columns`, `Column contract`).
- Policy cache: one call per commit across runs, including a cached "no policy" answer.

## Three break attempts

1. **Stale old-layout cache.** Wrote a base-era `pulls.json`-shaped entry into `cache.json`. Result: `attempt1 stale pulls.json-shaped cache -> OPEN red False` — the PR was re-read and served the true (red) facts, not the stale `passed: True`.
2. **Wrong-shape policy cache + unreadable window cache.** A cached `['bogus']` under a policy key is refetched (`attempt2a wrong-shape cache -> {'v': 1} calls: 1`); `{not json` in the merged-window cache forces a full dated search, matching the prose "a cache that cannot be read means one full search" (suite: `test_unreadable_cache_means_one_full_search`).
3. **Stale budget probe.** `gh api rate_limit` says budget remains, but the first GraphQL call reports a spent budget: the run stops on that response (`test_rate_limit_stops_the_run_at_once_with_one_clean_line`, reset line printed once, exit 0). A 403 that is not a rate limit still fails loudly (exit 1).

No attempt broke the fix.

## Notes (base faults / limits)

- Unchanged-base: none observed; base behaviour preserved everywhere I probed (open-PR one-call read, UNKNOWN scoping, five-move cap).
- Limit: PR discussion comments and any service-side state were not inspected; no service access.
- Limit: prose says "applies no move from that run", while the code prints `N moves already applied before it` when a move landed before the limit. The message is honest; I read the prose as applying from the stop onward. Not diff-induced, noting it once.
- Limit: I could not force a real mid-CLI move-then-limit sequence end to end without a live Hypertask; the no-move CLI path and the move path are each covered separately.