# House audit, 2026-11-24

Valentin's setup should follow Lauren Tan's pstack 1:1. Only a measured inability to use pstack justifies an exception.

**Result: 1 keep, 18 delete, 12 expire 14d.** Twelve entries remain acknowledged violations, not claims that pstack is impossible. Their removal deadline is **2026-12-08**, with filed follow-ups below. The retained Actions transport is conditional on an actual independent user journey; a green check alone never satisfies it.

## Baseline and coordination

- Ticket: https://app.hypertask.ai/detail/project-13556/191. Owner chat: Vstack Maintainer.
- Audited source: `skills/pstack-diff/house.txt` at `a1ab7ec3928c1c3f54c2457bb39b75f1696a0efe`. The kickoff's original 30 became 31 when VSTA-188 added `merge-gate`. Counts above include that added entry. For the original 30, counts are 1 keep, 17 delete, 12 expire.
- Pstack: **0.15.47**, installed at `~/.claude/plugins/cache/cursor-plugins/pstack/0.15.47`, upstream `cursor/plugins@2dd5c0ccc5b207dc23a69759871a35954082cbf7`. `.skill-lint.json` now pins this version, replacing 0.15.43. A newer 0.15.48 appeared during the run; evidence below explicitly selects 0.15.47.
- VSTA-186 already shipped https://github.com/valentinyeo/vstack/pull/344 and https://github.com/valentinyeo/vstack/pull/345. It removed the board-2060 exception and the accidental board-13734 application. It retained a renamed `board-15-live-proof-stage`. This PR does not change its reconcile stage implementation.
- VSTA-187 is Done. Its `stuck` finding catches idle red Checks cards. That does **not** restore the hourly audit of every owner and leaf worker. The remaining cadence removal is https://github.com/valentinyeo/vstack/issues/352.
- VSTA-188 already shipped https://github.com/valentinyeo/vstack/pull/346. Its `skills/board-drain/merge-gate`, drain-check finding, and Shipping bullet remain. Requiring the step-1 verifier implements pstack; it is not a reason to list a permanent exception.

## Stanza decisions

Each row is one baseline stanza. For the renamed board entry, the original id was `board-2060-live-proof-stage`; VSTA-186 owns that deletion. For entries already consistent with pstack, deleting the exception label does not delete the pstack behavior it mistakenly labelled an exception.

