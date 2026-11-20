---
name: pr-housekeeping
description: >-
  Tidy one chat's own open pull requests every loop tick, one state at a time, from a read only queue. Use it when a chat owns open PRs, or at /pr-housekeeping.
---

# PR housekeeping

Prior art: pstack `poteto-mode` Babysit, Shipping and Autopilot-full step 6 take one PR at a time; the house-rules `hypertask-triage` `pr-queue` reads PRs from the board side. Neither says which live chat owns a PR, so this skill adds the per chat queue and its states.

Every chat tidies its own PRs. Nobody tidies another chat's. Maintainers are not operators: no central timer and no central runner watches for you, so you set up your own check.

## Set up your own check

Once per chat, add this line to your own loop, the `/loop` prompt or your loop playbook, named as your live chat:

```sh
~/.claude/skills/pr-housekeeping/pr-queue --mine "<your live chat name>"
```

The skill installs there, so that path works from any repo. A tick whose run exits nonzero does not end quietly: work the named PR first, or say on its ticket why it has to wait. Add `--token-file PATH` or `HT_TOKEN` when this chat has a board login.

## Every tick

A nonzero exit is the enforcement: one of your own PRs has gone quiet, or, without `--mine`, a PR in scope has no owner. Deal with it before you pick new work. The script only reads `gh`, the live roster and, with a token, one ticket.

## Ladder of states

- BOT: CI Boss owns dependabot, renovate and github-actions PRs.
- DUPLICATE: the keeper is the PR with a passing verdict at its current head, else the newest green one, else the oldest. Message its owner chat, then close this one with a one line reason and the ticket link. Never open a second PR beside a stalled one.
- NO-OWNER: without `--mine`, a PR no live chat claims fails the tick whatever its checks and verdict. Hand it to the chat that works in the repo or owns its ticket, and say so there.
- CONFLICT: run Babysit in check mode, rebase your own branch, then push with force-with-lease on your own branch only.
- BILLING: private repos only. Scan the history for secrets and client data, then make the repo public; ask Valentin only if the scan finds something.
- RED: run Babysit in check mode, fix the failing check on your branch, then push.
- VERIFIER-FAIL: fix the finding the verifier named, push it, and get a fresh verdict at the new head.
- MISSING-LINES: add the `Author model:` and `Pacer launch:` lines to the PR body.
- NO-VERDICT: run Babysit in check mode, then get a verdict at the current head before merging.
- STALE: finish it, or close it with a reason and note that on the ticket.
- READY: merge per pstack Shipping, only when a verdict from another model family than every `Author model:` line covers this head. Never skip a required check or approval.
- OK: nothing to do this tick.

## Who owns a PR

Ownership comes from the live roster: the checkout's branch, then the chat name in the branch slug, then the ticket's board assignee, then the only checkout of the repo. The board is read only, and only with a token. With no token such a PR can still read NO-OWNER; hand it over by hand, once.

## Gaps

A gap or repeated fault goes to board 13556 (Vstack) with label PR Housekeeping. A repeat becomes a check inside `pr-queue` with a test beside it, so the next run catches it.

## Proof

`tests/test_pr_queue.py` is the proof: fixtures only, no network. It runs the script through a symlink, as the skills directory installs it, and reads ownership from a fake board. `skills/pr-housekeeping/pr-queue --self-test` runs the same suite through the script.
