# Verification by the book: what pstack actually requires

Source: `~/.claude/plugins/cache/cursor-plugins/pstack/0.15.43` (pstack 0.15.43). Paths are relative to that root.
Ticket https://app.hypertask.ai/detail/project-2060/2568 returns HTTP 307 (login redirect), so it was unreadable.
Every quote is verbatim. "Artifact" lines are my reading, not pstack text.

## 1. Agent drives the real app
Defined by `skills/create-verification-skill/SKILL.md:11`
> Every serious project needs a scripted way to drive the real app and prove behavior: launch it, exercise a feature the way a user would, and capture evidence.

Same file, `:27`
> Write `.cursor/skills/verify-<app>/SKILL.md` with YAML frontmatter (`name: verify-<app>` and a `description` that names the app, the surface, and when to reach for it — without frontmatter the skill never registers) and these sections, each grounded in what the interview actually found (no placeholders left):

Required sections, `:29-34`: `**Launch:**`, `**Doctor:**`, `**Drive:**`, `**Evidence:**`, `**Cleanup:**`, `**Helpers:**`.
Launch must reach a usable state from an empty data dir (`:29`). Doctor is "one read-only check" (`:30`).

`skills/principle-prove-it-works/SKILL.md:9`
> Verify every output by checking the real thing directly: run the feature, read the actual value, inspect the diff. Proxies (file mtimes, self-reports, cached output, "it compiles") do not count.

Artifact: `.cursor/skills/verify-<app>/SKILL.md` with `name: verify-<app>` and the six sections.
Status: DEFINED. The harness itself (`control-ui`, `control-cli`) is only referenced by pstack
(`skills/poteto-mode/playbooks/shipping.md:5` names them "from `cursor-team-kit`") and lives in
another plugin, so the control CLI is NOT IN PSTACK.

## 2. Human is not the verifier
`docs/guide/06-verify-and-ship.md:5`
> Verification is the slowest step in most agent work, because it's the step that usually waits on a human. Make the agent able to do it, and you stop being the bottleneck. Skip it, and running more agents only gets you more unchecked work to review.

`skills/poteto-mode/SKILL.md:106`
> Never hand the human a check you could run.

`skills/poteto-mode/worker.md:7`
> Never call a tool that shows a person a question. Make any choice you can undo, then say what you chose and why.

`skills/poteto-mode/playbooks/bug-fix.md:7`
> Reproduce it yourself on the matching surface via the control skill (Non-negotiables), even when a debug or instrumentation protocol says to ask the user to reproduce. Ask the user only with a stated, specific reason the control surface cannot reach the target, and only after driving it as far as it goes.

`skills/maintain-verification-skill/SKILL.md:35`
> The coordinator owns all driving

Artifact: no human step in the verify loop; only "inconclusive" or a named blocker leaves the agent's hands. Status: DEFINED.

## 3. Feature map, and what "complete" means
`skills/create-verification-skill/SKILL.md:38`
> Create `.cursor/skills/verify-<app>/features/README.md` plus one file per user-facing feature you can identify (aim for the top 3-5 to start, from routes, commands, menus, or docs).
> The four H2s are `Sub-features`, `How to get to it (user POV)`, `Driving it with <harness>`, and `Gotchas`.
> The map is the repo's maintained verification source; a proof that drives one convenient entry point is incomplete when the map lists others.
> Never weaken the journey to make it pass.

`skills/create-verification-skill/references/feature-map-example/README.md:35`
> Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order.

Same example, `:31`
> Do not report a skipped entry point as verified through a different path.

`skills/create-verification-skill/SKILL.md:42` (how much one pass must cover)
> Run its own instructions end to end once: launch, doctor, drive ONE mapped feature (one is enough; the map exists so later runs can cover the rest), capture evidence, clean up.

Artifact: `features/README.md` (H1, index, preconditions, proof and skip reporting) plus one
`features/<feature>.md` per feature, H1, one paragraph, exactly four H2s.
Status: DEFINED. "Complete" means every entry point the map lists was driven. 3-5 is a seed target.

## 4. Reproduce the bug first
`skills/poteto-mode/playbooks/bug-fix.md:7`
> If it won't reproduce directly, synthesize the trigger, tighten conditions, or instrument until it fires.

Same file, `:5`
> Be scientific. Every shipped line traces to runtime evidence. Belt-and-suspenders that "might help" is a hypothesis, not a fix. It does not ship.

