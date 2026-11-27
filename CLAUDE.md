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
| Worker briefs name pstack and the worker kickoff (house `worker-brief-pstack-source`) | `hooks/pstack-source.py` |
| Briefs and PRs walk every book item (house `book-check`) | `hooks/book-check.py` |
| Promised work starts in that turn (pstack `skills/poteto-mode/playbooks/autonomous-run.md`: "Define done, then drive to it without stopping.") | `hooks/said-started.py` |
| A chat with an open ticket never ends its turn idle (pstack `skills/poteto-mode/playbooks/autonomous-run.md`: "Stop when the predicate is met.") | `skills/responsive-mode/idle-stop.py`, `tests/test_idle_stop.py` |
| A chat never waits on Valentin to merge or review a finished, green PR (pstack `skills/poteto-mode/playbooks/autonomous-run.md`: "Do not park reversible work for the human or use `AskQuestion`.") | `skills/hypertask-work/merge-ask`, `skills/board-drain/drain-check`, `skills/responsive-mode/reply-check.py`, `tests/test_board_drain.py`, `tests/test_responsive_mode_checks.py` |
| Advisors respect configured project boundaries (pstack `skills/principle-boundary-discipline/SKILL.md`: "Validate, narrow types, and handle errors where data crosses a system boundary (CLI args, config files, external APIs, network).") | `hooks/out-of-bounds.py` |
| Long-chat and pacing hooks act only in a chat that loaded valentin-mode (house `long-chat-auto-handover`) | `hooks/valentin_mode_loaded.py`, `tests/test_valentin_mode_loaded.py` |
| Responsive mode's rules reach the chat without the chat choosing to fetch them (pstack `skills/principle-encode-lessons-in-structure/SKILL.md`: "Encode the rule as a lint, metadata flag, runtime check, or script instead of more text.") | `skills/valentin-mode/context.py`, `.claude/skills/verify-vstack/tools/valentin-mode/grade.py`, `tests/test_valentin_mode_context.py` |
| Billing failures go once on the ticket (pstack `skills/principle-make-operations-idempotent/SKILL.md`: "Design every state-changing operation to converge to the correct state however many times it runs and wherever the previous run stopped.") | `hooks/billing-quiet.py` |
| No bare ticket ids to Valentin, and no pull request link without that work's ticket link (pstack `skills/principle-encode-lessons-in-structure/SKILL.md`: "Encode the rule as a lint, metadata flag, runtime check, or script instead of more text.") | `hooks/no-bare-ids.py`, `tests/test_no_bare_ids.py` |
| Each chat and every pacer worker refuses heavy local builds and tests before they start (house `heavy-local-guard`) | `hooks/heavy-local-guard.py`, `config/heavy-local.json`, `scripts/worker-shims`, `tests/test_heavy_local_guard.py`, `tests/test_worker_shims.py` |
| Every hook passes its self-test on GitHub (pstack `skills/correct/SKILL.md`: "Prove each new check fails on a real past mistake. Run the same command locally and in CI.") | `advisor-checks` workflow on PRs |
| A vstack change keeps chats working (pstack `skills/principle-prove-it-works/SKILL.md`: "Verify every output by checking the real thing directly: run the feature, read the actual value, inspect the diff.") | `.claude/skills/verify-vstack/run` (Doctor in CI, Drive by the PR owner), `tests/test_verify_vstack.py` |
| A hook never points at a missing script (pstack `skills/principle-prove-it-works/SKILL.md`: "Script the check when you can.") | `hooks/run-hook` (fail open), `scripts/check-hook-paths`, `tests/test_hook_paths.py` |
| A change ships only when a journey exercised it (house `uncovered-pass-gate`) | `scripts/uncovered_gate.py` (behind every vstack review), `GAP uncovered pass gate` in `skills/pstack-diff`, `tests/test_uncovered_gate.py` |
| A change the user can see ships a short before and after video (house `ui-video-proof-gate`) | `scripts/video_proof_gate.py`, `scripts/verdict.py`, `tests/test_video_proof_gate.py` |
| A repo a chat ships from refuses a merge until a checker that did not write the code has passed it (house `merge-gate`) | `skills/board-drain/merge-gate`, `skills/board-drain/drain-check`, `tests/test_merge_gate.py` |
| Every chat reads one true server facts file (house `server-facts`) | `docs/servers.md`, `config/servers.json`, `tests/test_server_facts.py` |
| A merged rule reaches a running chat without anyone asking (pstack `skills/poteto-mode/playbooks/autopilot-full.md`: "Each tick re-reads this playbook from trunk and fixes drift") | `hooks/skill-update.py`, `tests/test_skill_update.py` |
| A chat switched to another harness (Codex, Antigravity, Pi) gets valentin-mode and its board drain loop without anyone asking (house `switch-keeps-mode`) | `hooks/harness-start.py`, `scripts/install-mode-start-hook.py`, `skills/valentin-mode/pi-start.ts`, `tests/test_harness_start.py` |
| Board watchers (including Hypertask Reconciler) keep polling across cycles, pulse into loop-state, block Stop in their own chat when dead, push Valentin once after 10m dead, and show dead time and notice status in the fleet report (house `board-drain-view-watcher-pace`) | `skills/board-drain/watch`, `hooks/board-drain-guard.py`, `skills/board-drain/loop-state`, `skills/fleet-report/fleet-report`, `tests/test_board_drain.py`, `tests/test_board_watcher_guard.py`, `tests/test_fleet_report.py` |
| vstack builds tools each chat runs on its own work; the builder never runs them for other chats (house `pacer-check`) | `skills/pr-housekeeping/pr-queue` (`--mine` required), `scripts/pacer-check.py` (`Owner chat:`), `tests/test_pr_queue.py`, `tests/test_pacer_enforce.py`, `scripts/skill-check-retired.txt`, `tests/test_skill_check.py` |
| A chat retains its merged PR until its own local copies are gone (house `repo-tidy-automated-cleanup`) | `skills/pr-housekeeping/pr-queue`, `tests/test_pr_queue.py`; branch-only cleanup in `skills/repo-tidy/repo-tidy`, `tests/test_repo_tidy.py` |
| Every agent removes its own merged worktree and branch after a merge, and a chat starting on a project sweeps the merged worktrees and old sibling branch folders that project left behind (house `repo-tidy-automated-cleanup`) | `skills/repo-tidy/repo-tidy --mine`/`--project`, `skills/board-drain/drain-check` finding `tidy`, `tests/test_repo_tidy.py`, `tests/test_board_drain.py` |
| A chat reclaims its own idle build output and old `/tmp` entries in seconds instead of waiting on the human, and an 85% disk names those two commands (pstack `skills/principle-encode-lessons-in-structure/SKILL.md`: "Encode the rule as a lint, metadata flag, runtime check, or script instead of more text.") | `skills/repo-tidy/repo-tidy --prune-caches`/`--clean-tmp`, `tests/test_repo_tidy_hygiene.py`; 85% warning in `skills/vps-state/vps-state`, `tests/test_vps_state.py` |
| A vstack tool acts only on the chat that runs it; the building chat is never its operator (pstack `skills/correct/SKILL.md`: "Give each piece of state one owner and each task one supported way.") | `tests/test_own_chat_only.py` |
| Worker briefs name both fault destinations (house `book-check`) | `hooks/book-check.py` |
| Worker tasks can run on vendor cloud agents (house `cloud-agent-offload`) | `skills/cloud-agent/cloud-agent`, `tests/test_cloud_agent.py` |
| Direct cloud worker launches check lane eligibility before any vendor runs (house `cloud-agent-vendor-routing`) | `skills/cloud-agent/cloud-agent` calls `plan-pick --lane-ok`, `tests/test_cloud_agent.py` |
| Poteto ticket writes use one helper (pstack `skills/correct/SKILL.md`: "Give each piece of state one owner and each task one supported way.") | `hooks/ticket-way.py`, `bin/poteto-ticket` |
| Reconcile keeps boards 15 and 2060 truthful (pstack `skills/principle-make-operations-idempotent/SKILL.md`: "Read the current state, compare it to the goal, and apply only the difference.") | `skills/hypertask-work/reconcile`, `tests/test_hypertask_work.py` |
| Boards stay true without anyone asking (pstack `skills/principle-make-operations-idempotent/SKILL.md`: "Derive each step from the state that exists, not from what the previous run meant to do.") | lease start/end sync, `skills/board-drain/watch`, `bin/hand-moves` |
| Skills pass pstack authoring validation (pstack `skills/poteto-mode/playbooks/authoring-a-skill.md`: "Validate the skill: frontmatter has `name` and `description`, referenced files exist, cross-skill links resolve.") | `scripts/skill-validate.py`, `.github/workflows/skill-lint.yml`, `tests/test_skill_validate.py` |
| Loaded skills stay lean: no dead links, duplicate names, retired terms or oversized descriptions (pstack `skills/principle-guard-the-context-window/SKILL.md`: "Context overflow degrades reasoning quality, creates compression artifacts, and halts progress.") | `scripts/skill-check.py`, `tests/test_skill_check.py` |
| A PR adds no verification gate pstack does not ask for (pstack `skills/poteto-mode/worker.md`: "The bar in your kickoff is the whole bar. Add no check, gate, sign-off or review round above it.") | `hooks/pstack-new-gates.py`, `checks` workflow step |
| A repo over 10 open pull requests refuses a new one (pstack `skills/principle-encode-lessons-in-structure/SKILL.md`: "Encode the rule as a lint, metadata flag, runtime check, or script instead of more text.") | `hooks/pr-cap-guard.py`, `scripts/pr-cap.py`, `scripts/register-user-hook.py`, `scripts/worker-shims`, `install`, `tests/test_pr_cap.py` |
| An agent label holding 5 or more open tickets in Doing+Checks+AI Review starts no non-urgent Todo ticket (house `wip-cap`) | `skills/board-drain/wip-cap`, `skills/hypertask-work/lease`, `skills/board-drain/drain-check`, `tests/test_wip_cap.py` |
| A house change to pstack is listed once, quoting pstack (pstack `skills/correct/SKILL.md`: "Replace hand-synced lists with one source of truth.") | `skills/pstack-diff/house.txt`, `tests/test_house_list.py` |
| Results, proof, verdicts and done summaries go in people comments (`comment add --kind done\|qa`), never in `activity add` (pstack `skills/principle-encode-lessons-in-structure/SKILL.md`: "Encode the rule as a lint, metadata flag, runtime check, or script instead of more text.") | `hooks/agent-lane-guard.py`, `skills/hypertask/scripts/ticket-lint`, `scripts/worker-shims`, `install`, `tests/test_agent_lane_guard.py` |
| Every real step on a ticket gets one short readable progress comment for Valentin (house `human-progress`) | `skills/hypertask-work/board-lint` rule `silent-ticket`, `skills/hypertask/references/tickets.md`, `skills/board-drain/drain-check`, `tests/test_board_lint.py` |
| A chat verifies every other agent on its board is still live when it arrives, and archives one it proved dead (pstack `skills/principle-encode-lessons-in-structure/SKILL.md`: "Encode the rule as a lint, metadata flag, runtime check, or script instead of more text.") | `skills/board-drain/peers`, `skills/board-drain/drain-check` note `peer:`, `tests/test_board_drain_peers.py` |

Poteto ticket commands live in `bin/poteto-ticket`.
Use `new`, `claim`, `log`, `review`, `done`, `ask`.
Run `bin/install-ticket-claim` to install claim routing.
The installer preserves unrelated global claim routes.
