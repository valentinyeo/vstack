---
name: deep-work
description: "/deep-work [task]: hand a big task to this session and walk away for 60 to 90 minutes. Proves first that it can check its own work, asks every question in one go, then runs alone through /do until done, parks what it cannot finish and ends with a two minute report. Use for 'deep work', 'run without me', 'I'm away for an hour', or any big prompt the owner wants finished alone."
---

# /deep-work

The task is the text after `/deep-work`. With none, use the latest task in this conversation.

Shape, after Cal Newport's book [Deep Work](https://calnewport.com/deep-work-rules-for-focused-success-in-a-distracted-world/): the owner spends ten focused minutes up front, then gets ninety minutes of silence, then reads one short report. All talk happens at the start and at the end.

The one thing the agent must confirm up front: it can test and QA its own output. Verification is a big part of everything.

## Needs

- [do](../do/SKILL.md) from this repo, with its own needs: [pstack](https://github.com/cursor/plugins/tree/main/pstack) and [unlazy](https://github.com/Leonxlnx/unlazy).

## Phase A: contract, with the owner present

Finish all of Phase A before any work. Keep it to about ten minutes of the owner's time.

### A1. Goal

Restate the goal, the problem and the smallest change that meets it, in plain words.

### A2. Verification first

No work starts until you have shown you can prove the result yourself.

1. Write done as a check that can fail: a test, a command, a page state, a live number, a ticket column. Never "looks good".
2. Name the exact check for every outcome: the command, the URL plus what must show, or the test name.
3. Run each check now. It must run, and it must fail today for the right reason. A check that already passes proves nothing.
4. Confirm you have the access each check needs: test login, browser, CI, logs, deploy record. Fetch keys the way your project's rules say. Missing access is a question for round 1 of A3.
5. No check possible? Building the checker becomes the first work step. Still impossible? Say so in A3 and ask for the owner's acceptance test instead. This is the only reason Phase B may not start.

Show the owner the table: outcome, check, today's result.

### A3. Questions, all at once

Ask every question now, so none are needed later. Rounds follow Matt Pocock's [grilling skill](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md), cut down to the owner's calls:

- Ask only what the owner alone decides: product and taste, money, keys, going public, deleting real data, needing them at their computer. Decide every technical fork yourself and log it. Look up facts yourself, with a subagent if needed.
- One round, five questions at most, in plain words. Number each and give your recommendation. Word it so "yes" accepts all.
- A second round only when an answer opens a new owner call.
- Nothing to ask? Say "No questions" and go on.

### A4. Lock the contract

Write the contract at the top of the first ticket (or the task list, per `/do` step 0):

- Goal, in one sentence.
- The verification table from A2.
- Must stop for: money or paid calls, deleting real data, going public, keys, anything irreversible. Add any the owner named.
- Decides alone: everything else, logged.
- Time box: the owner's number, default 90 minutes.
- Where the report lands.

Then say: "Going quiet now. Report in about N minutes." Start Phase B without waiting for a reply unless the owner asked to approve the contract.

## Phase B: run alone

Run `/do` on the task with the contract as input, in pstack autonomous-run mode. The A2 checks become unlazy gates, one per outcome. Add these rules on top:

- **No questions.** Never end a turn with a question, an offer, "say go" or a pick-A-or-B. Pick your recommendation, log it, do it. Asking permission for reversible work is the most common avoidable stop.
- **Check before asking for a hand.** About to ask the owner to sign in, restart or install? First test that it is really needed. Then park it and keep working.
- **Waiting is not stopping.** CI or a deploy running: keep one slow watcher (5 minutes or more), work other parts meanwhile, act on the result.
- **Verify every unit before the next.** Run its check, read the real output, and only then move on. A unit counts as done only with check output, never on your own word.
- **Verify like a user.** For anything a person sees, open it in the browser as that person and look. For anything that ships, check the live system, not only the branch.
- **Log decisions.** Each call you made for the owner gets one line: what, why, how to undo.
- **Park, never wait.** Stuck after two different attempts (pstack Attack the Premise), a must-stop call, or a tool failure past one workaround: blocked state on that ticket, one line why, what would unblock it. Then keep working the other parts.
- **Running out of context or time.** pstack pause-safely, then Phase C.

## Phase C: two minute report

Run unlazy's final audit, then reply in short plain sentences:

1. **Done.** One line per outcome with its proof link: test run, screenshot, live URL, ticket.
2. **Decisions I made.** The decision log, one line each.
3. **Parked.** Each with the reason and the one thing needed from the owner.
4. **Numbers.** Minutes run alone, gates met out of total.

Never report an outcome as done without its check passing in this session.
