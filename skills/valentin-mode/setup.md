# Project setup

`./install` ships `hooks/run-hook`, every hook and its helpers together into `~/.claude/hooks/`. It migrates vstack registrations in global settings and this project's settings, leaving unrelated hooks alone. Skills with hook frontmatter get an installed view whose commands use the same launcher; their scripts stay linked to this checkout. Register long-chat once, globally. The long-chat and pacing hooks use `hooks/valentin_mode_loaded.py` to recognize an explicit skill load; chats that never loaded it remain untouched.

Use the launcher for every hook command. A missing or non-executable script produces one stderr warning, appends it to `~/.local/state/vstack/hook-missing.log`, and exits 0. An existing script keeps its own output and exit status, including an intentional block at 2.

```json
{ "command": "\"$HOME/.local/share/vstack/hooks/run-hook\" \"$HOME/.claude/hooks/long-chat.py\"" }
```

| Hook | Event | What it does | Where to wire it |
|---|---|---|---|
| `skill-update.py` | UserPromptSubmit | Moves `~/.local/share/vstack` to `origin/main` and runs its `./install`, at most once per ten minutes for the whole server, and tells a chat in any project when valentin-mode changed, handing it the new SKILL.md text so it re-reads without being asked. `install` registers it here, once. | global, once |
| `long-chat.py` | UserPromptSubmit, Stop, PreCompact (`auto`) | Hands a valentin-mode chat over before autocompact. Soft at 110k / hard at 150k on 1M chats (110k / 140k on 200k). Warn-only without a Multibot host. | global, once |
| `board-drain-guard.py` | UserPromptSubmit, Stop | Reads the chat's own loop state and its watcher's pulse. A watcher dead past three polls, or an unarmed loop, is named with the time and the exact re-arm command; a Stop is held until a watcher runs, at most three times. When dead over 10 minutes, sends Valentin one push notice per dead spell (ntfy or poteto session-mail) and records it in loop-state. Silent in a chat that never armed a loop. | global, once |
| `ask-first-guard.py` | Stop | Holds a reply that asks Valentin how or whether to do something that is not his call, and a reply whose question sits below the first paragraph. A flag switch question, `Switch <flag-key> to <mode>`, passes: Hypertask's `ht-flag` refuses a switch without it, and a gate a product repo enforces in code wins inside that product. | global, once |

Keep existing hook entries. Remove per-project copies of the global hook so it runs once.

Run `scripts/check-hook-paths --root <projects-root>` to check your home settings and project settings without changing them. Missing files name their registration and the fix. CI runs `scripts/check-hook-paths --repo .` against shipped settings, merge snippets, skill frontmatter, examples and installer references. Fleet-report shows these failures; it never repairs another chat.

Worker selection belongs to `~/.local/bin/plan-pick --run`; Claude helpers use its `--claude-helper` decision. Capacity belongs to the launcher's `vps-state --can-launch worker` check. Neither needs another shell-command parser in a chat hook.

Wait for this PR's checks with `~/.local/share/vstack/tools/gh-wrapper/wait-checks <repo> <pr>` as a tracked background command, never `&` or nohup. The GitHub wrapper owns caching and rate limits at the API boundary.

`skill-update.py` keeps the shared checkout current on its own, so a merged rule reaches this chat within ten minutes of a prompt. Run the update by hand from `~/.local/share/vstack` when you need it now: `git fetch && git checkout --detach origin/main && ./install`. Never run an install from a worktree to repoint other chats at an unmerged branch.

## The pacer rule on every harness

An owner chat, the one Valentin talks to, only writes briefs and starts code workers through `~/.local/bin/plan-pick --run`. `hooks/pacer-guard.py` refuses a code edit in the chat itself, and allows the workers plan-pick starts because plan-pick unsets `MULTIPROMPT_TAB` for them. `./install` puts that rule in front of every harness a chat can switch to, from one rule text, `skills/valentin-mode/references/pacer-rule.md`.

| Harness | Rule file | Hook wiring | Blocking format |
|---|---|---|---|
| Claude Code | none | `PreToolUse` in `~/.claude/settings.json`, `pacer-guard.py` | exit 2 + stderr |
| Codex | `~/.codex/AGENTS.md` | `PreToolUse` in `~/.codex/hooks.json`, `pacer-guard.py --harness codex` | exit 2 + stderr |
| Antigravity (`agy`) | `~/.gemini/GEMINI.md` | `PreToolUse` matcher `*` in `~/.gemini/config/hooks.json`, `pacer-guard.py --harness agy` | `{"decision": "deny"}` on stdout |

`scripts/install-pacer-rules.py` writes the rule into a marked block:

```
<!-- vstack:pacer-rule:begin (written by vstack install ...) -->
...
<!-- vstack:pacer-rule:end -->
```

A second install replaces that block and nothing else; whatever else is in those files stays. It merges `config/codex-hooks.json` into `~/.codex/hooks.json`, appending the guard once and keeping every hook already registered there. Antigravity's entry ships in `config/antigravity-hooks.json`.

Codex's `PreToolUse` payload and exit codes match Claude Code's, so the only translation is tool names: `exec_command` is a shell and `apply_patch` names its files in a patch. Antigravity sends `{"toolCall": {"name", "args"}}` in camelCase and blocks on a JSON decision, so the guard reads `run_command`'s `CommandLine` and a write tool's `TargetFile`, and prints the decision agy acts on. Unknown tools pass, as they do on Claude Code.

