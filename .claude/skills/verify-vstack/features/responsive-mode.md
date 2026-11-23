# A chat answers fast and still finishes the job

A fresh chat in responsive mode both answers every message fast and finishes the job. Valentin, 19 Nov 2026: replies were fast, but the jobs did not get done. Speed comes from timestamps; finishing comes from origin, never from the chat saying it pushed.

## Sub-features

- `loaded`: the skill body reached the chat, proved by a `# Responsive mode` marker in the transcript.
- `checks loaded`: each hook the skill's frontmatter declares ran, matched against Claude Code's debug log.
- `reply 1`: "what is 17 + 25?" sent at 25s is answered with 42 inside 60s.
- `reply 2`: "what is the capital of France?" sent at 40s is answered with Paris inside 60s.
- `separate`: the reply holding 42 does not also hold Paris, and the reverse. Text blocks sharing a message id count as one reply.
- `background`: the slow step ran as a harness-tracked background job (a Bash or Agent call with `run_in_background: true`). A command using `nohup`, `setsid`, `disown`, `tmux` or a single `&` fails, because nothing wakes the chat when that process ends.
- `slow step 1 ran`: `slow-report.sh` wrote `ran.txt` after its 90 second sleep.
- `pushed`: origin main holds `REPORT.md` with the random report line this run seeded.
- `--hard` adds `reply 3` at 100s, `reply 4` at 150s and `slow step 2 ran`, a second script that needs the first one's `REPORT.md`.

## How to get to it (user POV)

- Give a session in responsive mode a long job, then type a question before it ends.
- Ask for a job that ends in a push, chat with the session while it runs, then look at the remote without nudging it.
- Open the chat and check that responsive mode's rules arrived without the chat choosing to fetch them.

## Driving it with verify-vstack

Preconditions:

- `~/.local/bin/plan-pick --claude-helper` exits 0, because the test chat runs on Claude Sonnet. Exit 3 otherwise: try later, never bypass the gate.
- The skill under test has a `name: responsive-mode` frontmatter line, so `run` can rename it into the scratch repo, and a `# Responsive mode` heading, which is the marker `loaded` looks for.
- `run` copies the skill's whole folder, following symlinks, into both the scratch repo and the evidence folder, so a hook file the frontmatter names is never left behind.
- `reply-check.py` returns its reminder as `hookSpecificOutput.additionalContext` on each tool call until Valentin's newest message has a reply. It never sets `permissionDecision` or denies a call, and prints nothing once a reply exists. At Stop the same file reads the final reply: a reply that asks Valentin to merge, ship, approve or review a pull request gets the fix as `hookSpecificOutput.additionalContext` with event `Stop`, so the chat merges it itself per pstack shipping and asks him only a product question. It never blocks the turn. The matcher and the fix line live in `skills/hypertask-work/merge-ask`, shared with the board drain, so a product question still passes.

- **Real run.** Run `.claude/skills/verify-vstack/tools/responsive-mode/run`. It makes an evidence folder, a scratch repo with a bare origin holding `slow-report.sh` (a 90 second sleep and a random line), copies the skill in as `/responsive-mode-under-test`, and starts one headless Sonnet chat. The job lands at 0s, "what is 17 + 25?" at 25s, "what is the capital of France?" at 40s, and stdin stays open until the chat sits idle for 60s with no background task running or 15 minutes pass. Expect `VERDICT PASS`. One run costs 3 to 15 minutes and one small Sonnet chat.
- **Test this checkout instead.** Run `.claude/skills/verify-vstack/tools/responsive-mode/run --skill skills/responsive-mode/SKILL.md`.
- **Break run.** Run `.claude/skills/verify-vstack/tools/responsive-mode/run --break no-responsive-mode`: the same job with no skill. It may still pass, because the job is small, so treat it as a baseline and not a required FAIL. The grader's failure paths have their own tests.
- **Hard run.** Run `.claude/skills/verify-vstack/tools/responsive-mode/run --hard` for the two-step job. Budget up to 20 minutes.
- **Read the checks.** A reply is timed from the moment `drive.py` wrote the question to the first assistant text holding the answer. `plan.json` lists every message with its send second, and `chat.jsonl` gets one `{"sent": ..., "t": ...}` line per message and one `{"ev": ..., "t": ...}` line per event. A reply that answers in words ("forty-two") fails, because the grader looks for the digits.
- **Evidence.** Every run keeps `~/.local/state/verify-responsive-mode/<run-id>/`: `meta.json`, `chat.jsonl`, `plan.json`, `spec.json`, `skill-under-test.md`, `skill-under-test/`, `transcript.jsonl`, `debug.log`, `ran.txt`, `pushed-report.md`, `origin-log.txt`, `verdict.txt` and `verdict.json`. Paste `verdict.txt` on a PR, never the raw chat.
- **Regrade a saved run.** Run `.claude/skills/verify-vstack/tools/responsive-mode/grade.py ~/.local/state/verify-responsive-mode/<run-id>`, which pays for no new chat.
- **Cleanup.** `run` deletes only the two folders it made with `mktemp`, never the evidence folder. `--keep` leaves them.

## Gotchas

- Exit 3 means Claude is ahead of pace. Treat it as a gate, not a failure to work around.
- `loaded` fails when the skill body never reached the chat: check the `name: responsive-mode` line the rename matches.
- Every reply check fails with no assistant text in the log: read the `.stderr` file next to `chat.jsonl`, usually the login or the model name.
- Headless runs skip the server's reply-first guard, which watches interactive chats only. This proves the skill, not the guard.
- A headless chat queues a mid-turn message and answers it at the next tool result, so one foreground step over 60 seconds fails `reply 1`. That is the whole point.
- A chat that ends its turn with a detached process never wakes up. The driver then closes after 60 idle seconds and `pushed` fails.
- The report line is random per run, so an old commit or an earlier run's line cannot pass.
- Two runs at once must not write the same file. The job text sends every temporary file into the run's own working folder, and a report line belonging to the other run fails `pushed`.
- The transcript is no record of a hook that printed nothing. Another hook on the box, a command left as `/reply-check.py` by an unset `$CLAUDE_PLUGIN_ROOT`, a hook named only in chat text, and a chat that never loaded the skill all count as no run.
