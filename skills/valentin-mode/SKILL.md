---
name: valentin-mode
description: >-
  Work in Valentin's style on top of pstack, on his projects (Hypertask, Multi Bot, Software Factory, Pecunia, vstack, his personal apps). Starts only when invoked with /valentin-mode, never on its own.
disable-model-invocation: true
---

# Valentin mode

Run `/pstack:poteto-mode` for the task. This skill holds only Valentin's own rules. A repo's AGENTS.md holds facts about that repo, never a copy of these rules.

## Talking to the user

- **Audience:** He is a product owner, not a developer. Short, plain words. Never ask him to merge, review code or run QA.
- **Links:** Full https:// URLs, never a server path or a bare ticket id.
- **Screenshots:** One public https URL, never a file path or a second image host.
- **Question first:** A question goes in your first line, with your pick. Ask once.
- **Thumbs up:** "👍 to: <quoted text>" on a question is his yes to your pick: act. On a status line it only means seen.
- **Ticket, not chat:** Every unit gets a ticket before work; status, evidence and questions go on it, not in chat. The `hypertask-work` skill owns the ticket rules.
- **Pace:** Answer each message within a minute. Long work runs in the background through `plan-pick --run`.

## Three tools

### Subscription pacer

Start every code worker and reviewer through `~/.local/bin/plan-pick --run`, with the brief in a file named brief.txt. Reviews add `--not-vendor <author vendor>`. Chats Valentin talks to run on Claude; code workers never do. The always-on pstack models rule holds the lanes. Every brief includes the shared worker rules from the house-rules repo's docs/worker-brief.md. Never ask him to pay more; bring the free option.

### Board rules

Board work follows the `hypertask-work` skill: your own login, a ticket before work, the true column. Get the login with `/board-identity`. Never write as Valentin; a guard blocks it.
Run `/hypertask-checkup` on a new project and daily in your loop.

### Board sync

The project's agent notes name its board in one line: `Hypertask board: <id>, label: <label>`. In your own loop, run `skills/hypertask-work/reconcile --board <id> --label <label>`, then again with `--apply --limit 5`. No central timer runs it.

## Working

- **Hypertask gaps:** file one at once with `hypertask feedback` (see `hypertask-work`), then send him the link.
- **Bans live in lint:** a ban written only in markdown is not a ban.
- **Checks:** each repo cuts push-to-verdict time with the pstack hillclimb playbook. Fix flaky checks per pstack tdd; never rerun to pass.
- **Finish line:** tickets waiting on Valentin or BlockedBy stay outside it.
- **Verifying:** every app has one `verify-<app>` skill. Every ticket's Done when names its proof. A behaviour PR carries proof that fits the change: a screenshot or video for UI, a transcript for CLI, a response body for API. No proof means FAIL.
- **Verifier:** from a different model family than every author. Every PR body carries one `Author model: <family>/<model>` line per author.
- **Server and cloud:** this server runs workers, focused tests, the app, the QA phone, git and boards. GitHub-hosted runners run the full suite, CI, reviews and the verifier. Never a self-hosted runner.
- **Open source by default:** repos are public unless client data or secrets keep them private. Start one with `new-public-repo`. No commit carries a real email.
- **GitHub billing:** it blocks only private repos. When checks fail with "recent account payments have failed", scan the repo for secrets and client data, then make it public. A repo that must stay private waits: note it once on the ticket.
- **Cloudflare:** a new project begins from Joel Hooks' rat-stack template.
- **Long chats:** save the handover, then start a fresh chat with its loop on.
- **Formal where bugs cost most:** the first PR touching money math, sync, retries or a queue gets a ticket for pstack `create-formal-verification-skill`.

## Designing

- Never ask him to choose a design. Build yours; he judges the live result. Label a design ticket `needs-design`. Give him 2-3 quick throwaway HTML variants built from the app's real styles, your pick marked, before the build starts. Figma only when he asks on that ticket.
- One specialist skill per step: `impeccable` for style, `animate` then `review-animations` for motion (none by default), `modern-web-guidance` for the web platform, `apple-design` or `material-3` for native. Never stack two taste skills on one step.

## Changing the rules

- **pstack first, write last:** look for the rule in pstack, then in the domain's stack. Add only the gap, and name what you checked in the commit message.
- **Where a correction lands:** a correction about one product goes in that product's repo. A correction about how agents work everywhere goes in this skill (vstack), whichever session heard it. A check for either goes in vstack too.
