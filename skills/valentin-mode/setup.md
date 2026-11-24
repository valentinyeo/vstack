# Project setup

`./install` ships `hooks/run-hook`, every hook and its helpers together into `~/.claude/hooks/`. It migrates vstack registrations in global settings and this project's settings, leaving unrelated hooks alone. Skills with hook frontmatter get an installed view whose commands use the same launcher; their scripts stay linked to this checkout. Register long-chat once, globally. The long-chat and pacing hooks use `hooks/valentin_mode_loaded.py` to recognize an explicit skill load; chats that never loaded it remain untouched.

Use the launcher for every hook command. A missing or non-executable script produces one stderr warning, appends it to `~/.local/state/vstack/hook-missing.log`, and exits 0. An existing script keeps its own output and exit status, including an intentional block at 2.

```json
{ "command": "\"$HOME/.local/share/vstack/hooks/run-hook\" \"$HOME/.claude/hooks/long-chat.py\"" }
```

| Hook | Event | What it does | Where to wire it |
|---|---|---|---|
| `skill-update.py` | UserPromptSubmit | Moves `~/.local/share/vstack` to `origin/main` and runs its `./install`, at most once per ten minutes for the whole server, and tells a chat in any project when valentin-mode changed, handing it the new SKILL.md text so it re-reads without being asked. `install` registers it here, once. | global, once |
| `long-chat.py` | UserPromptSubmit, Stop, PreCompact (`auto`) | Hands a valentin-mode chat over before autocompact. Soft at 300k / hard at 400k on 1M chats (110k / 140k on 200k). Warn-only without a Multibot host. | global, once |
| `board-drain-guard.py` | UserPromptSubmit, Stop | Reads the chat's own loop state and its watcher's pulse. A watcher dead past three polls, or an unarmed loop, is named with the time and the exact re-arm command; a Stop is held until a watcher runs, at most three times. When dead over 10 minutes, sends Valentin one push notice per dead spell (ntfy or poteto session-mail) and records it in loop-state. Silent in a chat that never armed a loop. | global, once |

Keep existing hook entries. Remove per-project copies of the global hook so it runs once.

Run `scripts/check-hook-paths --root <projects-root>` to check your home settings and project settings without changing them. Missing files name their registration and the fix. CI runs `scripts/check-hook-paths --repo .` against shipped settings, merge snippets, skill frontmatter, examples and installer references. Fleet-report shows these failures; it never repairs another chat.

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
