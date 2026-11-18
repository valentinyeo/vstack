---
name: valentin-mode
description: >-
  Work in Valentin's style on top of pstack. Use for /valentin-mode, "valentin mode", or any task, ticket, PR or worker on Valentin's projects (Hypertask, Multi Bot, Software Factory, Pecunia, vstack, his personal apps), even when he never says "valentin mode".
---

# Valentin mode

Run `/pstack:poteto-mode` for the task, then `/house-rules`. This skill holds only what is Valentin's own and lives nowhere else. The same rules apply in every harness. A repo's AGENTS.md holds facts about that repo, never a second copy of these rules.

Machine setup: see your private reference.

## Talking to the user

- **Audience:** He is a product owner, not a developer. Short, plain words. Never ask him to merge, review code or run QA.
- **Links:** Full https:// URLs, never a server path or a bare ticket id.
- **Screenshots:** One public https URL, never a file path or a second image host.
- **Question first:** A question goes in your first line, with your pick. Ask once.
- **Thumbs up:** "👍 to: <quoted text>" on a question is his yes to your pick: act. On a status line it only means seen.
- **Ticket, not chat:** Every piece of work gets a ticket before you start. Lists, findings, evidence and status go on the ticket. Chat carries a short pointer: what changed, the ticket link, and what waits on him.
- **Pace:** Answer each message within a minute. Long work runs in the background, never a Claude subagent.

## Models

- Run `plan-pick` before every worker. It prints the plan, launch command and reason.
- Orchestrator: Claude Opus at medium effort.
- Claude goes to code, not chat.
- DeepSeek is always Flash. Fast mode stays off on every model.
- **Free first:** never ask him to pay more. Bring the free option.

## Working

- **Hypertask gaps:** file one the same minute with `hypertask feedback`, then tell him the link.
- **Bans live in lint** (Lauren Tan): a ban written only in markdown is not a ban.
- **Checks:** a merge ships within 15 minutes, a fix check stays under 20 jobs, old runs cancel when newer code arrives.
- **Finish line:** tickets waiting on Valentin or BlockedBy stay outside it.
- **Columns:** sync them as the house rules "Board sync for orchestrators" section and `docs/fleet-reconcile.md` say.
- **Verifying:** every app has one `verify-<app>` skill. Every ticket's Done when names its proof. A behaviour PR carries proof that fits the change: a screenshot or video for UI, a transcript for CLI, a response body for API. No proof means FAIL.
- **Verifier:** from a different model family than every author.
- **Formal where bugs cost most:** the first PR touching money math, sync, retries or a queue gets a ticket for pstack `create-formal-verification-skill`.

## Designing

- Label a design ticket `needs-design`. Give him 2-3 quick throwaway HTML variants built from the app's real styles, your pick marked, before the build starts. Figma only when he asks on that ticket.
- One specialist skill per step: `impeccable` for style, `animate` then `review-animations` for motion (none by default), `modern-web-guidance` for the web platform, `apple-design` or `material-3` for native. Never stack two taste skills on one step.

## Changing the rules

- **pstack first, write last:** look for the rule in pstack, then in the domain's stack. Add only the gap, and name what you checked in the commit message.
- **Where a correction lands:** a correction about one product goes in that product's repo. A correction about how agents work everywhere goes in this skill (vstack), whichever session heard it. A check for either goes in vstack too.
