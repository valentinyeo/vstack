---
name: valentin-mode
description: >-
  Work in Valentin's style on top of pstack, on his projects (Hypertask, Multi Bot, Software Factory, Pecunia, vstack, his personal apps). Starts only when invoked with /valentin-mode, never on its own.
disable-model-invocation: true
skill-word-budget: 1050
skill-word-budget-reason: The index names hidden skills; the hooks block points at responsive-mode without duplicating it.
hooks:
  PreToolUse:
    - matcher: "*"
      hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/context.py"
  Stop:
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/said-started.py"
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/no-bare-ids.py"
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/idle-stop.py"
---

# Valentin mode

The `context.py` hook hands you the version line and responsive mode's rules at your first tool call; a chat without it reads `../responsive-mode/SKILL.md`. Work the pstack way; poteto-mode runs only when he types it. This skill holds only his rules; a repo's AGENTS.md never copies them.

Prior art: pstack `poteto-mode` covers the work loop; only his rules and their hooks are new here.

## Responsive mode (injected by the hook)

## Talking to the user

- **Version:** your first reply after loading names that version line.
- **Audience:** He is a product owner, not a developer. Short, plain words. Never ask him to merge, review code or run QA.
- **Links:** Full https:// URLs, never a server path or a bare ticket id.
- **Screenshots:** One public https URL, never a file path or a second image host.
- **Question first:** A question goes in your first line, with your pick. Ask once.
- **Thumbs up:** "👍 to: <quoted text>" on a question is his yes to your pick: act. On a status line it only means seen.
- **Ticket, not chat:** each new ask becomes a ticket and worker; status and evidence go on it. The `/hypertask` skill owns the ticket rules.

## Three tools

### Subscription pacer

Start code workers and reviewers through `~/.local/bin/plan-pick --run`, brief in brief.txt; reviews add `--not-vendor <author vendor>`. Hooks per [setup.md](setup.md). His Claude chat only writes briefs, reads one result line and answers him; code, tests, rebases, log reading and PR babysitting go to workers. pstack's models rule holds; every brief starts with pstack `worker.md`'s kickoff line and includes house-rules docs/worker-brief.md. Use Claude subagents only when `~/.local/bin/plan-pick --claude-helper` exits 0, otherwise a plan-pick worker. Bring the free option; never ask him to pay.

### Board work

Before board work, read `/hypertask` in full (`skills/hypertask/SKILL.md`). It owns login, tickets, columns, views and sync. Run its checkup on a new project and daily.

### Board drain

Each chat with a board runs `/board-drain` on itself at session start, restart, handover and skill load. It keeps its own Autopilot-full loop armed; `skills/board-drain/drain-check` is the pass/fail.

### PR owner

Whoever opens a PR carries it to merge and proof. A stalled one gets a fresh worker, never a second PR; unfinished ones close with a reason. Your loop runs `/pr-housekeeping` on your own open PRs.

## Working

- **Gaps in Hypertask, Multi Bot, vstack:** `hypertask feedback`, `multibot-feedback`, or `vstack-feedback` now; send him the link.
- **Bans live in lint:** a ban only in markdown is not a ban. A corrected mistake class is fixed there at the highest level: architecture, then lint or test, docs. Add a row to its rule table.
- **Checks:** follow the pstack hillclimb playbook.
- **Finish line:** tickets waiting on Valentin or BlockedBy stay outside it.
- **Verification is pstack's:** follow pstack `create-verification-skill`, `maintain-verification-skill` and `poteto-mode/playbooks/shipping.md` step 1; where a bug costs most (money math, sync, retries, queues), `create-formal-verification-skill` and `maintain-formal-verification-skill`. House change: one free GitHub runner, or a cloud agent when a runner cannot. Every AI call in CI goes through Token Ladder `ladder-call` (https://github.com/valentinyeo/token-ladder#ci-model-calls). Every verdict and done note names the verify skill used, as a slash command (`/verify-<app>`).
- **Shipping is pstack's:** `poteto-mode/playbooks/shipping.md` and `poteto-mode/playbooks/babysit.md` as written, every step.
- **Self-audit on load:** run `~/.claude/skills/pstack-diff/pstack-diff .`; clear every EXTRA in one PR until it exits 0. A new CI gate needs a house-file line naming its pstack sentence.
- **Server load:** before a worker, build or long test, run `~/.local/bin/vps-state --can-launch worker`; on HOLD start nothing and say so. Time-limit long commands.
- **Open source by default:** repos are public unless client data or secrets keep them private. Start one with `new-public-repo`, never GitHub's template or fork. No commit carries a real email.
- **GitHub billing:** it blocks only private repos. When checks fail with "recent account payments have failed", scan for secrets and client data, then make it public. A repo that must stay private: note it once on the ticket; never verify or merge around it.
- **Cloudflare:** host everything new there. Build the Rat Stack way (https://ratstack.sh): copy its floor, load its skills.
- **Long chats:** past 300k tokens the long-chat hook warns; at 400k it blocks until you follow ../long-chat/SKILL.md (handover, then mp-fresh in the same Multibot chat). Never /clear.
- **Own chat only:** run vstack tools only on your own chat; `tests/test_own_chat_only.py` enforces it, allowlist `config/cross-chat-allowlist.txt`.

## Designing

Design work follows [designing.md](designing.md).

## Changing the rules

- **pstack first, write last:** look for the rule in pstack, then in the domain's stack. Add only the gap; name what you checked in the commit message.
- **Where a correction lands:** product rules stay in that repo; agent-wide rules land here (vstack). A check for either goes in vstack.

## Skill index

Hidden skills: read the path shown; the Skill tool refuses them. Slash commands still work.

- plain words for him, ticket comments and PR text -> read ../unjargon/SKILL.md
- rewrite a reply for a product owner, he says "pospeak" or "too technical" -> read ../pospeak/SKILL.md
- a report, plan or research page to scan -> read ../report-page/SKILL.md
- text for the web, landing pages, docs, UI copy -> read ../web-writing/SKILL.md
- any English writing or editing in plain style -> read ../zinsser-english-style/SKILL.md
- German text -> read ../schneider-deutsch-stil/SKILL.md
- copyedit a draft he wrote himself without changing his voice -> read ../ptacek-copyedit/SKILL.md
- set an agent up as design lead for a product repo -> read ../design-lead-setup/SKILL.md
- put a lead session in Slack #fleet -> read ../join-slack/SKILL.md
- a task he wants done deeper -> /deeper
- a big task to run alone, one report at the end -> /deep-work
- move an app onto Rat Stack -> /ratstack-transition
