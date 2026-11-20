---
name: valentin-mode
description: >-
  Work in Valentin's style on top of pstack, on his projects (Hypertask, Multi Bot, Software Factory, Pecunia, vstack, his personal apps). Starts only when invoked with /valentin-mode, never on its own.
disable-model-invocation: true
---

# Valentin mode

First step, before any other tool: load the `pstack:poteto-mode` and `responsive-mode` skills. This skill holds only Valentin's own rules. A repo's AGENTS.md holds facts about that repo, never a copy of these rules.

## Talking to the user

- **Audience:** He is a product owner, not a developer. Short, plain words. Never ask him to merge, review code or run QA.
- **Links:** Full https:// URLs, never a server path or a bare ticket id.
- **Screenshots:** One public https URL, never a file path or a second image host.
- **Question first:** A question goes in your first line, with your pick. Ask once.
- **Thumbs up:** "👍 to: <quoted text>" on a question is his yes to your pick: act. On a status line it only means seen.
- **Ticket, not chat:** Every unit gets a ticket before work; status, evidence and questions go on it, not in chat. The `hypertask-work` skill owns the ticket rules.

## Three tools

### Subscription pacer

Start every code worker and reviewer through `~/.local/bin/plan-pick --run`, with the brief in a file named brief.txt. Reviews add `--not-vendor <author vendor>`. Chats Valentin talks to run on Claude; code workers never do. The always-on pstack models rule holds the lanes. Every brief includes the shared worker rules from the house-rules repo's docs/worker-brief.md. Never ask him to pay more; bring the free option.

### Board rules

Board work follows the `hypertask-work` skill: your own login, a ticket before work, the true column. Get the login with `/board-identity`. Never write as Valentin; a guard blocks it.
Run `/hypertask-checkup` on a new project and daily in your loop.

### Board drain

A chat with a board drains it. Its agent notes name the board: `Hypertask board: <id>, label: <label>`. Your own loop, every 15 minutes, runs `skills/hypertask-work/reconcile --board <id> --label <label>`, then with `--apply --limit 5`, and starts a `plan-pick` worker on the top Todo ticket you can do. Todo work with nothing in Doing means your loop is off: turn it on. A ticket that waits on Valentin carries his name in waiting-on; a blocked one names its blocker.

### PR owner

From pstack Autopilot-full: one owner carries each PR from build to merge. Whoever opens a PR stays on it through green checks, fixes, merge and live proof. Your loop checks each open PR has a worker pushing it; a stalled one gets a fresh worker, never a new PR beside it. A PR nobody will finish gets closed with a reason.

## Working

- **Hypertask gaps:** file one at once with `hypertask feedback` (see `hypertask-work`), then send him the link.
- **Bans live in lint:** a ban written only in markdown is not a ban.
- **Checks:** each repo cuts push-to-verdict time with the pstack hillclimb playbook. Fix flaky checks per pstack tdd; never rerun to pass.
- **Finish line:** tickets waiting on Valentin or BlockedBy stay outside it.
- **Verifying:** every app has one `verify-<app>` skill. Every ticket's Done when names its proof. A behaviour PR carries proof that fits the change: a screenshot or video for UI, a transcript for CLI, a response body for API. No proof means FAIL.
- **Verifier:** from a different model family than every author. Every PR body carries one `Author model: <family>/<model>` line per author.
- **Server and cloud:** this server runs workers, focused tests, the app, the QA phone and boards. GitHub runners run CI and the verifier. Never a self-hosted runner.
- **Open source by default:** repos are public unless client data or secrets keep them private. Start one with `new-public-repo`, never GitHub's template or fork button. No commit carries a real email.
- **GitHub billing:** it blocks only private repos. When checks fail with "recent account payments have failed", scan its history for secrets and client data, then make it public. A repo that must stay private waits: note it once on the ticket; never verify or merge around it.
- **Cloudflare:** a new project begins from Joel Hooks' rat-stack template.
- **Long chats:** save the handover, then start a fresh chat with its loop on.
- **Formal where bugs cost most:** the first PR touching money math, sync, retries or a queue gets a ticket for pstack `create-formal-verification-skill`.

## Designing

Design work follows [designing.md](designing.md).

## Changing the rules

A correction about one product goes in that product's repo. One about how agents work everywhere goes in this skill (vstack). A check for either goes in vstack too. More in [changing-rules.md](changing-rules.md).
