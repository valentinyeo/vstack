---
name: pr-housekeeping
description: >-
  Tidy one chat's own open pull requests every loop tick, one state at a time, from a read only queue. Use it when a chat owns open PRs, or at /pr-housekeeping.
---

# PR housekeeping

Prior art: pstack `poteto-mode` Babysit, Shipping and Autopilot-full step 6 take one PR at a time; the older `hypertask-triage` `pr-queue` reads PRs from the board side. Neither says which live chat owns a PR, so this skill adds the per chat queue and its states.

Every chat tidies its own PRs. Nobody tidies another chat's. vstack builds the queue tool; your chat runs it on its own work only. Pass `--mine` with your live chat name every tick.

## Set up your own check

Once per chat, add this line to your own loop, the `/loop` prompt or your loop playbook, named as your live chat:

```sh
~/.claude/skills/pr-housekeeping/pr-queue --mine "<your live chat name>"
```

The skill installs there, so that path works from any repo. A tick whose run exits nonzero does not end quietly: work the named PR first, or say on its ticket why it has to wait. Add `--token-file PATH` or `HT_TOKEN` when this chat has a board login.

## Every tick

A nonzero exit is the enforcement: one of your own PRs has gone quiet or needs action. Deal with it before you pick new work. The script only reads `gh`, local refs, the live roster and, with a token, one ticket. It keeps a per-chat cleanup record in local state. It never deletes a worktree or branch.

## Ladder of states

- BOT: CI Boss owns dependabot, renovate and github-actions PRs.
- DUPLICATE: the keeper is the PR with a passing verdict at its current head, else the newest green one, else the oldest. Message its owner chat, then close this one with a one line reason and the ticket link. Never open a second PR beside a stalled one. The `pr-overlap` GitHub check fails the newer PR when an older open one already edits a guarded file or carries the same ticket key.
- NO-OWNER: your pull request lacks a readable owner for this chat. Add `Owner chat: <your live name>` to the body, or branch with your chat's unique initials prefix, then rerun.
- CONFLICT: run Babysit in check mode, rebase your own branch, then push with force-with-lease on your own branch only.
- BILLING: private repos only. Scan the history for secrets and client data, then make the repo public; ask Valentin only if the scan finds something.
- RED: run Babysit in check mode, fix the failing check on your branch, then push.
- VERIFIER-FAIL: fix the finding the verifier named, push it, and get a fresh verdict at the new head.
- MISSING-LINES: add the `Author model:` and `Pacer launch:` lines to the PR body.
- NO-VERDICT: run Babysit in check mode, then get a verdict at the current head before merging.
- STALE: finish it, or close it with a reason and note that on the ticket.
- READY: this tick records your PR before the merge. Merge per pstack Shipping once the verifier's PASS or PASS+NOTES covers the current head. Never skip a required check or approval.
- CLEANUP: your recorded PR merged, but local copies remain. Run the printed branch-scoped repo-tidy command from outside its worktree. Never bypass a hold. Retry next tick until the refs are gone. A changed tip needs an ownership check, not deletion.
- OK: nothing to do this tick.

A worker merging for your chat does not end this duty. Run this queue before handing it the merge, then keep your own loop alive for held cleanup. Already merged PRs never observed by this queue need an explicit repo-tidy audit.

## Who owns a PR

Ownership comes from the `Owner chat:` line in the body, then branch initials unique among live chats, then the live roster: checkout branch, chat name in the branch slug, ticket assignee on the board, then the only checkout of the repo. The board is read only, and only with a token.

## Gaps

A gap or repeated fault goes to board 13556 (Vstack) with label PR Housekeeping. A repeat becomes a check inside `pr-queue` with a test beside it, so the next run catches it.

## Proof

`tests/test_pr_queue.py` is the proof: fixtures only, no network. It runs the script through a symlink, as the skills directory installs it, and reads ownership from a fake board. `skills/pr-housekeeping/pr-queue --self-test` runs the same suite through the script.
