# How the chats on this server use pstack verification

Ticket VSTA-141. Read-only research. Window: PRs merged 2026-11-20 to 2026-11-23 13:00 UTC (72h).
Rule being measured: `create-verification-skill`, `maintain-verification-skill`, and Shipping step 1
(one verifier per PR, not the author, running the change as a user would, posting PASS / PASS+NOTES / FAIL
for the PR's current head, only a verdict on the merged head counting).

## Method

- 31 live chats, 12 distinct git repos, 7 repos with merged PRs in the window.
- Merged PR counts in the window: chromescribe 8, claude-cro 3, postbox 6, hypertask 26, vstack 116,
  multiprompt 112, multiprompt-android 64, faceless-channels / clickshades-theme / triage /
  upwork-auto-applier 0.
- Per the brief, repos over 15 merged PRs were sampled to the 15 newest: 77 PRs examined in total.
- Per PR: comment history, commit list, check rollup, body, and changed files.
- Transcripts were grepped (not loaded) only to see whether a chat loaded its verify skill or drove the app.

## Counts (77 PRs)

| Repo | merged (72h) | sampled | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| valentinyeo/chromescribe | 8 | 8 | 8 | 0 | 0 | 0 | 0 |
| valentinyeo/claude-cro | 3 | 3 | 1 | 2 | 0 | 1 | 0 |
| valentinyeo/vstack | 116 | 15 | 12 | 3 | 0 | 12 | 2 |
| hypertask-ai/hypertask | 26 | 15 | 14 | 1 | 0 | 13 | 4 |
| valentinyeo/multiprompt-android | 64 | 15 | 15 | 0 | 0 | 10 | 5 |
| valentinyeo/multiprompt | 112 | 15 | 15 | 0 | 0 | 7 | 4 |
| valentinyeo/postbox | 6 | 6 | 6 | 0 | 0 | 5 | 1 |
| **total** | **335** | **77** | **71** | **6** | **0** | **48** | **17** |

A and B split the sample. C, D and E overlap both: a PR can merge without a timely verdict and also
carry test-only evidence, or add a gate and still get no user-path proof.

A verdict before the merge, on the merged head, happened for 71 of 77 PRs. That part of the rule holds in
every repo except claude-cro and the three vstack cases below. What fails is D: most verdicts are a
transcript of unit tests, or a generic "appearance" journey that never touches the changed surface.

Two shapes dominate, and neither is "one Cursor cloud agent per PR":

- **Repo workflow verifier.** chromescribe, multiprompt, multiprompt-android, postbox and hypertask post
  verdicts as `github-actions` from a repo workflow (`pstack-verifier.yml`, `verify.yml`,
  `tools/verify-wazig`). It is not the author, so C is 0 everywhere, but it is a pipeline, not an agent
  that drove the change.
- **Judge reading text.** multiprompt verdicts say so in their own words: "The ladder-call judge read text
  evidence only, so no screenshot was read for this verdict."

## 1. Tables per chat

Chat names and folders from a local roster file kept outside the repo. Where several chats share a repo, PR-level
attribution to an individual chat was not reliable from transcripts (see Limits), so those rows report the
shared repo and name the chats.

### Chromescribe
repo `valentinyeo/chromescribe`

| chat | repo | PRs merged | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| Chromescribe | valentinyeo/chromescribe | 8 | 8 | 0 | 0 | 0 | 0 |

verify skill: `.claude/skills/verify-chromescribe` with `features/` (20 files at HEAD), plus `verify-queue-formal`.
Used by the verifier: yes. Verdicts cite `cs-verify select`, `launch`, `doctor`, `journey <name>` and PNG
proof paths.

### Claude CRO
repo `valentinyeo/claude-cro`

| chat | repo | PRs merged | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| Claude CRO | valentinyeo/claude-cro | 3 | 1 | 2 | 0 | 1 | 0 |

verify skill: none in the repo, no `features/`. The one verdict (#25) is a code reading by a named
verifier model, not a run.

### vstack (5 chats)
repo `valentinyeo/vstack` — chats: Deepseek Price Researcher, Hypertask Reconciler, Long Session Clear,
Pstack Verification Compliance, Responsive Mode, VPS Admin, Vstack Maintainer

| chat | repo | PRs merged | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| shared vstack repo (sample) | valentinyeo/vstack | 116 (15 examined) | 12 | 3 | 0 | 12 | 2 |

verify skills at HEAD: 9 (`verify-valentin-mode`, `verify-hypertask`, `verify-reconcile`,
`verify-board-drain`, `verify-repo-tidy`, `verify-responsive-mode`, `verify-test-timeout`,
`verify-vps-state`, `verify-valentin-subskills`). `verify-valentin-mode` has `features/` and `grade.py`.
Used by the verifier: almost never. 12 of 15 verdicts are "## Commands and outputs" listings of
`python3 -m unittest` runs.

### hypertask (3 chats)
repo `hypertask-ai/hypertask` — chats: HT Mistake Proofing, HT Product Lead, HT Security

| chat | repo | PRs merged | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| shared hypertask repo (sample) | hypertask-ai/hypertask | 26 (15 examined) | 14 | 1 | 0 | 13 | 4 |

verify skills: `verify-hypertask`, `verify-qa` (feature map at `.claude/skills/verify-qa/reference/feature-map/`,
INDEX plus per-area files), `verify-design` (6 feature files), `verify-visual`, `verify-on-phone`.
Used by the verifier: partly. The verifier names areas (`area:reports-agent-doors [desktop]`) and drove
them on #3751, but 14 of 15 verdicts read `no app path: no user path` or `non-app files only`.

### multiprompt (5 chats)
repo `valentinyeo/multiprompt` — chats: Multi Bot, Multi Bot Bugs, Multi Bot Features,
Multi Bot Verification, Seamless Session Transitioning

| chat | repo | PRs merged | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| Multi Bot Bugs (transcript-linked) | valentinyeo/multiprompt | PRs #1240, 1249, 1251, 1254, 1255, 1263, 1265, 1269 | 8 | 0 | 0 | 4 | 3 |
| Multi Bot Verification (transcript-linked) | valentinyeo/multiprompt | PRs #1249, 1255 | 2 | 0 | 0 | 1 | 0 |
| shared multiprompt repo (sample) | valentinyeo/multiprompt | 112 (15 examined) | 15 | 0 | 0 | 7 | 4 |

verify skills: `verify-multiprompt` with `features/` (100 files), plus `verify-chat-delivery-formal`,
`verify-chat-still`, `verify-hosted-chat-reads`, `verify-switch-ai-formal`.
Used by the verifier: yes, and the verdicts name the evidence file (`evidence/verify-appearance/result.json`).
The gap is selection: "selection.json lists only the appearance feature".

### multiprompt-android (3 chats)
repo `valentinyeo/multiprompt-android` — chats: Multi Bot Android Bugs, Multi Bot Android Features,
Multi Bot Android Verifiy

| chat | repo | PRs merged | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| Multi Bot Android Bugs (transcript-linked) | valentinyeo/multiprompt-android | PRs #519, 520, 521, 522, 523, 528, 529, 532, 534, 535 | 10 | 0 | 0 | 7 | 4 |
| Multi Bot Android Verify (transcript-linked) | valentinyeo/multiprompt-android | PRs #525, 530, 531 | 3 | 0 | 0 | 2 | 2 |
| shared multiprompt-android repo (sample) | valentinyeo/multiprompt-android | 64 (15 examined) | 15 | 0 | 0 | 10 | 5 |

verify skill: `verify-multiprompt-android` with `features/` (28 files).
Used by the verifier: yes when a journey runs (`chat-table.md`, `session-pins.md`, seven journeys on #530).

### Postbox (2 chats)
repo `valentinyeo/postbox` — chats: Postbox, Postbox Verify & CI

| chat | repo | PRs merged | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| Multi Bot Bugs (transcript-linked) | valentinyeo/postbox | PRs #554, 559 | 2 | 0 | 0 | 1 | 0 |
| Multi Bot Verification (transcript-linked) | valentinyeo/postbox | PRs #562, 563 | 2 | 0 | 0 | 2 | 0 |
| shared postbox repo (sample) | valentinyeo/postbox | 6 | 6 | 0 | 0 | 5 | 1 |

verify skills: `verify-wazig` with `features/` (59 files), plus `verify-send-queue`.
Used by the verifier: the verdict names a judge model and a run URL but no journey in 4 of 6 cases.

### No merged PRs in the window
Faceless Channels, Last 30 Days Research, Matt Live Stream, Poteto, Token Ladder, Triage LC, Upwork,
term-37c2ecd, projects-75. Their repos are `faceless-channels`, `clickshades-theme`, `triage`,
`upwork-auto-applier` (0 merged PRs each) and `software-factory` / `last30days` (not git checkouts).

### Commits straight to the default branch
No direct pushes found. Every first-parent commit in the window on `multiprompt` `master`,
`multiprompt-android` `main`, `postbox` `main`, `vstack` `main`, `chromescribe` `master`,
`claude-cro` `master` belongs to a merged PR, including the ones whose message has no `(#N)` suffix
(checked 4 of them through `gh api repos/<r>/commits/<sha>/pulls`: all rebase-merged PRs, e.g.
`multiprompt ab590b3d2` is #1251). So no solo-dev green-push release ran in this window, and no
verification question arises for that path.

## 2. Flags

### B: merged without a verdict, a FAIL verdict, or a verdict for an older head

- https://github.com/valentinyeo/vstack/pull/282 — merged with **no comments at all**, so no verdict for
  head `3777ff4` (revert of a board-sync change).
- https://github.com/valentinyeo/vstack/pull/270 — the only verdict, "PASS", was posted at 21:00:39Z
  after the merge at 20:57:22Z.
- https://github.com/valentinyeo/vstack/pull/271 — the only verdict, "PASS+NOTES", was posted at
  21:04:39Z after the merge at 21:00:02Z.
- https://github.com/hypertask-ai/hypertask/pull/3751 — merged 7 hours after a **FAIL** on its own head:
  "FAIL: area:reports-agent-doors [desktop]: failed at step 2 area:reports-agent-doors [phone]: failed at
  step 2". No later verdict exists.
- https://github.com/valentinyeo/claude-cro/pull/23 — no verdict comment, merged 2026-11-20T14:40Z.
- https://github.com/valentinyeo/claude-cro/pull/24 — no verdict comment, merged 2026-11-20T14:53Z.

### D: no user-path evidence in the verdict

vstack, 12 PRs where the verdict is a test transcript:

- https://github.com/valentinyeo/vstack/pull/288 — body opens "## Commands and outputs (verbatim)" with
  `python3 -m unittest discover -s tests`; no chat session, hook run or CLI journey was driven.
- https://github.com/valentinyeo/vstack/pull/286 — same shape: `python3 -m unittest tests.test_cloud_agent`.
- https://github.com/valentinyeo/vstack/pull/284 — "Base 1101 tests pass, head 1119 pass"; no surface.
- https://github.com/valentinyeo/vstack/pull/280 — verdict judges a one-line `CLAUDE.md` diff, no run.
- https://github.com/valentinyeo/vstack/pull/277 — "## Diff judged ... Shape matches
  `skills/hypertask/references/tickets.md` parts. Good." A file was read, not a command run.
- Also: #279, #278, #276, #274, #272, #271, #270 (same unit-test-plus-diff evidence pattern).
- https://github.com/valentinyeo/vstack/pull/269 is borderline: it ran `grade.py` on fixtures under
  `.claude/skills/verify-valentin-mode/`, close to the real surface but not a live chat.

hypertask, 14 PRs whose verdict states no user path was exercised:

- https://github.com/hypertask-ai/hypertask/pull/3803 — "PASS+NOTES: no app path: no user path Run time
  2 min", on a change to the local board launcher.
- https://github.com/hypertask-ai/hypertask/pull/3794 — same wording, 1 minute run.
- https://github.com/hypertask-ai/hypertask/pull/3761 — same wording, for a change that adds a board sync
  after every chat turn.
- https://github.com/hypertask-ai/hypertask/pull/3788 — "No user path: the change only adds console
  warnings". Accurate for the file changed, but the verdict is a code reading.
- Also: #3746, #3747, #3748, #3749, #3761, #3775, #3790, #3797, #3798, #3799, #3803 (all `no app
  path` or `non-app files only`). #3751 is not counted here: its FAIL verdict did drive areas, it just
  failed.

multiprompt, 7 PRs where a journey ran but not on the changed surface:

- https://github.com/valentinyeo/multiprompt/pull/1262 — "selection.json lists only the appearance feature,
  so no selected desktop journey covers the session-listing compatibility change in src/mp_sessions.py."
- https://github.com/valentinyeo/multiprompt/pull/1263 — "The selected session-actions journey does not
  report a check for the restored-chat switch paint release."
- https://github.com/valentinyeo/multiprompt/pull/1265 — "no desktop journey was planned for the completer
  deployment" while the PR changes `src/completer_sync_shim.py`.
- https://github.com/valentinyeo/multiprompt/pull/1250 — "no selected journey exercises the chat-listing
  change", verdict rests on the appearance smoke.
- https://github.com/valentinyeo/multiprompt/pull/1255 — checks listed are `startup-maximized`,
  `IGSH-1016-reader-sidebar`, `dark-to-light`; none exercises "a fresh start keeps the chat".
- https://github.com/valentinyeo/multiprompt/pull/1251 — "selection.json intentionally selects no desktop
  journeys", so the verdict is CI read-outs plus the diff.
- https://github.com/valentinyeo/multiprompt/pull/1254 — same: "intentionally selects no desktop journeys",
  and the verdict itself notes a failed `reader-tests` job it could not explain.

multiprompt-android, 10 PRs with "Journeys driven: - none":

- https://github.com/valentinyeo/multiprompt-android/pull/527 — "Nothing was driven, so the app was not
  exercised. AI picker unavailable" on a PR that changes `DesignKit.kt` and `MultipromptApp.kt` (rounded
  entry box).
- https://github.com/valentinyeo/multiprompt-android/pull/520 — a journey did run, but `message-reply.md`
  is not the mention menu this PR changes; the verdict shows no mention-menu check (guess: journey
  selection picked the nearest file).
- Also: #519, #522, #523, #525, #529, #531, #532, #534, #535 (all non-product changes, so "none" is
  defensible, but these verdicts are still CI plus diff and no app run).

postbox, 5 PRs:

- https://github.com/valentinyeo/postbox/pull/559 — verdict body is "PASS ... - No notes." with no journey,
  screenshot or response body named, on a change to `src/main.zig` mention handling.
- https://github.com/valentinyeo/postbox/pull/556 — same "No notes." verdict on a visible UI change (blue
  read mark).
- https://github.com/valentinyeo/postbox/pull/553 — same "No notes." verdict, and the PR removes the
  repro-first gate.
- https://github.com/valentinyeo/postbox/pull/562 — same "No notes." verdict on verifier tooling.
- https://github.com/valentinyeo/postbox/pull/563 — the verdict admits the gap: "No direct evidence that
  the new static judge fallback (trying next model on 404) was exercised."

claude-cro:

- https://github.com/valentinyeo/claude-cro/pull/25 — the verdict is line-by-line code reading
  ("`ops/claude-cro-daily:5` — `set -euo pipefail` is in effect"), no run of the script and no token-missing
  scenario executed.

### E: PRs that add a required check or gate

- https://github.com/hypertask-ai/hypertask/pull/3749 — adds `.github/workflows/pstack-verifier-eval.yml`
  and moves the AI checker onto `ladder-call`.
- https://github.com/hypertask-ai/hypertask/pull/3794 — "Require leftovers in live test proof" changes
  `.claude/skills/ship/scripts/ship-check`.
- https://github.com/hypertask-ai/hypertask/pull/3798 — "A no defect close must name a control check".
- https://github.com/hypertask-ai/hypertask/pull/3751 — `config/parity/contract.json`, title "Expired inbox
  parity plan blocks every merge" (this is the PR that merged on a FAIL).
- https://github.com/valentinyeo/multiprompt-android/pull/531 — "A test fix cannot merge while its own test
  fails".
- https://github.com/valentinyeo/multiprompt-android/pull/535 — "One Android session merges at a time",
  `tools/merge-lock.mjs`.
- https://github.com/valentinyeo/multiprompt-android/pull/519 — "Merge check compares with the newest
  nightly run", `tools/pr-checks.mjs`.
- https://github.com/valentinyeo/multiprompt-android/pull/529 — ratchets `tools/tmux-target/baseline.json`
  and adds `tools/tmux-target/check.py`.
- https://github.com/valentinyeo/multiprompt-android/pull/525 — changes which phone tests a PR runs.
- https://github.com/valentinyeo/multiprompt/pull/1251 — "Run the commit identity check on master pushes",
  extends a required check to `master`.
- https://github.com/valentinyeo/multiprompt/pull/1254 — adds `tools/check-journey-evidence.mjs` and
  `if: always()` uploads, a new evidence guard.
- https://github.com/valentinyeo/multiprompt/pull/1248 — adds `tools/check-file-size.mjs` to `test.yml`.
- https://github.com/valentinyeo/multiprompt/pull/1247 — "Stop the nightly journey harness checks drifting".
- https://github.com/valentinyeo/vstack/pull/270 — adds the prior-art gate (`config/tool-registry.txt`,
  `tests/test_skill_prior_art.py`) plus nine SKILL.md lines.
- https://github.com/valentinyeo/vstack/pull/274 — adds a "Check the tree main will get" step to
  `skill-lint.yml`.
- https://github.com/valentinyeo/postbox/pull/553 — removes the repro-first gate; journeys red on main stop
  blocking PRs.
- https://github.com/valentinyeo/chromescribe/pull/24 is borderline, not counted: it adds a scope guard
  step, but to the daily map-upkeep job rather than to PR merging.

### One more flag, not in A-E

The verdict in these repos is produced by a repo workflow, not "one verifier per PR" as a separate agent.
multiprompt says it outright: "The ladder-call judge read text evidence only, so no screenshot was read for
this verdict." That is a text judge reading a result file, one hop away from the app.

## 3. Doing it well

- **Chromescribe** is clean: 8 of 8 PRs got a verdict on their merged head before merging, and the verdicts
  show the run, not a summary of it. Example
  https://github.com/valentinyeo/chromescribe/pull/31 — "`cs-verify launch --seed real` → exit 0 (4000
  transcripts seeded); `cs-verify doctor` → exit 0 ... `cs-verify journey theme` → exit 0, **9/9 checks
  pass** ... proof screenshot `theme-home-dark.png` in the verifier work folder", plus a break attempt and a cleanup.
  Its verdicts also name a verifier model from a different family than the author's.
- **multiprompt** when it selects the right feature.
  https://github.com/valentinyeo/multiprompt/pull/1249 — "evidence/verify-chat-still/result.json shows the
  chat-still journey passed on head ... evidence/verify-remind-me/result.json shows remind-me passed on
  head with Ctrl+H and picker rows 6600-6612 ... cleanup recorded". Real journeys on the changed surface,
  and vstack-style rebase cases still got re-verified at the new head.
- **multiprompt-android** https://github.com/valentinyeo/multiprompt-android/pull/530 — seven named
  journeys passed on head, including `session-pins.md` which is the changed feature.
- **postbox** https://github.com/valentinyeo/postbox/pull/554 — a verdict comment that carries real proof:
  "The same Slack journey reproduced the bug on main and passed on this PR", with the base repro run.
- **vstack** https://github.com/valentinyeo/vstack/pull/273 — the one vstack verdict that says
  "Exercised as a user (Bash writes through the hook)" and shows exit codes per scenario.

## 4. Limits

- **Sampled, not exhaustive.** 335 PRs merged, 77 examined. vstack, multiprompt, multiprompt-android and
  hypertask were cut to the 15 newest, so the A/B/D/E rates are rates over the newest work, not the window.
- **Chat attribution is weak.** Transcripts do not record a stable chat name. `SHIP_SESSION_NAME` values
  found in worker commands resolve to names that are not on the roster ("VVM Test Agent", "HT Pstack Boss"),
  and one transcript mentions several chat names. Rows marked "transcript-linked" are the ones where a
  session that mentions that PR URL also carries that name; treat them as leads. The repo totals and the
  A-E counts do not depend on attribution.
- **Verdict comment text only.** I did not open CI run logs or artifact stores (GitHub call budget), so
  "no user-path evidence" means the posted verdict shows none. postbox runs may contain journeys the terse
  "No notes." comment omits. Marked as such where it matters.
- **D is counted by the letter of the rule.** 27 of the 48 D PRs changed no user-facing surface (CI, docs,
  verify tooling), so "no app path" is honest there. The 21 that matter are the ones whose PR does change a
  surface and whose verdict still shows no journey on it (12 of those are vstack skill and hook changes);
  those are named in Flags.
- **C is 0 everywhere** because every verdict came from a bot identity, never the author. That is also why
  the "separate agent that did not write the code" clause looks satisfied on paper while the deeper
  requirement, an agent running the change, is not: a pipeline and a text judge are not that agent.
- Not checked: faceless-channels, clickshades-theme, triage, upwork-auto-applier (0 merged PRs);
  `software-factory` and `last30days` are not git checkouts, so no repo to read. A stale local checkout of
  vstack hid its 9 verify skills; those were read from the GitHub API at HEAD instead.

Evidence kept in a local study folder outside the repo (`prjson/`, `files/`, `verdicts.txt`, `attrib/`,
`selection.json`).