Same file, `:10`
> Verify on the same surface. The original repro now passes. "Inconclusive" or wrong-surface is not a pass. Flag it.

Artifact: a repro recipe or command that fails on the base commit, its output in the PR
`## Verification`, plus binary-search or instrumentation evidence. Status: DEFINED.

## 5. Failing test first
`skills/poteto-mode/playbooks/bug-fix.md:11`
> Stage the commits so the failing repro lands before the fix in git history. See the **tdd** skill for the failing-test-first cadence when the bug has a cheap local test path. Skip it when the test would be expensive, integration-heavy, or unclear.

`skills/tdd/SKILL.md:17-18`
> **Write the failing test first.** Add the smallest focused test that would have caught the bug.
> **Run the new test before fixing.** Confirm it fails for the intended reason.

`skills/tdd/SKILL.md:42`
> If failing-before evidence could not be demonstrated, state why and describe the closest regression check used instead.

`skills/poteto-mode/playbooks/bug-fix.md:15`
> Paste failing-then-passing repro output verbatim.

Artifact: repro/test commit first, fix second; PR body quoting both runs, or a stated reason plus the substitute check.
Status: DEFINED, conditional. Skipping the new test is allowed, skipping the failing-first evidence is not.

## 6. Agents try to break it
`skills/interrogate/SKILL.md:11`
> Adversaries try to break a change or a design. A finding survives only when a run proves it. Report the findings. Do not apply fixes.

Same file, `:21`
> Break this change. Prove each finding with a run against the real code, such as a failing test, a repro script, or command output that shows the wrong behavior.

`skills/create-formal-verification-skill/SKILL.md:26`
> **Able to fail.** A check that you have never seen fail proves nothing. Show each property failing on a broken variant of the code it guards, such as a removed check or a reordered step.

Only fuzzing line, `docs/guide/06-verify-and-ship.md:73`
> A swarm of verifiers also confirms a perf win over a big enough sample, or fuzzes the app for regressions before a PR ships.

Artifact: an `/interrogate` report with Findings (command, output, how it breaks intent) and a Dropped count.
Status: PARTLY DEFINED. Adversarial review is its own skill and every check must be shown failing, but
"attack the shipped app" is no step in Bug fix, Feature, Autopilot-full or Shipping. `playbooks/feature.md:7` makes it opt-in: "If the design is contested, `interrogate` before shipping."

## 7. Tests or evals for the verify skill
`skills/create-verification-skill/SKILL.md:42`
> A generated skill that was never executed is a draft, not a deliverable.

`skills/create-formal-verification-skill/SKILL.md:41`
> Follow the generated skill once, as the next agent would, on a scratch change that breaks the property in the real code. It must catch the break. ... A verify skill that was never run is a draft.

`skills/maintain-verification-skill/SKILL.md:11`
> The unit of rigor is the feature, not every sentence: cover every feature file from source and exercise every feature live, without terminalising every bullet.

Same file, `:29-31` (index hygiene, source wave)
> Read the feature map README and glob its sibling files. Fix missing, extra, duplicate, or dead entries. ... One read-only subagent per feature file, launched concurrently. ... Children never drive the app and never edit files.

Closest artifact: a documented one-time end-to-end run (launch, doctor, one feature, evidence, cleanup,
evidence survives), plus a `/maintain-verification-skill` pass with outcome `clean` / `changed` / `blocked` (`:17-19`).
Status: NOT IN PSTACK as a test suite or eval. No test file, no eval harness, no regression suite for the
skill itself. `skills/poteto-mode/playbooks/eval.md:17` defines an eval as a blinded model bake-off
("**Frame.** State what variant is under test and what behavior counts as success."), not a verify-skill test.
The substitute is run-it-once-by-hand plus a periodic live maintenance pass.

## 8. Hard rules enforced in checks
`skills/correct/SKILL.md:19-22`
> 1. **Eliminate it with architecture.** Give each piece of state one owner and each task one supported way. Hide internals so the wrong import fails.
> 2. **Enforce it with types so the bad state can't be written.** If bad code still compiles, add a lint or CI check whose error names the file, type, or function to use instead.
> 3. **Test the behavior.** Fix or delete any test that still passes when the behavior it checks breaks, or that fails when only the internals change.
> 4. **Write docs or agent rules last, only for judgment calls.** Nothing fails when an agent skips them.

