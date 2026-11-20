---
name: pr-housekeeping
description: >-
  Tidy one chat's own open pull requests every loop tick, one state at a time, from a read only queue. Use it when a chat owns open PRs, or at /pr-housekeeping.
---

# PR housekeeping

Prior art: pstack `poteto-mode`, whose Babysit, Shipping and Autopilot-full step 6 playbooks take one PR at a time, plus the house-rules `hypertask-triage` `pr-queue`, which reads PRs from the board's side. Neither says which live chat owns a PR and what that chat does with it on this tick, so this skill adds the per chat queue and its states.

Every chat tidies its own PRs. Nobody tidies another chat's.

## Every tick

Run this from the repo you work in, named as your live chat:

```sh
skills/pr-housekeeping/pr-queue --mine "<your live chat name>"
```

A nonzero exit is the enforcement: something you own has no owner or has gone quiet. Deal with it before you pick new work. The script only reads `gh` and the live roster, so it writes nothing to GitHub and nothing to a board.

## Ladder of states

- BOT: CI Boss owns dependabot, renovate and github-actions PRs, so leave it alone.
- DUPLICATE: message the other PR's owner chat. The older or weaker one closes with a one line reason and the ticket link. Never open a second PR beside a stalled one.
- CONFLICT: rebase your own branch and push with force-with-lease, on your own branch only.
- BILLING: billing blocks private repos only. Scan the repo history for secrets and client data, then make the repo public. Ask Valentin only when the scan finds something.
- RED: run Babysit in check mode, fix the failing check on your branch, then push.
- VERIFIER-FAIL: fix the finding the verifier named, push it, and get a fresh verdict at the new head.
- MISSING-LINES: add the `Author model:` and `Pacer launch:` lines to the PR body.
- NO-OWNER: in a run without `--mine`, hand the PR to the chat that owns the repo or its ticket.
- STALE: finish it, or close it with a reason and note that on the ticket.
- NO-VERDICT: ask for a verdict at the current head and read it before merging.
- READY: merge per pstack Shipping, only when the verdict's model family differs from every `Author model:` line and that verdict covers the current head. Never skip a required check or approval.
- OK: nothing to do this tick.

## Who owns a PR

Ownership comes from the live roster, branch names and repo checkouts, because `pr-queue` has no board login. A PR whose ticket names its owner on the board can still read NO-OWNER. Hand that one over by hand, once; branch names and checkouts then keep it matched.

## Gaps

A gap or a repeated fault goes to the PR Housekeeping view on board 2060 with label PR Housekeeping. When a gap repeats, it becomes a check inside `pr-queue` with a test beside it, so the next run catches it.

## Proof

`tests/test_pr_queue.py` is the proof: fixtures only, no network. Run `skills/pr-housekeeping/pr-queue --self-test` for the same suite through the script.
