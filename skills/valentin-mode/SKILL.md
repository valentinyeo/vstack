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
- **Ticket, not chat:** Every unit gets a ticket before work; status, evidence and questions go on it, not in chat. The `hypertask-work` skill owns the ticket rules.
- **Pace:** Answer each message within a minute. Long work runs in the background through `plan-pick --run`.

## Three tools

### Subscription pacer

Start every code worker and reviewer through `~/.local/bin/plan-pick --run`, with the brief in `brief.txt`. Reviews add `--not-vendor <author vendor>`. Chats Valentin talks to run on Claude; code workers never do. `~/.claude/rules/pstack-models.md` holds the lanes. Never ask him to pay more; bring the free option.

### Board rules

Board work follows the `hypertask-work` skill: your own login, a ticket before work, the true column. Get the login with `/board-identity`. Never write as Valentin; a guard blocks it.

### Board sync

The project's own agent notes (its AGENTS file or CLAUDE file) name its board in one line: `Hypertask board: <id>, label: <label>`. In your own loop, run `skills/hypertask-work/reconcile --board <id> --label <label>`, then again with `--apply --limit 5`. No central timer runs it.

## Working

- **Hypertask gaps:** file one the same minute with `hypertask feedback`, then tell him the link. The `hypertask-work` skill has the command.
- **Bans live in lint** (Lauren Tan): a ban written only in markdown is not a ban.
- **Checks:** pstack sets no number. Each repo improves push-to-verdict time with the pstack hillclimb playbook. Flaky checks get fixed per pstack tdd, never rerun to pass.
- **Finish line:** tickets waiting on Valentin or BlockedBy stay outside it.
- **Columns:** The `hypertask-work` skill owns the login, board, columns, worker leases and reconcile.
- **Verifying:** every app has one `verify-<app>` skill. Every ticket's Done when names its proof. A behaviour PR carries proof that fits the change: a screenshot or video for UI, a transcript for CLI, a response body for API. No proof means FAIL.
- **Verifier:** from a different model family than every author. Every PR body carries one `Author model: <family>/<model>` line per author; the picker reads it.
- **Formal where bugs cost most:** the first PR touching money math, sync, retries or a queue gets a ticket for pstack `create-formal-verification-skill`.

## Designing

- Label a design ticket `needs-design`. Give him 2-3 quick throwaway HTML variants built from the app's real styles, your pick marked, before the build starts. Figma only when he asks on that ticket.
- One specialist skill per step: `impeccable` for style, `animate` then `review-animations` for motion (none by default), `modern-web-guidance` for the web platform, `apple-design` or `material-3` for native. Never stack two taste skills on one step.

## Changing the rules

- **pstack first, write last:** look for the rule in pstack, then in the domain's stack. Add only the gap, and name what you checked in the commit message.
- **Where a correction lands:** a correction about one product goes in that product's repo. A correction about how agents work everywhere goes in this skill (vstack), whichever session heard it. A check for either goes in vstack too.