Same file, `:15` and `:26`
> A class counts once it has happened twice.
> Prove each new check fails on a real past mistake. Run the same command locally and in CI. Exceptions go on the offending line with a reason, an expiry date, and a human's approval.

Same file, `:30`
> Last, keep a table in the agent instruction file that pairs each rule with what enforces it. When the operator corrects you, fix the mistake and add the rule. If the rule was already there and nothing enforces it, that's a repeat, so fix it at the highest level in the same change. Drop a rule once its mistake can't happen.

Artifact: a rule table in `AGENTS.md` / `CLAUDE.md` pairing each rule with its enforcer (architecture, type,
lint, test, CI), the enforcer run locally and in CI and seen failing on a past mistake.
Status: DEFINED. A prose rule with no enforcer is pstack's definition of a repeat defect, not a rule.

## 9. Auto-merge earned (trust ladder)
Nearest ladder, `docs/guide/07-overnight.md:9-16`
> A loop you don't trust just produces unchecked work faster, and the mess compounds with every iteration. Before you leave one running, check that it has earned it:
> - You've done the task once by hand, or watched an agent do it, so you know what good looks like.
> - The agent has the tools and signals you'd use yourself: the verification skill, the profiler, the logs.
> - Every stage proves its work and can stop the line when the work misses the bar.
> - You've read a few transcripts and turned the repeated failures into tools, skills, or checks.
> Make the loop autonomous only after all four hold. Until then, run it while you watch.

Merge authority, `skills/poteto-mode/playbooks/shipping.md:5`
> Only a verdict from an agent that did not write the code counts, because an author checks what it meant to build. Green CI and an approving bot review are not verdicts, because neither runs the change as a user would.

`skills/poteto-mode/playbooks/autopilot-full.md:17`
> Green CI alone never authorizes a merge.

`skills/poteto-mode/playbooks/shipping.md:8`
> Arm `--auto` (Origin merge-when-ready or GitHub auto-merge) only on a PR whose verdict covers its current head, because it lands whatever head is ready.

`skills/poteto-mode/playbooks/autopilot-full.md:5`
> A verdict covers one patch and green CI covers one head.

`skills/poteto-mode/playbooks/babysit.md:10`
> Owner approval is a wait. Babysitting never authorizes merging.

Artifact for what pstack defines: a verifier identity separate from the author, a posted `PASS` / `PASS+NOTES`
/ `FAIL` verdict on the PR, a `git patch-id` match between verdict SHA and merge head, `--auto` armed only
after that, and evidence the four `/loop` conditions held before autonomy.
Status: NOT IN PSTACK as a graded ladder. Two states only (watched, autonomous), gated by four conditions,
plus per-PR verdict-before-merge. No tiers, no score, and no agent ever earns merge-without-verdict.

## 10. Spend tokens on verifying
`skills/poteto-mode/SKILL.md:98`
> Verification always runs on the `swarm workers` model, `claude-opus-5-5-high-fast` by default.

`skills/poteto-help/SKILL.md:46`
> If cost is the worry, say where the tokens go and how to spend fewer. pstack spends extra tokens on subagents and review panels. Rerun `/setup-pstack` and pick a smaller budget or cheaper models.

`skills/poteto-mode/playbooks/autopilot-full.md:14`
> A full swarm runs once, at the code-ready head. Another full swarm runs only for new behavior, a redesign, or a large new diff. A rebase, a merge-conflict resolution, or a minor fix gets a single verifier at the new head, and a wording-only change gets none.

Status: NOT IN PSTACK as a rule. pstack fixes which model verifies and how much swarm a change earns, exposes
a budget dial, and tells you how to lower it. It never says spend generously on verification.

## What a repo must contain
1. `.cursor/skills/verify-<app>/SKILL.md`, frontmatter `name: verify-<app>`, sections Launch, Doctor, Drive, Evidence, Cleanup, Helpers.
2. `features/README.md` plus one file per feature, exactly four H2s in order.
3. A rule table in the agent instruction file pairing each hard rule with its enforcer; enforcer runs locally and in CI and has been seen failing.
4. A PR `## Verification` section with verbatim failing-then-passing output and live proof.
5. Separate verifier identity, a posted verdict on the PR, `--auto` only after a patch-id match.

Mark these NOT IN PSTACK before claiming "by the book": a test suite or eval for the verify skill
itself; adversarial break-it as a required merge step; a graded trust ladder; a rule to spend
more tokens on verification.