| Id | Verdict | Why and change or follow-up |
|---|---|---|
| `pacer-check` | expire 14d | Not impossible: pstack PR headings work here, but removing the shared pacer protocol requires coordinated token-ladder and hook changes (scripts/pacer-check.py, hooks/pacer-guard.py). Follow-up: https://github.com/valentinyeo/vstack/issues/351 (due 2026-12-08). |
| `board-drain-plan-pick-owners` | expire 14d | Not impossible: local worktree owners are supported by pstack docs/harness/claude-code.md, but replacing plan-pick leases and lane-capacity state spans skills/hypertask-work/lease and token-ladder. Follow-up: https://github.com/valentinyeo/vstack/issues/351 (due 2026-12-08). |
| `board-drain-view-watcher-pace` | expire 14d | Not impossible: an hourly audit can run here, but skills/board-drain/watch and loop-state still encode the slower watcher cadence; VSTA-187 only adds the stuck finding. Follow-up: https://github.com/valentinyeo/vstack/issues/352 (due 2026-12-08). |
| `board-drain-keep-loop-empty-todo` | delete | Restored stand-down when delegated work is finished in skills/board-drain/SKILL.md; empty Todo alone is not that condition. |
| `board-15-live-proof-stage` | expire 14d | Not impossible: the production branch now requires pstack-verifier, but board 15 still has no Done stage; migrate with its owner. Follow-up: https://github.com/valentinyeo/vstack/issues/353 (due 2026-12-08). |
| `cloud-agent-offload` | delete | Removed mandatory vendor-cloud offload in skills/cloud-agent/SKILL.md; the supported pstack local-worktree adapter is usable. |
| `cloud-agent-vendor-routing` | expire 14d | Not impossible: the pstack model family can be selected, but removing Codex-only routing requires changing skills/cloud-agent/cloud-agent and token-ladder lane policy together. Follow-up: https://github.com/valentinyeo/vstack/issues/351 (due 2026-12-08). |
| `deep-work-upfront-proof` | delete | Removed mandatory red tests in skills/deep-work/SKILL.md; practical baseline checks and pstack tdd now decide. |
| `deep-work-phase-c-report` | delete | Removed the custom four-part report in skills/deep-work/SKILL.md in favor of autonomous-run's reply contract. |
| `deeper-ask-before-running` | delete | Removed the extra approval question in skills/deeper/SKILL.md; sharpen already ends with the rewritten prompt. |
| `design-lead-mockup-approval` | delete | Removed blanket image approval before reversible implementation and PRs from skills/design-lead-setup/SKILL.md; irreversible writes still pause. |
| `hypertask-tickets-human-lane-pospeak` | delete | Removed the 8/12-word and code/path bans from ticket guidance, ticket-lint and poteto-ticket; restored whole sentences and pstack's 25-word guidance. |
| `hypertask-checkup-plan-pick` | delete | Removed mandatory plan-pick routing from skills/hypertask/references/checkup.md; worker selection belongs to pstack. |
| `join-slack-caveman-voice` | delete | Removed caveman voice from skills/join-slack/SKILL.md; restored unslop whole sentences. |
| `long-chat-auto-handover` | expire 14d | Not impossible: the chat can continue using compaction, but hooks/long-chat.py and skills/long-chat carry a blocking handover protocol requiring a separate lifecycle change. Follow-up: https://github.com/valentinyeo/vstack/issues/354 (due 2026-12-08). |
| `pospeak-caveman` | delete | Removed the caveman override from skills/pospeak/SKILL.md; retained product-owner vocabulary. |
| `pr-housekeeping-one-owner-one-pr` | delete | Removed automatic babysit on PR creation and the blanket second-PR ban from pr-housekeeping and valentin-mode; Autopilot-full still has one owner per PR. |
| `github-actions-verifier` | keep | Cursor Task cloud API is absent in this harness; keep hosted execution only when it actually drives changed behavior parent against head. |
| `merge-gate` | delete | Not a deviation: VSTA-188 enforces shipping step 1 at GitHub; removed only the exception label, retaining its required verifier and drain-check. |
| `uncovered-pass-gate` | delete | Not a deviation: refusing unexercised product files implements shipping step 1; replaced CLAUDE.md's house citation with pstack and retained the proof checker. |
| `ratstack-github-actions-only` | delete | Removed the blanket local-check prohibition in skills/ratstack-transition/SKILL.md; touched-path checks precede push and full CI stays hosted. |
| `repo-tidy-automated-cleanup` | expire 14d | Not impossible: pinned-chat confirmation can precede cleanup, but skills/repo-tidy/repo-tidy and pr-queue currently infer safety from process and lease state rather than the pinned-chat set. Follow-up: https://github.com/valentinyeo/vstack/issues/355 (due 2026-12-08). |
| `responsive-mode-plan-pick-workers` | expire 14d | Not impossible: pstack workers can run here, but skills/responsive-mode and token-ladder share a plan-pick helper eligibility protocol that must be removed together. Follow-up: https://github.com/valentinyeo/vstack/issues/351 (due 2026-12-08). |
| `schneider-german-dashes-colons` | delete | Removed German punctuation exceptions in skills/schneider-deutsch-stil/SKILL.md; unslop rules 13 and 14 apply. |
| `heavy-local-guard` | expire 14d | Not impossible: focused local checks are allowed by the operator and pstack, but hooks/heavy-local-guard.py and scripts/worker-shims still block wider command families across supported clients. Follow-up: https://github.com/valentinyeo/vstack/issues/356 (due 2026-12-08). |
| `vps-state-hold-throttle` | expire 14d | Not impossible: cloud work does not consume local worker capacity, but drain-check and the launchers apply a shared host HOLD policy that needs a local-versus-cloud split. Follow-up: https://github.com/valentinyeo/vstack/issues/356 (due 2026-12-08). |
| `web-writing-bulleted-sequences` | delete | Removed bullet-only sequences in skills/web-writing/SKILL.md; ordered procedures use numbered lists. |
| `zinsser-colons-editorial-guide` | delete | Removed the broad colon permission in skills/zinsser-english-style/SKILL.md; unslop rule 14 applies. |
| `worker-brief-pstack-source` | expire 14d | Not impossible: pstack worker.md alone can carry the brief, but hooks/pstack-source.py, installer registrations and their migration tests enforce the extra source line. Follow-up: https://github.com/valentinyeo/vstack/issues/357 (due 2026-12-08). |
| `book-check` | expire 14d | Not impossible: the pstack short PR body works here, but hooks/book-check.py, installed registrations and tests/test_advisor_migration.py enforce the shared 15-item checklist. Follow-up: https://github.com/valentinyeo/vstack/issues/357 (due 2026-12-08). |
| `server-facts` | delete | Not a deviation: one facts source implements correct's quoted rule; replaced CLAUDE.md's house citation with pstack and retained the facts source. |

