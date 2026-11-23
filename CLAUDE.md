# vstack

pstack owns workflow rules.
vstack holds shared skills and checks.
Product repos hold their own facts.

Hypertask board: 13556
Each chat working from this repo uses its own label on board 13556 (its chat name): Hypertask Reconciler, Responsive Mode, VPS Admin, PR Housekeeping, Board Drain Loop, Token Ladder. Vstack Maintainer uses Vstack.

## Rules and the checks that enforce them

Changes land through pull requests.
Every hook runs in `advisor-checks` on GitHub.
Verification follows pstack create-verification-skill, maintain-verification-skill and Shipping step 1; the one verifier is the verifier job in pstack-sources.yml, on a GitHub runner.
Nobody pushes to main.

| Rule | Enforced by |
|---|---|
| Worker briefs name pstack and the worker kickoff | `hooks/pstack-source.py` |
| PRs name a real pstack source | `hooks/pstack-source.py` |
| Briefs and PRs walk every book item | `hooks/book-check.py` |
| Advice replies name their pstack source | `hooks/pstack-reply.py` |
| Promised work starts in that turn | `hooks/said-started.py` |
| A chat with an open ticket never ends its turn idle | `skills/responsive-mode/idle-stop.py`, `tests/test_idle_stop.py` |
| A chat never waits on Valentin to merge or review a finished, green PR | `skills/hypertask-work/merge-ask`, `skills/board-drain/drain-check`, `skills/responsive-mode/reply-check.py`, `tests/test_board_drain.py`, `tests/test_responsive_mode_checks.py` |
| Advisors respect configured project boundaries | `hooks/out-of-bounds.py` |
| Long-chat and pacing hooks act only in a chat that loaded valentin-mode | `hooks/valentin_mode_loaded.py`, `tests/test_valentin_mode_loaded.py` |
| Responsive mode's rules reach the chat without the chat choosing to fetch them | `skills/valentin-mode/context.py`, `.claude/skills/verify-valentin-mode/grade.py`, `tests/test_valentin_mode_context.py` |
| Billing failures go once on the ticket | `hooks/billing-quiet.py` |
| No bare ticket ids to Valentin | `hooks/no-bare-ids.py`, `tests/test_no_bare_ids.py` |
| Each chat and every pacer worker refuses heavy local builds and tests before they start | `hooks/heavy-local-guard.py`, `config/heavy-local.json`, `scripts/worker-shims`, `tests/test_heavy_local_guard.py`, `tests/test_worker_shims.py` |
| Every hook passes its self-test on GitHub | `advisor-checks` workflow on PRs |
| A vstack change keeps chats working | `.claude/skills/verify-vstack/run` (Doctor in CI, Drive by the PR owner), `tests/test_verify_vstack.py` |
| A hook never points at a missing script | `hooks/run-hook` (fail open), `scripts/check-hook-paths`, `tests/test_hook_paths.py` |
| A change ships only when a journey exercised it | `scripts/uncovered_gate.py` (behind every vstack review), `GAP uncovered pass gate` in `skills/pstack-diff`, `tests/test_uncovered_gate.py` |
| Every chat reads one true server facts file | `docs/servers.md`, `config/servers.json`, `tests/test_server_facts.py` |
| A merged rule reaches a running chat without anyone asking | `hooks/skill-update.py`, `tests/test_skill_update.py` |
| A chat whose board watcher died is told to re-arm in its own turn, and the fleet report shows the time | `hooks/board-drain-guard.py`, `skills/board-drain/loop-state` (`watcher dead since`), `tests/test_board_watcher_guard.py`, `tests/test_fleet_report.py` |
| vstack builds tools each chat runs on its own work; the builder never runs them for other chats | `skills/pr-housekeeping/pr-queue` (`--mine` required), `scripts/pacer-check.py` (`Owner chat:`), `tests/test_pr_queue.py`, `tests/test_pacer_enforce.py`, `scripts/skill-check-retired.txt`, `tests/test_skill_check.py` |
| A chat retains its merged PR until its own local copies are gone | `skills/pr-housekeeping/pr-queue`, `tests/test_pr_queue.py`; branch-only cleanup in `skills/repo-tidy/repo-tidy`, `tests/test_repo_tidy.py` |
| A vstack tool acts only on the chat that runs it; the building chat is never its operator | `tests/test_own_chat_only.py` |
| A PR never collides with an older open PR on a guarded file or ticket | `scripts/pr-overlap`, `.github/workflows/pr-overlap.yml`, `tests/test_pr_overlap.py` |
| Worker briefs name both fault destinations | `hooks/book-check.py` |
| Worker tasks can run on vendor cloud agents | `skills/cloud-agent/cloud-agent`, `tests/test_cloud_agent.py` |
| Poteto ticket writes use one helper | `hooks/ticket-way.py`, `bin/poteto-ticket` |
| Board 2060 aliases preserve live-proof stages | `tests/test_board_columns.py`, `Column contract` workflow |
| Reconcile keeps boards 15 and 2060 truthful | `skills/hypertask-work/reconcile`, `tests/test_hypertask_work.py` |
| Boards stay true without anyone asking | lease start/end sync, `skills/board-drain/watch`, `bin/hand-moves` |
| Skill budgets, copied rules, references and new-skill prior art pass (pstack `poteto-mode/playbooks/authoring-a-skill.md`: "When in doubt, delete. Keep only prose that changes a decision.") | `.github/workflows/skill-lint.yml`, pinned shared house-rules script |
| Loaded skills stay lean: no dead links, duplicate names, retired terms or oversized descriptions | `scripts/skill-check.py`, `tests/test_skill_check.py` |
| A PR adds no verification gate pstack does not ask for | `hooks/pstack-new-gates.py`, `checks` workflow step |
| New skill, script or hook names its pstack skill and root cause | `tests/test_skill_prior_art.py`, `config/tool-registry.txt` |

Skill-lint commands and exceptions: [shared reference](https://github.com/valentinyeo/house-rules/blob/d60a2c149b29ef555dec42f20afc074543624f7b/docs/skill-lint.md).

Poteto ticket commands live in `bin/poteto-ticket`.
Use `new`, `claim`, `log`, `review`, `done`, `ask`.
Run `bin/install-ticket-claim` to install claim routing.
The installer preserves unrelated global claim routes.
