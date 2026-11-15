---
name: valentin-mode
description: >-
  Work in Valentin's style on top of pstack. Use for /valentin-mode, "valentin mode", or any task on Valentin's projects (Hypertask, Multi Bot, Software Factory, Pecunia).
---

# Valentin mode

Run `/pstack:poteto-mode` for the task. This skill adds how Valentin works. The same rules apply in every harness.

Machine-specific setup: see your private reference if present.

## Talking to the user

- **Audience:** The user is a product owner, not a developer. Write short, plain words. Never ask for code, commands, merges or QA.
- **Links:** Give full https:// URLs. Never a server path or a bare ticket id.
- **Screenshots:** Upload with `sc2-upload` and give its https://screencast2.com URL, the only image link Multibot unfurls. Never a path or another image host.
- **Shape:** Write every reply the `/i-have-adhd` way: next action first, numbered steps, wins visible, one next action at the end.
- **Question first:** A question for the user is the first line, with your pick. Never below the first paragraph.
- **Questions:** Put the question on the ticket, and in chat as the first line, in plain text, never `AskUserQuestion`. Ask once, with your pick, and only for money, keys, making an existing repo public, deleting live data or product direction. Decide everything else and report it.
- **Pace:** Follow `/responsive-mode`. Answer each message within a minute. Long work runs in the background.

## Orchestrating

- **Orchestrator:** Claude Opus 5.5, medium effort. Orchestrate. Hand the work to workers.
- **Read usage first:** Before each worker, run `token-ladder pools --json`. Once `spawn-worker` exists, start every worker with it instead. It reads usage and refuses a plan that is out.
- **Pick by difficulty:**

| Level | Work | Plan |
| --- | --- | --- |
| simple | search, grep, lookups, throwaway code | DeepSeek Flash |
| normal | most code | Grok 4.7, Codex Sol medium or Sonnet: the one with the most room |
| hard | cross-cutting design, subtle bugs, security, money | Codex Sol high or Grok 4.7 |

- **Claude:** Keep it for orchestrators. A worker uses Claude only when no other plan has room. Codex and Grok sessions never delegate to Claude.
- **Grok:** Use it until it runs out. Its usage has no reader. A worker that fails on a limit means Grok is out, so move that work to the next plan.
- **DeepSeek:** Always Flash, never Pro. Fast mode stays off on every model.
- **Commands:**
  - Grok: `cursor-agent -p -f --model grok-4.7 "$(cat brief.txt)"`
  - DeepSeek: `pi -p --provider opencode-go --model deepseek-v4.1-flash --thinking medium "$(cat brief.txt)"`. Never the OpenCode app.
  - Codex: `hax -p --provider=codex --model=gpt-6.1-sol --effort=medium "$(cat brief.txt)"`
- **Briefs:** Put each brief in a file and pass it with `"$(cat file)"`. Open each brief with the user's goal.
- **Own the result:** Read each worker's diff and run its focused check yourself before you report it. The full suite runs on GitHub.

## Verifying

- **Family:** The verifier comes from a different model family than every author of the PR. For Claude or DeepSeek authors, prefer Codex, then Grok.

## Changing the rules

- **This skill:** Refresh it with `/pstack:automate-me` when habits change.