## Valentin's question: which valentin-mode lines conflict with pstack?

Line numbers below refer to the audited baseline above. Where the branch corrects a line, its number is unchanged. Quotes are from pinned pstack 0.15.47, not remembered summaries. An added domain rule without a conflicting pstack requirement is not automatically a contradiction.

| Source and conflicting instruction | Pstack quote and source | Result |
|---|---|---|
| `skills/valentin-mode/SKILL.md:25`, poteto-mode runs only when he types it | "Match the task to a playbook and open its steps" (`skills/poteto-mode/SKILL.md:110`) | Removed the additional slash-command prerequisite; follow the matching playbook during work. |
| `skills/valentin-mode/SKILL.md:35-36`, never return a server path and always use a public screenshot URL | "your recommendation, and the scratch path" (`skills/poteto-mode/playbooks/prototype.md:14`) | The absolute path ban can suppress required prototype evidence. The preference for shareable links alone is compatible. This remaining instruction needs narrowing, not publication of private artifacts. |
| `skills/valentin-mode/SKILL.md:39`, every ask becomes a ticket and worker | "The bar in your kickoff is the whole bar. Add no check, gate, sign-off or review round above it." (`skills/poteto-mode/worker.md:4`) | A board record can track work, but an unconditional worker for an answer adds a workflow pstack did not require. Limit it to work that needs an owner. |
| `skills/valentin-mode/SKILL.md:45`, mandatory plan-pick, non-author vendor, Claude helper eligibility, and a parent restricted to briefs and one result line | "Code, prose, and judgment: `claude-opus-5-5-xhigh-fast`." and "You own every subagent's work. Review the diff and write your own summary." (`skills/poteto-mode/SKILL.md:92,100`) | Routing and parent blindness are not impossible to remove. The cross-repo pacer/worker migration expires in 14 days: https://github.com/valentinyeo/vstack/issues/351. Independence means a different agent; the default verifier is not inherently a different family. |
| `skills/valentin-mode/SKILL.md:53`, always keep the board loop armed | "On the operator's go, arm `/loop 1h` to audit until no delegated work is left" (`skills/poteto-mode/playbooks/autopilot-full.md:22`) | Restored the grant and delegated-work lifetime in the skill. The actual watcher cadence still needs issue 352. |
| `skills/valentin-mode/SKILL.md:57`, opening any PR automatically commits its opener to merge; blanket second-PR ban | "Opening a PR does not start a babysit." (`skills/poteto-mode/playbooks/opening-a-pr.md:9`) | Removed the blanket rule here and in pr-housekeeping. Autopilot-full's one owner per PR and step-1 proof remain. VSTA-186 owns the already-shipped proof-before-merge and stale-owner behavior. |
| `skills/valentin-mode/SKILL.md:63`, every check follows Hillclimb | "Match the task to a playbook" (`skills/poteto-mode/SKILL.md:110`) | A metric-search playbook is not the default for every test or verification. Use Shipping for landing and the task's own playbook for checks. |
| `skills/valentin-mode/SKILL.md:65`, unrestricted Actions substitution and mandatory Token Ladder routing for every AI call | "One verifier per PR, each a Cursor cloud agent, runs the change the way a user would" (`skills/poteto-mode/playbooks/shipping.md:5`); "Verification always runs on the `swarm workers` model" (`skills/poteto-mode/SKILL.md:98`) | Narrowed the machine substitution to vstack and actual parent/head driving. Routing must preserve configured pstack role models; the mandatory provider policy is part of issue 351. |
| `skills/valentin-mode/SKILL.md:67`, clear every EXTRA in one PR, including baseline faults | "Report a problem the base already has in one line." (`skills/poteto-mode/worker.md:6`) | Restored changed-path scope and follow-ups for unrelated baseline differences. This audit itself was explicitly requested and is not an unrelated gate. |
| `skills/valentin-mode/SKILL.md:68`, a local HOLD stops everything, including independent cloud work | "Run owners in parallel off trunk, never stacked" (`skills/poteto-mode/playbooks/autopilot-full.md:13`) | Local capacity can constrain local work; it cannot establish that a remote worker is impossible. Split the policies in issue 356. |
| `skills/valentin-mode/SKILL.md:70`, make a private repository public as a billing workaround | "Always pause" for "irreversible writes" (`skills/poteto-mode/SKILL.md:80`) | Removed automatic publication. A privacy disclosure cannot be undone by making the repo private later. Valentin decides publication. |
| `skills/valentin-mode/SKILL.md:72` and `skills/valentin-mode/setup.md:14`, force a fresh-chat handover at the hard context threshold | "This is explicit only. On "keep going", "going to bed, keep going", or "don't stop", do not pause." (`skills/poteto-mode/playbooks/pause-safely.md:3`) | The automatic blocking handover is a live lifecycle change; remove it in issue 354. |
| `skills/valentin-mode/setup.md:15`, Stop waits until a board watcher runs, regardless of delegated work | "audit until no delegated work is left" (`skills/poteto-mode/playbooks/autopilot-full.md:22`); "Stand down at once on the operator's stop." (same file, step 7) | The watcher guard must respect completion and an explicit stop; include this in issue 352. |
| `skills/valentin-mode/setup.md:21`, worker selection belongs to plan-pick and Claude-helper policy | "per-role lines override the defaults below" (`skills/poteto-mode/SKILL.md:90`) | A shared launcher may implement configured models; it may not replace them with a blanket vendor ban. Issue 351 includes this setup text. |
| `skills/valentin-mode/designing.md:3`, never let Valentin choose, and build variants for every design ticket | "let the user pick directions before building. Skip when the direction is set." and "No decision means no prototype. Route to Feature." (`skills/poteto-mode/playbooks/prototype.md:8,7`) | Choose experimentally settled details yourself, but leave genuinely untestable preferences to the operator. Do not impose prototypes on an already-set direction. The separate design-lead skill's approval-before-any-PR rule was removed in this PR. |

