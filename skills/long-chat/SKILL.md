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

2. **Handover file.** Write `~/.local/state/long-chat/<session_id>.md`. The first line must be: If valentin-mode is not loaded in this chat, read ~/.claude/skills/valentin-mode/SKILL.md in full first, then run /board-drain. In Google Antigravity (`agy`), type `/valentin-mode` instead of the Claude path once the shared vstack install has run on the server. Also record whether valentin-mode was loaded in the old chat. Then goal; tickets (full `https://` URLs); open PRs; running jobs; decisions made; next step; other chats this work talks to. Multibot types `/valentin-mode` as the first message after a fresh start when the old chat had it loaded (multiprompt PR 1162). Keep it under about 6000 characters.

3. **Queue fresh start.** Run `mp-fresh --handover <that file>`.
   - Exit **0**: write marker `~/.local/state/long-chat/<session_id>.queued` (empty file is fine), tell the user one line ("Starting fresh in this same chat, handover saved."), end the turn.
   - Exit **1** or **2**: run `failed-handover --reason <the reason mp-fresh printed>`. That files one ticket on this board under this chat's login; a repeat raises its count. Never put the handover in it.
   - Exit **3** (not under an agent host), command missing, or any other failure except **4**: write marker `~/.local/state/long-chat/<session_id>.nohost` (empty file is fine), tell the user once this chat is outside Multibot and keep working (warn only).
   - Exit **4**: write marker `~/.local/state/long-chat/<session_id>.queued`, end the turn (already queued).

   When Multibot later says "Fresh start failed", the long-chat hook already ran `failed-handover` once for it. Nothing else to do.

4. **Never** type `/clear` or ask the user to.

The handover path is the session id from hook input or environment. Multibot queues a Fresh start for this same chat when the current turn ends.