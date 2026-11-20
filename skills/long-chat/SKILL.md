---
name: long-chat
description: >-
  Hand off and start fresh before the chat grows too long. Use when the chat is too long,
  context is full, you need a hand off, or a fresh start in the same Multibot chat instead
  of autocompact or /clear.
---

# Long chat

Prior art: checked vstack skills (responsive-mode, board-drain, spawn-multibot-session, pstack recall), none fits because this skill is only the handover-and-mp-fresh flow when context is large, not looping, spawning, or recall.

Valentin-mode chats must hand off and restart in the same Multibot chat before context autocompacts. The hook nudges you at the soft limit and blocks further turns at the hard limit until you complete this flow. On a 1M-token window that is 300k warn and 400k hand off; on a 200k window it stays 110k / 140k (55% / 70% capped by those token limits).

## Steps

1. **Background work.** Finish or stop tracked background jobs (Agent or Bash `run_in_background`, `/loop`). Anything still running goes in the handover with how to pick it up.

2. **Handover file.** Write `~/.local/state/long-chat/<session_id>.md` with: goal; tickets (full `https://` URLs); open PRs; running jobs; decisions made; next step; other chats this work talks to. Keep it under about 6000 characters.

3. **Queue fresh start.** Run `mp-fresh --handover <that file>`.
   - Exit **0**: write marker `~/.local/state/long-chat/<session_id>.queued` (empty file is fine), tell the user one line ("Starting fresh in this same chat, handover saved."), end the turn.
   - Exit **3** or command missing: tell the user once this chat is outside Multibot and keep working (warn only).
   - Exit **4**: write the same `.queued` marker, end the turn (already queued).

4. **Never** type `/clear` or ask the user to.

The handover path is the session id from hook input or environment. Multibot queues a Fresh start for this same chat when the current turn ends.