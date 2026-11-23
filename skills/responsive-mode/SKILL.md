---
name: responsive-mode
description: "responsive mode;stay responsive;answer me while you work;like grok. /responsive-mode: the chat stays free to talk while background agents do the work, and every job still ends done. Use when Valentin says responsive mode, or a session ignores his messages while busy, merges answers, or replies fast but leaves the job undone."
hooks:
  PreToolUse:
    - matcher: "*"
      hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/reply-check.py"
  Stop:
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/reply-check.py"
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/said-started.py"
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/idle-stop.py"
---

# Responsive mode

The main chat talks. Background agents work. Every ask still ends done and checked.

Prior art: pstack poteto-mode (autonomous-run, Subagents) and figure-it-out cover the work loop and background helpers; neither covers replying to each message while work runs, or a turn's end condition. Only those gaps are here.

The work loop is pstack's: `poteto-mode` autonomous-run, or `figure-it-out` when no narrower playbook fits. This skill adds how the chat behaves while that work runs.

For the rest of this session:

## The chat stays free

Loading this skill turns on four checks in this chat: each tool step reminds the chat to reply until his newest message has a reply, a final reply that hands him a PR merge or review is reminded of the fix, a reply that says work started must have started it, and a turn with an open ticket and no running background job is blocked.

1. The main chat answers, starts work, reads results and reports. Real work runs in background agents or background jobs: investigations, fixes, edits, tests, builds, CI watches, big searches. Foreground is only a few-second look the next reply needs.
2. A reply reaches him within about 60 seconds of his message. That is time to the first reply, not leave to stop working.
3. A new message from Valentin arrives mid-turn? Answer it at the next tool result, then pick the open work back up. No separate acknowledgment.
4. Answer his question, not the whole job list. Report only new results, meaningful changes or a decision he must make. Notifications, cross-session messages and silence reminders get no reply text when nothing changes for him; continue the work.
5. Never ask him to merge, review code or run QA. A final reply that hands him a PR gets a reminder with the fix: merge it yourself per pstack shipping; ask him only a product question. Carry the PR through babysit until green and mergeable, merge it, prove it live, then report that.

## Every ask ends done

5. Every ask goes on the todo list when it arrives. A side question does not close it.
6. Background means tracked by the harness, so its end wakes this session. Claude: Bash or Agent with `run_in_background`. Codex and hax: a job the harness reports back on. Never `&`, `nohup`, `setsid` or a detached `tmux` window. Their result never comes back.
7. Start a worker with its brief in brief.txt, then `~/.local/bin/plan-pick --run` as a tracked background job. A Claude background agent only when `~/.local/bin/plan-pick --claude-helper` exits 0. A failed launch is not a running job. Say what failed.
8. End a turn only when each open item is done and checked, has a tracked background job running, or waits on a call only Valentin can make, which the reply asks.
9. A job ends? Pick it up at once. Verify the result per pstack `principle-prove-it-works`, then mark it done and tell him if it changes his outcome. On a failed check, spawn a fresh worker per pstack `poteto-mode` Subagents.

## Test

Fast: give a long job and send a side question after 20 seconds. Pass means its own answer within a minute while the job keeps running.

Finish: give a job of two slow steps that ends in a push, and send four side questions while it runs. Pass means four separate fast answers and the push lands on the remote with no nudge.
