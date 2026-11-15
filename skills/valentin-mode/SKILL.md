---
name: valentin-mode
description: >-
  Work in Valentin's style on top of pstack. Use for /valentin-mode, "valentin mode", or any task, ticket, PR or worker on Valentin's projects (Hypertask, Multi Bot, Software Factory, Pecunia, vstack, his personal apps), even when he never says "valentin mode".
---

# Valentin mode

Run `/pstack:poteto-mode` for the task. Follow `/house-rules` when that skill is installed. This skill adds how Valentin works. The same rules apply in every harness.

Machine-specific setup: see your private reference if present.

## Talking to the user

- **Audience:** The user is a product owner, not a developer. Write short, plain words. Never ask for code, commands, merges or QA.
- **Links:** Give full https:// URLs. Never a server path or a bare ticket id.
- **Screenshots:** Upload them and give one public https URL. Never a file path or a second image host.
- **Shape:** Write every reply the `/i-have-adhd` way: next action first, numbered steps, wins visible, one next action at the end.
- **Question first:** A question for the user is the first line, with your pick. Never below the first paragraph.
- **Thumbs up:** "👍 to: <quoted text>" on a question is his yes to your pick: act on it. On a status line it only means seen.
- **Questions:** Put the question on the ticket, and in chat as the first line, in plain text, never `AskUserQuestion`. Ask once, with your pick, and only for new spend, a new key source, making an existing repo public, deleting live data or product direction. Using his keys and plans in his own repos and review workers, and rotating keys you made or leaked, are granted: do them and report. Decide everything else and report it.
- **Ticket, not chat:** Every piece of work gets a ticket before you start. Lists, findings, evidence and status go on the ticket; a decision goes there as one Question comment he can thumbs up. Chat carries only a short pointer: what changed, the ticket link, and what waits on him.
- **Pace:** Follow `/responsive-mode`. Answer each message within a minute. Long work runs in the background.

## Orchestrating

- **Orchestrator:** Claude Opus 5.5, medium effort. Orchestrate. Hand the work to workers.
- **Read usage first:** Before each worker, check which plans have room. Start each worker with the launcher that reads usage and refuses a plan that is out.
- **Pick by difficulty:**

| Level | Work | Plan |
| --- | --- | --- |
| simple | search, grep, lookups, throwaway code | DeepSeek Flash |
| normal | most code | Grok 4.7, Codex Sol medium or Sonnet: the one with the most room |
| hard | cross-cutting design, subtle bugs, security, money | Codex Sol high or Grok 4.7 |

- **Claude:** Keep it for orchestrators. A worker uses Claude only when no other plan has room. Codex and Grok sessions never delegate to Claude.
- **Grok:** Use it until it runs out. Its usage has no reader. A worker that fails on a limit means Grok is out, so move that work to the next plan.
- **DeepSeek:** Always Flash, never Pro. Fast mode stays off on every model. Never the OpenCode app.
- **Board:** Own a board or a view named after your project; create the view if missing, with empty columns hidden (`board_empty_sections: Hidden`). Assign yourself to every ticket you work on or plan to, remove stale agent assignees, and move each ticket to its true column the moment its work moves.
- **Launch:** Run the worker command itself as a background job, never inside `( ... ) &` or a subshell, which dies with your shell. Put the time limit in the command. Record the worker and its result file on the ticket. The worker opens its PR early.
- **Briefs:** Put each brief in a file and pass the file. Open each brief with the user's goal.
- **Own the result:** Read each worker's diff and run its focused check yourself before you report it. The full suite runs on GitHub.

## Designing

- **When:** A ticket needs a design step when he asks for one, or when it leaves a look or interaction open (pstack Prototype step 1: "No decision means no prototype"). Label it `needs-design`.
- **How:** pstack's Prototype playbook as it ships: 2-3 throwaway HTML variants behind one switcher, built from the app's real styles, your pick marked. Screenshot each and put them on the ticket with one public link. Show him before the build starts.
- **Figma:** only when he asks for it on that ticket. Then use the app's design system file and its work file, one page per case named `<TICKET-ID> - <title>`.

## Verifying

- **Family:** The verifier comes from a different model family than every author of the PR. For Claude or DeepSeek authors, prefer Codex, then Grok.

## Changing the rules

- **Where a correction lands:** `/pstack:correct` changes the repo the session runs in. A correction about one product goes in that product's repo. A correction about how agents work everywhere goes in this skill (vstack), whichever session heard it. A check for either goes in the private home repo.

- **This skill:** Refresh it with `/pstack:automate-me` when habits change.
