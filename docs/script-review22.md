# Review of the 22 unsourced scripts

Ticket: https://app.hypertask.ai/detail/project-13556/128

Delete 12 scripts. Keep 10 with real pstack sources. Chats lose duplicate launch and turn-end guards, automatic shared-checkout updates, unused audits, and host-wide cleanup. Their own board watcher, response checks, context delivery, pacing boundary readers and cached CI wait remain.

## Evidence method and limits

Captured 2026-11-22T22:00:13.588033+00:00. The seven-day cutoff is 2026-11-15T22:00:13.588033+00:00. Read pstack 0.15.46's leaf skills before deciding.

Searched tracked callers, install, repo workflows/settings, global Claude hooks, skill frontmatter, recent debug files, state/log files and 362 recently modified Claude transcript files. Only entries timestamped within seven days counted. No transcript or message content is copied here.

Command mentions are counts of Bash tool inputs naming a script, including reads, searches and tests. They are not execution counts. Marker mentions are tool-result entries containing a script's block/reload marker, including quoted source; they are not proven denials. Every script had zero matching recent debug files. State counts are files modified within seven days, not executions; shared reconcile and board-drain state is attributed explicitly above. Absence is limited to these searched sources, not every harness or another machine.

The pre-change caller inventory and counts are in [script-review22-evidence.json](script-review22-evidence.json). The current GitHub call log has 88,803 recent rows; the updater log has 21 recent rows. These are counts only. The deployed GitHub wrapper differs from this checkout, but its `pr_checks_watch` also floors polling at `max(interval, PR_TTL)` and uses `cached_pr`. Counts alone never justified a keep. Each keep has a live caller and the specific pstack rule below; each deletion removes a duplicate owner, an unused tool, or symptom recovery.

## Verdicts

| Script | Verdict | Evidence and reason | Pstack source |
|---|---|---|---|
| `hooks/claude-helper-gate.py` | DELETE | Global Agent/Task and repo hooks; 1 marker mention. Re-asks plan-pick for a selected lane. Keep the decision in plan-pick, not a second chat gate. | Not retained |
| `hooks/gh-watch-guard.py` | DELETE | Repo hook and installer; 16 marker mentions. gh.pr_checks_watch already floors polling at 60 seconds; cached reads and budget enforcement own the shared token. | Not retained |
| `hooks/launch-gate.py` | DELETE | Installer and setup docs, absent from global and repo settings; 1 marker mention. Duplicates launcher capacity checks by parsing arbitrary shell commands. | Not retained |
| `hooks/plan-pick-only.py` | DELETE | Global Bash and repo hooks; 5 marker mentions. A second shell parser guards routing rather than fixing plan-pick. The supported launch path stays plan-pick --run. | Not retained |
| `hooks/reconcile-auto.py` | DELETE | Installer and sync docs, no global/repo Stop hook. 707 recent state files include lease-owned records, not proof this hook ran. Lease start/end and board-drain/watch already own sync. | Not retained |
| `hooks/repo-tidy-stop` | DELETE | Installer and optional skill snippet; no global/repo hook and 0 recent stop logs/stamps. Detached turn-end cleanup duplicates explicit post-merge cleanup. | Not retained |
| `hooks/skill-update.py` | DELETE | Global prompt and repo hook; 67 recent state files, 3 reload-marker mentions. A prompt mutates the checkout used by every chat. Update explicitly, outside another chat's turn. | Not retained |
| `hooks/subagent_call.py` | KEEP | pacer-guard imports it; CI pacer-check imports that guard. No direct command mentions is expected for an imported parser. Agent identity is legitimate external input, not a failure to patch. | principle-boundary-discipline |
| `hooks/valentin_mode_loaded.py` | KEEP | long-chat and pacer import it; long-chat is globally wired. 15 command mentions. Parses explicit opt-in at the harness boundary; removing lane hooks does not remove these callers. | principle-boundary-discipline |
| `scripts/skill-check-nightly` | DELETE | Only tests refer to it; no repo workflow or install entry. 6 recent skill-check state files do not identify the wrapper as their writer. CI owns changed-skill lint; the local reader remains callable. | Not retained |
| `skills/board-drain/loop-state` | KEEP | drain-check, watch, sync, owners, fleet-report and pacer import/read it. 26 recent state files. Stores this chat's real watcher PID, owner and heartbeat rather than a central chat controller. | poteto-mode |
| `skills/board-drain/watch` | KEEP | board-drain skill starts a tracked job; 292 command mentions and 26 recent shared loop records. Waits outside the model, syncs its own view and exits on change or heartbeat. | poteto-mode |
| `skills/hypertask/scripts/blocker-sweep.py` | DELETE | Only ticket docs and tests call it; 3 command mentions, none proves execution. Duplicates waiting-ticket reads in board-drain, uses an obsolete comments command and scans whole boards. | Not retained |
| `skills/hypertask/scripts/ticket-lint` | KEEP | Ticket-writing reference and regression tests; 371 command mentions. Rejects repeated design-pick and secret-paste asks at the write boundary; tests retain real past asks. | correct |
| `skills/join-slack/scripts/fleet-slack-doctor` | DELETE | One skill instruction, no hooks/CI/setup caller; 0 command mentions and no owned state. Unused whole-fleet audit. The skill checks only its own delivery row directly. | Not retained |
| `skills/ratstack-transition/scripts/rat-diff` | DELETE | One skill instruction, no hooks/CI/setup caller; 0 command mentions and 0 recent cache files. Unused hard-coded stack catalog. Read the pinned template rather than maintain another catalog. | Not retained |
| `skills/responsive-mode/reply-check.py` | KEEP | responsive-mode frontmatter and context.py; shared transcript reader for no-bare-ids. 229 result entries mention its marker. This chat's unresolved reply correction has no replacement owner; boundary check names the fix. | correct |
| `skills/valentin-mode/context.py` | KEEP | valentin-mode PreToolUse frontmatter; 15 recent injection markers. Fixes the skipped shell-expansion premise by delivering rules through the harness, without relying on the model to fetch them. | correct |
| `skills/valentin-mode/version.sh` | KEEP | context.py and fleet-report execute it; 123 command mentions. Computes loaded and known-main revisions from git, not a model's claim. Removed the promise of automatic updates. | principle-prove-it-works |
| `skills/vps-tidy/vps-tidy` | DELETE | Installer and skill, no repo timer; 21 recent state files. Host-wide scans can close private tmux servers and kill processes without ticket ownership. Fix resource lifetime in the job owner; do not add another scavenger. | Not retained |
| `tools/gh-wrapper/gh` | KEEP | Deployed /usr/bin/gh copy documented; wait-checks calls it, callers import gh_get. 6638 recent log/cache files. Handles quotas, cache, credential separation and rate-limit errors at the real API boundary. | principle-boundary-discipline |
| `tools/gh-wrapper/wait-checks` | KEEP | GitHub usage docs and chat setup; 52 command mentions. One tracked CI wait, 60-second floor and 30-minute cap. No messages to, or actions for, other chats. | poteto-mode |