`SKILL.md:66` is not a contradiction: it links Shipping and Babysit and names VSTA-188's required verifier. `setup.md:3,13,19,23,25,29-40` mostly describes installation or client capabilities, not replacement shipping rules. `setup.md:5` fails open for missing hooks, so those hooks cannot prove merge coverage; the actual GitHub gate must do that. `designing.md:4` selects specialist skills; no pinned pstack quote requires two taste skills on one step. It must not suppress pstack's architect or verification triggers.

These additional text findings do not turn into invented impossibility claims. They are visible remaining violations, distinct from the 31 stanza verdicts. Follow-up https://github.com/valentinyeo/vstack/issues/359 covers the remaining unlisted text findings, due 2026-12-08.

## Would today's checks catch every merge without step-1 proof?

**No.** A required verifier check is now present, but check presence is weaker than proof that the changed behavior was exercised.

### Measured server-side protection

On 2026-11-24 the following read-only GitHub calls returned:

```text
gh api repos/valentinyeo/vstack/branches/main/protection
404 Branch not protected

gh api repos/valentinyeo/vstack/rulesets/27993086
name: merge gate
enforcement: active
ref_name.include: [~DEFAULT_BRANCH]
bypass_actors: []
required_status_checks: [{context: verifier}]
strict_required_status_checks_policy: false

gh api repos/hypertask-ai/hypertask/rules/branches/production
required_status_checks: [{context: pstack-verifier, integration_id: 5264284}]
strict_required_status_checks_policy: false
```

The classic-protection 404 does **not** mean vstack is unprotected. Its active ruleset requires `verifier` for main. Board 15's old no-verifier rationale is also stale: its product branch has a required verifier now. That strengthens the case for removing its post-merge stage.

### Every requested merge path

| Entry point | What stops a pending or failed verifier on vstack main? | What stops a green or skipped check without a real user journey? |
|---|---|---|
| `gh pr merge` from a chat | GitHub ruleset 27993086's required `verifier`; a local hook is not the authority. No ruleset bypass actors are configured. | No complete check. The workflow accepts the weak evidence described below. |
| `gh pr merge` from a worker | The same GitHub required check, regardless of whether Claude hooks run. | The same gap; changing the launcher does not add proof validation. |
| Vendor cloud agent merges | The same ruleset when it targets this repo's main. Cloud agents do not inherit this laptop's hooks. | The same gap. Fork-origin PRs additionally skip this verifier job by its condition. |
| GitHub UI merge button | The same server-side required check; no terminal hooks run. | The same gap; a green status is what the UI sees. |
| Auto-merge or queueing | The same server-side requirement at the head GitHub lands. Pstack separately requires a current-head verdict before arming auto-merge. | No check verifies when auto-merge was armed or that a green result contains parent/head user proof. Strict-base mode is false, and no queue-specific proof was demonstrated. |

The gate applies to the default branch named by the ruleset, not every arbitrary base branch. A PR targeting an unprotected branch does not gain protection merely because the board is watched. GitHub also permits maintainers with settings rights to change the rule; this audit did not change permissions or attempt a bypass.

### Proven acceptance gap and remaining limits

