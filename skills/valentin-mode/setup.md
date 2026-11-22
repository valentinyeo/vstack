# Project setup

Each hook lives in vstack's `hooks/` folder; `./install` links it into `~/.claude/hooks/`. Register long-chat once, globally. The long-chat and pacing hooks use `hooks/valentin_mode_loaded.py` to recognize an explicit skill load; chats that never loaded it remain untouched.

Write registered commands to fail open when their file is missing. A bare `python3` call exits 2 on a missing link, which Claude Code reads as a block. Use this shape:

```json
{ "command": "sh -c 'f=\"$HOME/.claude/hooks/long-chat.py\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\"'" }
```

| Hook | Event | What it does | Where to wire it |
|---|---|---|---|
| `long-chat.py` | UserPromptSubmit, Stop, PreCompact (`auto`) | Hands a valentin-mode chat over before autocompact. Soft at 300k / hard at 400k on 1M chats (110k / 140k on 200k). Warn-only without a Multibot host. | global, once |

Keep existing hook entries. Remove per-project copies of the global hook so it runs once.

Worker selection belongs to `~/.local/bin/plan-pick --run`; Claude helpers use its `--claude-helper` decision. Capacity belongs to the launcher's `vps-state --can-launch worker` check. Neither needs another shell-command parser in a chat hook.

Wait for this PR's checks with `~/.local/share/vstack/tools/gh-wrapper/wait-checks <repo> <pr>` as a tracked background command, never `&` or nohup. The GitHub wrapper owns caching and rate limits at the API boundary.

Update the shared checkout explicitly from `~/.local/share/vstack`, then run its `./install`. Never run an install from a worktree to repoint other chats at an unmerged branch.
