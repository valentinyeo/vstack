---
name: valentin-mode
description: >-
  Work in Valentin's style on top of pstack, on his projects (Hypertask, Multi Bot, Software Factory, Pecunia, vstack, his personal apps). Starts only when invoked with /valentin-mode, never on its own.
disable-model-invocation: true
---

# Valentin mode

If no rules appear under Responsive mode below, load the `responsive-mode` skill before any other tool. A Codex, Cursor or pi chat, or one without bypass permissions, gets no paste. Load `pstack:poteto-mode` too where your harness allows it. This skill holds only Valentin's own rules. A repo's AGENTS.md holds facts about that repo, never a copy of these rules.

## Responsive mode (pasted in when this skill loads)

!`awk 'c>=2{print} /^---$/{c++}' "${CLAUDE_SKILL_DIR}/../responsive-mode/SKILL.md"`

## Talking to the user

- **Audience:** He is a product owner, not a developer. Short, plain words. Never ask him to merge, review code or run QA.
- **Links:** Full https:// URLs, never a server path or a bare ticket id.
- **Screenshots:** One public https URL, never a file path or a second image host.
- **Question first:** A question goes in your first line, with your pick. Ask once.
- **Thumbs up:** "👍 to: <quoted text>" on a question is his yes to your pick: act. On a status line it only means seen.
- **Ticket, not chat:** Every unit gets a ticket before work; status, evidence and questions go on it, not in chat. The `/hypertask` skill owns the ticket rules.

## Three tools

### Subscription pacer

Start every code worker and reviewer through `~/.local/bin/plan-pick --run`, brief in brief.txt. Reviews add `--not-vendor <author vendor>`. Chats Valentin talks to run on Claude; code workers never do. The pstack models rule holds the lanes. Every brief includes docs/worker-brief.md. Never ask him to pay more; bring the free option.

### Board work

Before any board work, read the `/hypertask` skill in full (`skills/hypertask/SKILL.md`). It owns login, tickets, columns, views and sync. Run its checkup on a new project and daily.

## Working

- **Hypertask gaps:** file one at once with `hypertask feedback` (see the `/hypertask` skill), then send him the link.
- **Bans live in lint:** a ban written only in markdown is not a ban.
- **Checks:** follow the pstack hillclimb playbook. Fix flaky checks per pstack tdd; never rerun to pass.
- **Finish line:** tickets waiting on Valentin or BlockedBy stay outside it.
- **Verifying:** every app has one `verify-<app>` skill. Every Done when names its proof. A behaviour PR carries proof that fits: screenshot or video for UI, transcript for CLI, response body for API. No proof, no PASS.
- **Verifier:** from a different model family than every author. Every PR body carries one `Author model: <family>/<model>` line per author.
- **Server and cloud:** this server runs workers, tests, the app, the QA phone and boards. GitHub runners run CI and the verifier. No self-hosted runners.
- **Open source by default:** repos are public unless client data or secrets keep them private. Start one with `new-public-repo`, never GitHub's template or fork. No commit carries a real email.
- **GitHub billing:** it blocks only private repos. When checks fail with "recent account payments have failed", scan its history for secrets and client data, then make it public. A repo that must stay private waits: note it once on the ticket; never verify or merge around it.
- **Cloudflare:** host everything new there, each page included. Build the Rat Stack way (https://ratstack.sh): copy its floor, load its skills.
- **Long chats:** save the handover, then start a fresh chat with its loop on.
- **Formal where bugs cost most:** the first PR touching money math, sync, retries or a queue gets a ticket for pstack `create-formal-verification-skill`.

## Designing

- Never ask him to choose a design. Build yours; he judges the live result. Label a design ticket `needs-design`. Before the build, give him 2-3 throwaway HTML variants in the app's styles, your pick marked. Figma only when he asks.
- One specialist skill per step: `impeccable` for style, `animate` then `review-animations` for motion (none by default), `modern-web-guidance` for the web platform, `apple-design` or `material-3` for native. Never stack two taste skills on one step.

## Changing the rules

- **pstack first, write last:** look for the rule in pstack, then in the domain's stack. Add only the gap, and name what you checked in the commit message.
- **Where a correction lands:** a correction about one product goes in that product's repo. A correction about how agents work everywhere goes in this skill (vstack), whichever session heard it. A check for either goes in vstack.
