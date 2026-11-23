# reconcile model verification map

The parts of reconcile planning this skill proves. Read this, then the file for
the feature.

## Baseline preconditions

- `python3` only. No network, no gh login, no board.
- The enumeration builds its own fact combinations, so a leftover from an
  earlier run cannot make a check pass.
- `python3 .claude/skills/verify-reconcile-model/check_model.py` runs
  `tests/test_verify_reconcile_model.py`, which is where every feature below is
  asserted.

## Features

- stage-model: one `Stage`, one `plan_stage`, one evidence order, enumerated
  over fact combinations and asserted as fixed points. Covers
  `test_exhaustive_model`.
- grace-window: every planned move is checked again inside and after the
  two-hour grace window, so a stale merge cannot promote a card.
- protected-columns: protected, unknown, waiting and blocked cards never move,
  and reopened backlog cards ignore merges older than
  `staleness.sectionChangedAt`.
- ranking: main's column-rule rows run alongside the enumeration, and every
  configured board ranks PR evidence above worker above idle the same way.
  Covers `test_main_column_rule_rows` and
  `test_a_merge_older_than_the_column_never_promotes`.

## Out of scope

Live Hypertask reads, GitHub prefetch, apply limits, and the board-15 login
guard. `verify-reconcile` drives those.