1. `.github/workflows/pstack-sources.yml:25` skips the verifier for PR heads from another repository. GitHub treats a skipped job as successful for required-check purposes. Thus the existence of a required context does not prove the job ran. See GitHub's [job conditions documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-jobs-with-conditions).
2. `.github/workflows/pstack-sources.yml:181` only requires **some** completed `bash` tool call. It does not require a successful app launch, the control skill, or matching parent/head journeys. The prompt at lines 110-113 asks for them, but the assertion does not validate them.
3. A local replay used that exact `Read verifier answer` Python block, a tool event for `true`, and the final answer `PASS` followed by `No app journey was executed.` The block exited **0**. Passing its emitted `verdict.md` through the real `scripts/verdict.py` also printed **PASS** and exited **0**. This proves the evidence parser can accept no-journey input; it does not claim the actual independent verifier always behaves that way.
4. `scripts/verdict.py:148-156` invokes `uncovered_gate` only if a selection file exists. A missing selection does not fail. The existing uncovered-file checker remains useful and is retained; it cannot certify omitted evidence.
5. The workflow and final verdict parser come from the PR head. The model runner comes from the base, which is a useful boundary, but it does not prevent a PR changing its own proof instructions or final parser. The vstack rule also lacks an integration binding and does not require a fresh base. These are coverage risks, not claims that every current PR is unproven.
6. VSTA-188's `merge-gate` checks required context names, not the journey artifacts. `gate_findings` at `skills/board-drain/merge-gate:245-254` returns no finding for some unreadable API states. A passing drain-check is therefore not proof of complete protection across every shipping repository. No fleet-wide protection claim was measured here.

Follow-up https://github.com/valentinyeo/vstack/issues/358 owns these remaining proof gaps **after** VSTA-188, without duplicating its merge-gate tool. Until those gaps close, the owner must inspect actual independent parent/head user proof, not infer it from green CI.

## Verification and evidence

The scope regression drives the real reconcile `target` interface across boards 15, 2060, 13556, 13734, and an unknown runtime board, varying columns, merged PASS/no-PASS, owner presence, blocked/waiting, verification labels and unavailable worker lanes. Every tagged path must be exercised. Missing or narrowed board scope fails. Replacing the board-15 classifier with the historical all-board behavior fails on board 13734. This is a test of emitted stages, not a substring count in the stage implementation. The check starts with VSTA-186's stage table; it does not claim runtime enforcement for every arbitrary tagged path in the repository.

The branch's tests were copied into a clean `git archive origin/main` tree, with no branch production changes copied, and run there first. All local tests used the system Python because the worker command shim blocked even the operator-approved single-file commands. Every test command was bounded by `timeout 300`. No full suite, build, shared install, deployment, merge or live data mutation ran on this server.

| Touched test file | Main with the new tests | Branch |
|---|---|---|
| `tests/test_house_list.py` | 12 tests, 5 failures; missing metadata and scope | 12 tests, PASS |
| `tests/test_ticket_question_rules.py` | 12 tests, 3 failures; old sentence/path bans | 12 tests, PASS |
| `tests/test_pstack_sources.py` | 2 tests, 1 failure; stale all-board verifier instruction | 2 tests, PASS |

Reproduce the focused branch checks with:

```bash
export PSTACK_PINNED_DIR="$HOME/.claude/plugins/cache/cursor-plugins/pstack/0.15.47"
timeout 300 /usr/bin/python3 -m unittest discover -s tests -p test_house_list.py -v
timeout 300 /usr/bin/python3 -m unittest discover -s tests -p test_ticket_question_rules.py -v
timeout 300 /usr/bin/python3 -m unittest discover -s tests -p test_pstack_sources.py -v
```

`pstack-diff --base origin/main` exited **0**. A second run with an isolated version-directory symlink selected exactly 0.15.47 and also exited **0**. This exit status proves no new classified EXTRA; `--base` does not promise complete semantic parity or reject every baseline GAP. `git diff --check` passed.

Principles used: Laziness Protocol kept the stage implementation and existing pstack-aligned proof checks; Test Behavior, Not Implementation made the scope test observe actual reconcile decisions, including a deliberate historical leak.

### Faults and filing

The PATH Hypertask shim refused board access. The native CLI verified the worker's own Vstack Maintainer read identity but refused helper writes. The owner chat was notified through session mail before a workaround. The seven linked repository issues file the required stanza removals rather than inventing Hypertask ticket numbers; the owner can link them to its own board. The proof-gap and remaining-text issues are separate. No token was printed or changed.

GitHub Actions runs the full suite and independent verifier on the PR head. The PR's Checks tab is the authoritative final result; this report does not predeclare a future CI run green.
