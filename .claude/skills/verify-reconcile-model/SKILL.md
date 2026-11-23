---
name: verify-reconcile-model
description: "Exhaustive check that reconcile uses one stage model and one evidence order on every board. Run after changes to skills/hypertask-work/reconcile planning logic."
---

# Verify reconcile model

Reconcile picks a card column from worker and GitHub facts. A bug here moves the wrong ticket on one board while another stays correct. This check enumerates fact combinations and asserts fixed points, grace behaviour, protected columns, and matching PR–worker–idle ranking on boards 15, 2060, and 13556.

## Property

After a planned move, check the next plan both inside and after the two-hour grace window. Reopened backlog cards ignore merges older than `staleness.sectionChangedAt`. Work and review stages count merges regardless of later edits. Protected, unknown, waiting and blocked cards never move. Every configured board ranks PR evidence above worker above idle the same way. Main's column-rule rows run alongside the fixed-point enumeration.

## Command

```bash
python3 .claude/skills/verify-reconcile-model/check_model.py
```

Or: `python3 -m unittest tests.test_verify_reconcile_model -v`

## Coverage

| Code | Role |
|------|------|
| `skills/hypertask-work/reconcile` | `Stage`, `plan_stage`, `target`, `BoardConfig`, `BOARDS` |
| `tests/test_verify_reconcile_model.py` | Enumeration and assertions; the skill's `check_model.py` runs this file |

Sync commit: bump when reconcile planning changes without re-running this check.

## Out of scope

Live Hypertask reads, GitHub prefetch, apply limits, board-15 login guard, and product-worker discovery.
