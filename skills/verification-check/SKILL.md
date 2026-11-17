---
name: verification-check
description: Audit one repo or session's verification setup against what pstack demands (verify skill, feature map, repro-first, evals, verifier on GitHub) plus Valentin's additions, and print a checklist with checkmarks and evidence. Works for any surface (web app, Windows desktop, Android, iOS, CLI, service). Use for /verification-check [repo path or session name], "is this session's verification set up properly", "how far is X with verification". Read only.
---

# Verification check

Prior art: checked pstack (create-verification-skill, maintain-verification-skill, principle-prove-it-works), vstack and company-skills (design-lead-setup, live-ui-audit); none fits because they build or maintain one verify skill, or audit UI, while this one audits a repo's whole verification setup against pstack and reports a checklist, without changing anything.

Compare a repo's real verification setup with what pstack demands. Read only: never edit, file, push or start workers. The answer is a checklist the owner can read in a minute.

## 1. Resolve the target

Argument is a repo path or a live session name. No argument means the current repo. `facts.sh` resolves a session name through `~/.local/share/house-rules/fleet/roster-live`.

## 2. Load the demands from pstack itself

Never answer from memory. Find the installed pstack: the highest version under `~/.claude/plugins/cache/*/pstack/*/skills/`. Read these and extract every concrete "must":

- `create-verification-skill/SKILL.md`: launch, doctor, drive, evidence, cleanup, helpers; feature map shape; skill proved by running it.
- `maintain-verification-skill/SKILL.md`: periodic pass, live drive of every feature, one PR of corrections.
- `poteto-mode/playbooks/bug-fix.md`: reproduce on the matching surface first, failing repro lands before the fix, verify on the same surface.
- `poteto-mode/playbooks/shipping.md`: verify each PR independently, green is not safe.
- `poteto-mode/playbooks/eval.md`: blinded evals for skills.
- `principle-prove-it-works`, `tdd`, `correct`: real artifact, failing test first, every correction becomes a check with a rule table.

If pstack added a demand that the list in step 4 lacks, add it as an extra item and say so.

## 3. Collect the facts

```sh
"$(dirname "$(readlink -f ~/.claude/skills/verification-check/SKILL.md)")/facts.sh" <repo-path | session-name>
```

It prints the repo, surface hints, verify skills with headings and feature-file counts, workflows with triggers and concurrency, required checks, rule-table size and the last merged PRs' verifier verdicts. Then open the files it names. A filename or a keyword match is not evidence; read the step and confirm it does what the item demands.

## 4. Judge each item

Match the surface: web apps drive a real browser (Playwright or Chrome DevTools), Windows desktop drives the real exe on a GitHub Windows runner, Android drives an emulator on a GitHub Linux runner plus a real phone before release, iOS a simulator, CLIs a PTY, services real HTTP.

Items, in this order:

1. Agent drives the real app (pstack create-verification-skill).
2. Human is not the verifier: recent bugs were caught by an agent before the owner saw them.
3. Feature map: one file per user-facing feature, four sections.
4. Feature map coverage: counted against the app's real feature list by a check, as a number like "41 of 230". Below 100% is not done.
5. Map kept current: a CI check blocks a new feature without a map entry, and a scheduled maintain-verification-skill pass runs.
6. Reproduce bug first and failing test first: a gate requires a journey that fails on the base branch and passes on the PR.
7. Agents try to break each fix.
8. Tests for the verify skill: planted bug gives FAIL, clean build gives PASS, more than one model family.
9. Hard rules in checks: rule table pairing each rule with the check that enforces it.
10. Auto-merge only once earned: nothing merges on a verdict that items 1 to 8 cannot back.
11. Spend tokens on verifying: most active work is verification until the list is green.
12. Real-size data: journeys start with seeded state at the size real users have, not an empty app.
13. Verifier runs on GitHub, as a required check.
14. Video or trace before release: the release is gated on recorded evidence per changed feature.
15. Speed: verifier result in about 20 minutes; every workflow has a concurrency group with cancel-in-progress.

## 5. Reply

First line: "<repo>: N of 15 done". Then the list, one line each: icon, item, one plain sentence of evidence with a PR or file link. Legend, shown once under the list:

- ✅ done and proven by a file or run you read
- 🟡 in progress: an open PR or a partial setup
- ⬜ not started
- ⏸ on hold on purpose
- ❌ broken: exists but fails or is bypassed

Plain words for a product owner. Full https:// links. End with the single most important missing item.