## Sources and choices

- `principle-fix-root-causes`: keep selection in plan-pick, API limits in the wrapper, sync in work lifecycle events, and resource lifetime in each job owner.
- `principle-attack-the-premise`: the premise that more external parsers and scavengers make chats reliable is contradicted by existing owners doing the same job. The rule-delivery hook instead removes the skipped-load premise.
- `principle-subtract-before-you-add`: delete unused catalogs and duplicate automatic guards rather than rebrand them with a generic source.
- `principle-migrate-callers-then-delete-legacy-apis`: remove implementations, mixed-test cases, setup hooks, verifier fixtures and obsolete cleanup plans in the same change. The installer retains names only as retirement data to remove old symlinks, not executable wiring.
- `poteto-mode`, autonomous-run step 2: an event gets an outside-model watcher plus a time-based fallback. This directly covers board-drain/watch, its loop-state, and this PR's wait-checks.
- `principle-boundary-discipline`: parse harness opt-in and agent identity once at hook entry; handle shared GitHub limits where requests cross the API boundary. The imported readers stay because remaining long-chat and pacing callers need them.
- `correct`: repeated operator corrections become boundary checks naming the fix. ticket-lint and reply-check still guard unresolved writing mistakes. context.py fixes rule delivery structurally, not by another reminder to run a shell line. Existing regression cases exercise these rules.
- `principle-prove-it-works`: version.sh reads the installed checkout's git history for context and fleet-report. It no longer promises a ten-minute self-update after deleting the updater.

All named sources exist under the installed pstack 0.15.46 skills directory. No retained entry is justified only by usefulness. No unsourced or expiry escape hatch remains in the registry parser.

## Migration and verification

The repository settings no longer register deleted hooks. Install removes old symlinks but preserves real files and does not edit settings. After merge, remove retired hook entries from the installed global/repo settings without touching unrelated hooks; do not deploy an unmerged worktree to every chat. Existing lease status paths remain data owned by the lease and session-login reader, not a legacy executable API.

Full tests run on GitHub-hosted runners with `timeout 900 python3 -m unittest discover -s tests`. Skill lint runs exactly as `.github/workflows/skill-lint.yml` specifies, using its pinned script, pstack and catalog and checking the merge-result tree. Focused local tests cover only the changed registry, installer and surviving callers.

Worker limits: no board login was supplied, so ticket updates belong to the orchestrator. The requested shared worker-brief file is absent from this checkout. The worker's capacity command returned exit 1 without output. No extra worker or local full suite was started.
