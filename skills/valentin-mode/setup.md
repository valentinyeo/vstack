# Project setup

Each hook lives in vstack's `hooks/` folder; `./install` links it into `~/.claude/hooks/`. Wire the lane hooks once, globally.

Write every registered command to fail open when its file is missing, and to block only when the hook itself says so. A bare path, or `python3 $HOME/.claude/hooks/hook.py`, exits 2 on a missing or broken link, and Claude Code reads exit 2 as a block. Use this shape, which exits 0 when the file is gone and passes the exit code through when it is there:

```json
{ "command": "sh -c 'f=\"$HOME/.claude/hooks/plan-pick-only.py\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\"'" }
```

| Hook | Event | What it does | Where to wire it |
|---|---|---|---|
| `plan-pick-only.py` | PreToolUse, Bash | Code workers start only through `~/.local/bin/plan-pick --run`. Acts only in a valentin-mode chat. | global, once |
| `claude-helper-gate.py` | PreToolUse, Agent and Task | A Claude helper starts only when `plan-pick --claude-helper` allows it. Acts only in a valentin-mode chat. | global, once |
| `launch-gate.py` | PreToolUse, Bash | No worker, build or test starts while vps-state says HOLD; `LAUNCH_GATE=off` is Valentin's override. | each project |
| `skill-update.py` | UserPromptSubmit | Keeps the shared skills current and says when valentin-mode changed, so the chat re-reads it. | each project |
| `gh-watch-guard.py` | PreToolUse, Bash | `gh --watch` and gh poll loops sleeping under 60 s are blocked. CI waits through `~/.local/share/vstack/tools/gh-wrapper/wait-checks <repo> <pr>` as a tracked background command (Bash `run_in_background`), not `&` or nohup. | each project |
| `long-chat.py` | UserPromptSubmit, Stop, PreCompact (`auto`) | Valentin-mode chats hand off via mp-fresh before autocompact. Soft at 300k / hard at 400k on 1M chats (110k / 140k on 200k). Soft adds context; hard blocks Stop and auto PreCompact. Warn-only without a Multibot host. Acts only when valentin-mode is loaded. | global, once |

Run `python3 ~/.claude/hooks/launch-gate.py --install-for-project` once per project (writes `.claude/settings.local.json`); `--check-project` exits 0 when wired.

## Wire the two lane hooks once, globally

Both lane hooks read the hook input's `transcript_path` through `hooks/valentin_mode_loaded.py` and act only when the transcript shows valentin-mode loaded: a `/valentin-mode` command turn, a Skill tool call for it, or the skill body's own base directory line. A chat that never loaded it passes untouched, so one global entry covers every project.

Merge these two entries into the `PreToolUse` list in `~/.claude/settings.json`, in the fail-open shape above. Keep the list you already have; do not replace it.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "sh -c 'f=\"$HOME/.claude/hooks/plan-pick-only.py\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\"'",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Agent|Task",
        "hooks": [
          {
            "type": "command",
            "command": "sh -c 'f=\"$HOME/.claude/hooks/claude-helper-gate.py\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\"'",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Then delete the `plan-pick-only.py` and `claude-helper-gate.py` entries from each project's `.claude/settings.json`. Two entries on one event both run, and the old per-project copy cannot tell a plain chat from a valentin-mode one.

## Wire long-chat once, globally

`long-chat.py` also gates on `valentin_mode_loaded`, so register it once in `~/.claude/settings.json` on UserPromptSubmit, Stop, and PreCompact (`matcher`: `auto`), in the fail-open shape above. Then delete any per-project `long-chat.py` entries so the hook does not run twice.

Prove it in your own chats: in a plain chat `codex exec -C /tmp/x "hi"` starts; in a valentin-mode chat the same command is blocked and points at `plan-pick --run`.