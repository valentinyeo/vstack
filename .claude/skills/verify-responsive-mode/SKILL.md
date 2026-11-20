---
name: verify-responsive-mode
description: >-
  Prove that a fresh Claude Code chat in responsive mode both answers every message fast and finishes the job. Starts one headless test chat with the skill, hands it a 90 second job that ends in a git push, asks two side questions mid-job, then grades the timestamps and the pushed commit PASS or FAIL. Use after any change to skills/responsive-mode, and as the proof on such a PR.
---

# Verify responsive mode

Valentin, 19 Nov 2026: replies were fast, but the jobs did not get done. Responsive mode makes two promises, so two families of check sit behind this one run. Speed comes from timestamps. Finishing comes from origin, never from the chat saying it pushed.

Prior art: pstack create-verification-skill and maintain-verification-skill, plus this repo's verify-valentin-mode and verify-reconcile. Those say how to build a check. None of them is a check that a fresh chat in responsive mode replies fast and still finishes the job, so this is the verify-<app> skill create-verification-skill asks for, with responsive mode as the app.

Read features/README.md for the map.

`checks loaded` reads the transcript's `hook_*` entries to prove the skill's hooks ran.

## Launch

```sh
.claude/skills/verify-responsive-mode/run                                # installed copy, expect VERDICT PASS
.claude/skills/verify-responsive-mode/run --skill skills/responsive-mode/SKILL.md   # this checkout
.claude/skills/verify-responsive-mode/run --break no-responsive-mode     # same job, no skill
```

The order of work:

1. Gate: plan-pick --claude-helper must exit 0, because the test chat runs on Claude Sonnet. Else exit 3.
2. Makes an evidence folder under ~/.local/state/verify-responsive-mode/, suffixed when the name is taken, and copies the skill under test into it.
3. Makes a scratch repo with a bare origin on disk. It holds the slow report script, which sleeps 90 seconds and prints a random line.
4. Copies that whole folder into the repo under another name, following symlinked hooks, so the chat calls it /responsive-mode-under-test and your installed copy stays untouched.
5. drive.py starts one headless Sonnet chat. Job at 0s, "what is 17 + 25?" at 25s, "what is the capital of France?" at 40s. stdin stays open until the chat sits idle for 60s with no background task running, or 15 minutes pass. The job tells the chat to keep every temporary file inside its own working folder.
6. Saves origin's REPORT.md, grades, then deletes its own scratch folders. --keep leaves them.

One run costs 3 to 15 minutes and one small Sonnet chat.

## Doctor

- Exit 3: Claude is ahead of pace. Try later, never bypass the gate.
- loaded fails: the skill body never reached the chat. Check that the skill has a name: responsive-mode line for the rename to match.
- checks loaded fails: the skill's hooks never ran.
- Every reply check fails and the log holds no assistant text: read the .stderr file next to chat.jsonl. Usually the login or the model name.

## Drive

Only the run script drives. To regrade a saved run without paying for a new chat:

```sh
.claude/skills/verify-responsive-mode/grade.py ~/.local/state/verify-responsive-mode/<run-id>
```

## Evidence

Every run keeps a folder under ~/.local/state/verify-responsive-mode/ with these files:

| File | What it proves |
| --- | --- |
| meta.json | which skill was tested, with which flags, at which commit |
| chat.jsonl | every event and its arrival second, plus each message sent |
| plan.json, spec.json | what was sent and what the grade expects |
| skill-under-test.md | the exact skill text tested |
| skill-under-test/ | the whole skill folder tested, hooks and their files included |
| transcript.jsonl | the chat's own transcript, where the expanded skill text appears |
| ran.txt, ran2.txt | the slow steps finished |
| pushed-report.md, origin-log.txt | what main holds on origin |
| verdict.txt, verdict.json | one PASS or FAIL line per check, then the verdict |

Paste verdict.txt on a PR. Never the raw chat.

## Cleanup

The run script deletes only the two folders it made with mktemp, never the evidence folder. The chat's own temporary files stay inside its working folder, which is one of those two.

## Gotchas

- Headless runs skip the server's reply-first guard, which watches interactive chats only. This proves the skill, not the guard.
- A break run shows what Sonnet does without the skill. It may still pass, because the job is small. Treat it as a baseline, not a required FAIL. The grader's failure paths have their own tests.
- Two runs at once stay out of each other's way, and the grade excuses no collision: a report line belonging to the other run fails pushed.
- --hard runs the two-step job: a second 90 second script that needs the first one's REPORT.md, plus two more side questions at 100s and 150s. Budget up to 20 minutes.
