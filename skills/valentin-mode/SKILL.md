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
          command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/reply-check.py"
  Stop:
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/said-started.py"
---

# Valentin mode

!`sh "${CLAUDE_SKILL_DIR}/version.sh"`

If no rules appear under Responsive mode below, load `responsive-mode` before any other tool. A Codex, Cursor or pi chat without bypass gets no paste. Work the pstack way; poteto-mode runs only when he types it. This skill holds only his rules; a repo's AGENTS.md never copies them.

## Responsive mode (pasted in when this skill loads)

!`awk 'c>=2{print} /^---$/{c++}' "${CLAUDE_SKILL_DIR}/../responsive-mode/SKILL.md"`

## Talking to the user

- **Version:** your first reply after loading names the version line above.
- **Audience:** He is a product owner, not a developer. Short, plain words. Never ask him to merge, review code or run QA.
- **Links:** Full https:// URLs, never a server path or a bare ticket id.
- **Screenshots:** One public https URL, never a file path or a second image host.
- **Question first:** A question goes in your first line, with your pick. Ask once.
- **Thumbs up:** "👍 to: <quoted text>" on a question is his yes to your pick: act. On a status line it only means seen.
- **Ticket, not chat:** each new ask from him becomes a ticket, then a worker; status, evidence and questions go on it. The `/hypertask` skill owns the ticket rules.

## Three tools

### Subscription pacer

Start every code worker and reviewer through `~/.local/bin/plan-pick --run`, brief in brief.txt. Reviews add `--not-vendor <author vendor>`. Wire hooks per [setup.md](setup.md). Chats Valentin talks to run on Claude; code workers never do. The pstack models rule holds the lanes. Every brief includes docs/worker-brief.md. Never ask him to pay more; bring the free option. A chat Valentin talks to always only writes briefs, reads one result line and answers him; code, tests, rebases, log reading and PR babysitting always go to workers. Pace decides only who runs the work: a Claude subagent only when `~/.local/bin/plan-pick --claude-helper` exits 0; otherwise plan-pick workers.

### Board work

Before board work, read the `/hypertask` skill in full (`skills/hypertask/SKILL.md`). It owns login, tickets, columns, views and sync. Run its checkup on a new project and daily.

### Board drain

Each chat with a board runs `/board-drain` on itself at session start, after a restart or handover, and whenever this skill loads. It keeps its own Autopilot-full loop armed; `skills/board-drain/drain-check` is the pass/fail.

### PR owner

Whoever opens a PR carries it to merge and proof. A stalled one gets a fresh worker, never a second PR; one nobody finishes closes with a reason. Your loop runs `/pr-housekeeping` on your own open PRs.

## Working

- **Hypertask gaps:** file one at once with `hypertask feedback` (see the `/hypertask` skill), then send him the link.
- **Bans live in lint:** a ban only in markdown is not a ban. A corrected mistake class is fixed there at the highest level: architecture, then lint or test, docs last. Add a row to its rule table.
- **Checks:** follow the pstack hillclimb playbook. Fix flaky checks per pstack tdd; never rerun to pass.
- **Finish line:** tickets waiting on Valentin or BlockedBy stay outside it.
- **Verification is pstack's:** follow pstack `create-verification-skill`, `maintain-verification-skill` and `poteto-mode/playbooks/shipping.md` step 1; where a bug costs most (money math, sync, retries, queues), `create-formal-verification-skill` and `maintain-formal-verification-skill`. House change: one free GitHub runner, or a cloud agent when a runner cannot. Every AI call in CI goes through Token Ladder `ladder-call` (https://github.com/valentinyeo/token-ladder#ci-model-calls). A corrected mistake becomes a lint or test, never a new CI gate.
- **Self-audit on load:** run `~/.claude/skills/pstack-diff/pstack-diff .`; clear every EXTRA in one PR until it exits 0. A new CI gate needs a house-file line naming its pstack sentence; otherwise it is EXTRA.
- **Server load:** before a worker, build or long test, run `~/.local/bin/vps-state --can-launch worker`; on HOLD start nothing and say so. Time-limit long commands.
- **Open source by default:** repos are public unless client data or secrets keep them private. Start one with `new-public-repo`, never GitHub's template or fork. No commit carries a real email.
- **GitHub billing:** it blocks only private repos. When checks fail with "recent account payments have failed", scan its history for secrets and client data, then make it public. A repo that must stay private waits: note it once on the ticket; never verify or merge around it.
- **Cloudflare:** host everything new there, each page included. Build the Rat Stack way (https://ratstack.sh): copy its floor, load its skills.
- **Long chats:** save the handover, then start a fresh chat with its loop on.

## Designing

Design work follows [designing.md](designing.md).

## Changing the rules

- **pstack first, write last:** look for the rule in pstack, then in the domain's stack. Add only the gap; name what you checked in the commit message.
- **Where a correction lands:** product rules stay in that repo; agent-wide rules land here (vstack). A check for either goes in vstack.

## Skill index

Hidden skills: read the path shown, since the Skill tool refuses them. Slash commands still work.

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
