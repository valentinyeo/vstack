---
name: responsive-mode
description: "responsive mode;stay responsive;answer me while you work;like grok. /responsive-mode: keep the chat free while work runs. Long steps go to the background, new messages get answered at once. Use when Valentin says responsive mode, or a session ignores his messages while busy."
---

# Responsive mode

Valentin, 2026-11-07, after a session sat silent on a 400 second check while he asked "are u there?":

> save it in a skill called responsive mode so that I can quickly instruct sessions where I need this responsive style of talking

Same idea as Grok Build: work runs out of the way, the chat stays free.

For the rest of this session:

1. Any step that may take over 30 seconds runs in the background: tests, builds, installs, CI watches, probes, big searches, subagents. Claude: `run_in_background`. Codex and hax: a background job. Never block the chat on it.
2. After starting background work, end the turn with one line: what runs, and what you do when it finishes.
3. A message arrives while work runs? Answer it at once. Do not wait for the work. Do not kill it.
4. Background work finishes? Pick it up, check the result, continue.
5. Foreground only when the next step cannot start without the result AND it takes under 30 seconds.
6. Keep replies short while work runs.

Test: give a long job, send "what are you doing?" after 20 seconds. Pass means an answer within seconds while the job keeps running.