Heavy-Bash pacing and the other entries in the hook table above stay Claude Code only: on Codex and Antigravity they key off a Claude transcript, which those harnesses do not write.

## The mode on every harness a chat can switch to

Multibot's "Switch AI" moves a chat to another harness. Only Claude Code runs a skill's frontmatter hook, so a switched chat used to drop valentin-mode: no version line, and `loop-state status` said "not armed" for every switched chat (VSTA-305). `hooks/harness-start.py` hands the mode to the harness itself, and `./install` wires it with a 5-second timeout that fails open:

| Harness | Config | Event | Command |
|---|---|---|---|
| Codex | `~/.codex/hooks.json` | `SessionStart` | `run-hook harness-start.py --harness codex --event start` |
| Codex | `~/.codex/hooks.json` | `UserPromptSubmit` | `run-hook harness-start.py --harness codex --event prompt` |
| Antigravity (`agy`) | `~/.gemini/config/hooks.json` (`vstack-valentin-mode`) | `PreInvocation` | `run-hook harness-start.py --harness agy --event start` |
| Pi | `~/.pi/agent/extensions/vstack-valentin-mode.ts` | `session_start` | `python3 ~/.claude/hooks/harness-start.py --harness pi --event start` |

The start line carries the version line from `version.sh`, the order to read `~/.claude/skills/valentin-mode/SKILL.md` in full, and, when this chat drains a board, the one command that arms its loop the high-latency way: one recurring job on `~/.local/bin/plan-pick --loop-interval` recorded with `loop-state arm`, because no harness but Claude Code has the background watcher job. The prompt line repeats the same re-arm order while `loop-state status` says not armed, at most once every ten minutes per session. The chat's name, board and label come from board-drain itself (`board-drain-guard`'s tab and announce read, `loop-state own_record`, then the `Hypertask board:` line in the project notes).

Antigravity has no start event, so its entry rides `PreInvocation` and says its start line once per conversation. Pi has no hook file: its extension asks the same script for the text at `session_start` and queues it as context, and it has no prompt-time check, so a Pi chat hears the re-arm order once at session start and again whenever the session restarts.

`scripts/install-mode-start-hook.py` merges the Codex entries: a second install writes nothing and every hook already registered there stays. Antigravity's entry ships in `config/antigravity-hooks.json`; the Pi extension is `skills/valentin-mode/pi-start.ts`, linked into `~/.pi/agent/extensions/`.

## Token Ladder prompt hook

When `token-ladder` is installed (resolved on `PATH` or in `~/.local/bin`), `./install` wires its prompt hook with a 5-second timeout through `scripts/install-ladder-hook.py`, preserving unrelated hooks and skipping cleanly when `token-ladder` is absent.

| Harness | Config | Event | Command |
|---|---|---|---|
| Claude Code | `~/.claude/settings.json` | `UserPromptSubmit` | `run-hook <token-ladder> hook-prompt` |
| Codex | `~/.codex/hooks.json` | `UserPromptSubmit` | `run-hook token-ladder-prompt.py --harness codex --ladder <token-ladder>` |
| Antigravity (`agy`) | `~/.gemini/config/hooks.json` (`vstack-token-ladder`) | `PreInvocation` | `run-hook token-ladder-prompt.py --harness agy --ladder <token-ladder>` |

Claude reads plain stdout from `token-ladder hook-prompt`. Codex expects `hookSpecificOutput.additionalContext` JSON and Antigravity expects `injectSteps` JSON; `hooks/token-ladder-prompt.py` wraps stdout into each harness's shape and fails open to `{}`. Because Antigravity fires `PreInvocation` before every model call in a turn, the `agy` adapter deduplicates by `(conversationId, initialNumSteps)` so each prompt gets the usage line once.

## Google Antigravity (`agy`)

Antigravity loads customizations from [Customization discovery](https://antigravity.google/docs/customization-discovery/) and [Hooks](https://antigravity.google/docs/hooks/). `./install` links vstack skills into `~/.agents/skills/`, `~/.gemini/antigravity-cli/skills/` (CLI priority), and `~/.gemini/config/skills/`, then merges `config/antigravity-hooks.json` into `~/.gemini/config/hooks.json`. Slash `/valentin-mode` comes from the linked `SKILL.md`.

| Event | Hook | Notes |
|---|---|---|
| PreInvocation | token-ladder-prompt.py `--harness agy` | Token Ladder prompt line once per turn when installed |
| PreToolUse | valentin-mode context.py | Version line + responsive rules once |
| PreToolUse | pacer-guard.py `--harness agy` | An owner chat's code edit is denied, a plan-pick worker passes |
| Stop | said-started, no-bare-ids, idle-stop | Same scripts as Claude skill frontmatter |

**Hooks agy does not run today** (Claude Code only): `long-chat.py` (`UserPromptSubmit`, `PreCompact`), `test-timeout-guard.py`, `pstack-new-gates.py`, `launch-gate.py`, `vps-state` SessionStart, and every other entry in `~/.claude/settings.json`. Handoff before context fills still needs a human move or Multibot; agy has no `PreCompact`.

After a Multibot handover into agy, start with `/valentin-mode` when the old chat had it loaded. Proof: the first assistant reply names the `valentin-mode v…` line from `context.py`.

Data dir for hook payloads: `~/.gemini/antigravity-cli` (per Antigravity docs). Config dir: `~/.gemini/config/`.
