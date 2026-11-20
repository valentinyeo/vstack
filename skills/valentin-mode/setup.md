# Project setup

Every project Valentin works in adds these hooks to its `.claude/settings.json`. Each hook lives in vstack's `hooks/` folder and is installed to `~/.claude/hooks/`.

Write every registered command to fail open when its file is missing, and to block only when the hook itself says so. A bare path, or `python3 $HOME/.claude/hooks/hook.py`, exits 2 on a missing or broken link, and Claude Code reads exit 2 as a block. Use this shape, which exits 0 when the file is gone and passes the exit code through when it is there:

```json
{ "command": "sh -c 'f=\"$HOME/.claude/hooks/plan-pick-only.py\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\"'" }
```

| Hook | Event | What it does |
|---|---|---|
| `plan-pick-only.py` | PreToolUse, Bash | Code workers start only through `~/.local/bin/plan-pick --run`. |
| `claude-helper-gate.py` | PreToolUse, Agent and Task | A Claude helper starts only when `plan-pick --claude-helper` allows it. |
| `skill-update.py` | UserPromptSubmit | Keeps the shared skills current and says when valentin-mode changed, so the chat re-reads it. |
