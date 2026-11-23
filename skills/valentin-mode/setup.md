# Project setup

Each hook lives in vstack's `hooks/` folder; `./install` links it into `~/.claude/hooks/`. Register long-chat once, globally. The long-chat and pacing hooks use `hooks/valentin_mode_loaded.py` to recognize an explicit skill load; chats that never loaded it remain untouched.

Write registered commands to fail open when their file is missing. A bare `python3` call exits 2 on a missing link, which Claude Code reads as a block. Use this shape:

```json
{ "command": "sh -c 'f=\"$HOME/.claude/hooks/long-chat.py\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\"'" }
```

| Hook | Event | What it does | Where to wire it |
|---|---|---|---|
| `skill-update.py` | UserPromptSubmit | Moves `~/.local/share/vstack` to `origin/main` and runs its `./install`, at most once per ten minutes for the whole server, and tells a chat when valentin-mode changed so it re-reads it. | global, once |
| `long-chat.py` | UserPromptSubmit, Stop, PreCompact (`auto`) | Hands a valentin-mode chat over before autocompact. Soft at 300k / hard at 400k on 1M chats (110k / 140k on 200k). Warn-only without a Multibot host. | global, once |

Keep existing hook entries. Remove per-project copies of the global hook so it runs once.

Worker selection belongs to `~/.local/bin/plan-pick --run`; Claude helpers use its `--claude-helper` decision. Capacity belongs to the launcher's `vps-state --can-launch worker` check. Neither needs another shell-command parser in a chat hook.

Wait for this PR's checks with `~/.local/share/vstack/tools/gh-wrapper/wait-checks <repo> <pr>` as a tracked background command, never `&` or nohup. The GitHub wrapper owns caching and rate limits at the API boundary.

`skill-update.py` keeps the shared checkout current on its own, so a merged rule reaches this chat within ten minutes of a prompt. Run the update by hand from `~/.local/share/vstack` when you need it now: `git fetch && git checkout --detach origin/main && ./install`. Never run an install from a worktree to repoint other chats at an unmerged branch.

## Google Antigravity (`agy`)

Antigravity loads customizations from [Customization discovery](https://antigravity.google/docs/customization-discovery/) and [Hooks](https://antigravity.google/docs/hooks/). `./install` links vstack skills into `~/.agents/skills/`, `~/.gemini/antigravity-cli/skills/` (CLI priority), and `~/.gemini/config/skills/`, then merges `config/antigravity-hooks.json` into `~/.gemini/config/hooks.json`. Slash `/valentin-mode` comes from the linked `SKILL.md`.

| Event | Hook | Notes |
|---|---|---|
| PreToolUse | valentin-mode context.py | Version line + responsive rules once |
| Stop | said-started, no-bare-ids, idle-stop | Same scripts as Claude skill frontmatter |

**Hooks agy does not run today** (Claude Code only): `long-chat.py` (`UserPromptSubmit`, `PreCompact`), `pacer-guard.py`, `test-timeout-guard.py`, `pstack-new-gates.py`, `launch-gate.py`, `vps-state` SessionStart, and every other entry in `~/.claude/settings.json`. Handoff before context fills still needs a human move or Multibot; agy has no `PreCompact`.

After a Multibot handover into agy, start with `/valentin-mode` when the old chat had it loaded. Proof: the first assistant reply names the `valentin-mode v…` line from `context.py`.

Data dir for hook payloads: `~/.gemini/antigravity-cli` (per Antigravity docs). Config dir: `~/.gemini/config/`.
