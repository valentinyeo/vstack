# Project setup

Every project Valentin works in adds these hooks to its `.claude/settings.json`. Each hook lives in vstack's `hooks/` folder and is installed to `~/.claude/hooks/`.

| Hook | Event | What it does |
|---|---|---|
| `plan-pick-only.py` | PreToolUse, Bash | Code workers start only through `~/.local/bin/plan-pick --run`. |
| `claude-helper-gate.py` | PreToolUse, Agent and Task | A Claude helper starts only when `plan-pick --claude-helper` allows it. |
| `skill-update.py` | UserPromptSubmit | Keeps the shared skills current and says when valentin-mode changed, so the chat re-reads it. |
