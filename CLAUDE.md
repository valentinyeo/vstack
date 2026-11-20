# vstack

pstack owns workflow rules.
vstack holds shared skills and checks.
Product repos hold their own facts.

Hypertask board: 13556
Each chat working from this repo uses its own label on board 13556 (its chat name): Hypertask Reconciler, Responsive Mode, VPS Admin, PR Housekeeping, Board Drain Loop, Token Ladder. Vstack Maintainer uses Vstack.

## Rules and the checks that enforce them

Changes land through pull requests.
Every hook runs in `advisor-checks` on GitHub.
A separate model family verifies before merge.
Its verdict is PASS, PASS+NOTES or FAIL.
Nobody pushes to main.

| Rule | Enforced by |
|---|---|
| Worker briefs name pstack and the worker kickoff | `hooks/pstack-source.py` |
| Workers start only through plan-pick | `hooks/plan-pick-only.py` |
| PRs name a real pstack source | `hooks/pstack-source.py` |
| Briefs and PRs walk every book item | `hooks/book-check.py` |
| Advice replies name their pstack source | `hooks/pstack-reply.py` |
| Promised work starts in that turn | `hooks/said-started.py` |
| Advisors respect configured project boundaries | `hooks/out-of-bounds.py` |
| Claude helpers start only when plan-pick --claude-helper allows | `hooks/claude-helper-gate.py` |
| Billing failures go once on the ticket | `hooks/billing-quiet.py` |
| Every hook passes its self-test on GitHub | `advisor-checks` workflow on PRs |
| The verifier's model family differs from every `Author model:` line in the PR body | `scripts/pick-verifier-model`, `tests/test_pick_verifier_model.py` |
| Each chat tidies its own open PRs | `skills/pr-housekeeping/pr-queue`, `tests/test_pr_queue.py` |
| A PR never collides with an older open PR on a guarded file or ticket | `scripts/pr-overlap`, `.github/workflows/pr-overlap.yml`, `tests/test_pr_overlap.py` |
| A separate verifier posts a verdict before merge | Review procedure; branch protection is not configured here |
| Worker briefs name both fault destinations | `hooks/book-check.py` |
| Poteto ticket writes use one helper | `hooks/ticket-way.py`, `bin/poteto-ticket` |
| Board 2060 aliases preserve live-proof stages | `tests/test_board_columns.py`, `Column contract` workflow |
| Reconcile keeps boards 15 and 2060 truthful | `skills/hypertask-work/reconcile`, `tests/test_hypertask_work.py` |
| Boards stay true without anyone asking | lease start/end sync, `hooks/reconcile-auto.py`, `bin/hand-moves` |
| Verifier PASS requires commands and unchanged tracked files | `tests/test_column_verifier.py`, hosted verifier harness |
| Every verifier reads its verdict through one parser | `scripts/verdict.py`, `tests/test_verdict.py` |
| Every verifier falls through every allowed model and lane | `scripts/verifier_lanes.py`, `tests/test_run_verifier.py` |
| Advisor reports keep exact-head validation | `tests/test_advisor_verdict.py` |
| Skill budgets, copied rules, references and new-skill prior art pass | `.github/workflows/skill-lint.yml`, pinned shared house-rules script |
| Loaded skills stay lean: no dead links, duplicate names, retired terms or oversized descriptions | `scripts/skill-check.py`, `tests/test_skill_check.py` |

Skill-lint commands and exceptions: [shared reference](https://github.com/valentinyeo/house-rules/blob/d60a2c149b29ef555dec42f20afc074543624f7b/docs/skill-lint.md).

Poteto ticket commands live in `bin/poteto-ticket`.
Use `new`, `claim`, `log`, `review`, `done`, `ask`.
Run `bin/install-ticket-claim` to install claim routing.
The installer preserves unrelated global claim routes.
