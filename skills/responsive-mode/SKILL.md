---
name: responsive-mode
description: "responsive mode;stay responsive;answer me while you work;like grok. /responsive-mode: keep the chat free while work runs. Long steps go to the background, new messages get answered at once, one reply per message. Use when Valentin says responsive mode, or a session ignores his messages while busy or merges answers."
---

# Responsive mode

Valentin, 2026-11-07, after a session sat silent on a 400 second check while he asked "are u there?":

> save it in a skill called responsive mode so that I can quickly instruct sessions where I need this responsive style of talking

Valentin, 2026-11-13, after a turn chained 15 to 25 foreground steps (each under 30 seconds) and answered his mid-turn messages as one long reply at the end:

> your answers take a very long time and I only get combined answers, whereas I would prefer you answer as fast as possible for the individual questions.

Same idea as Grok Build: work runs out of the way, the chat stays free.

pstack owns the work loop through `poteto-mode` autonomous-run. Use `figure-it-out` when no narrower playbook fits. The poteto-mode Subagents section requires background helpers. This skill adds replies within one minute. Each message gets its own reply. A new message stops the foreground chain.

For the rest of this session:

1. Budget per turn, not per step. A reply reaches him within about 60 seconds of his message. More work than that goes to a background task or a worker. Many short foreground steps in a chain count as one long step.
2. Any single step that may take over 30 seconds runs in the background: tests, builds, installs, CI watches, probes, big searches, workers. Claude: `run_in_background`. Codex and hax: a background job. Never block the chat on it.
3. A new message arrives mid-turn? Stop the chain at the next tool result. Reply to that message on its own. Then continue the work in the background. Do not kill running work.
4. One message, one reply. Never merge answers to several messages into one reply.
5. Investigations and multi-step fixes go to a background worker by default. Start it with `spawn-worker` (Grok, DeepSeek Flash or Codex). Never a Claude subagent: Claude is kept for orchestrators. The chat thread only reads results and reports.
6. After starting background work, end the turn with one line: what runs, and what you do when it finishes.
7. Background work finishes? Pick it up, check the result, continue.
8. Foreground only when the next step cannot start without the result AND the whole turn stays under 60 seconds.
9. Keep replies short while work runs.

Test: give a long job, send "what are you doing?" after 20 seconds. Pass means an answer within seconds while the job keeps running. Also send two questions 10 seconds apart; pass means two separate replies, each within a minute.
