# Project setup

Every project Valentin works in adds these hooks to its `.claude/settings.json`. Use the exact command shown: `install` links only `skill-update.py` into `~/.claude/hooks/`; the other two run from the shared vstack checkout.

| Hook | Event | Command | What it does |
|---|---|---|---|
| `plan-pick-only.py` | PreToolUse, matcher `Bash` | `/usr/bin/python3 /home/valentin/.local/share/vstack/hooks/plan-pick-only.py` | Code workers start only through `~/.local/bin/plan-pick --run`. |
| `claude-helper-gate.py` | PreToolUse, matcher `Agent\|Task` | `/usr/bin/python3 /home/valentin/.local/share/vstack/hooks/claude-helper-gate.py` | A Claude helper starts only when `plan-pick --claude-helper` allows it. |
| `skill-update.py` | UserPromptSubmit | `python3 ~/.claude/hooks/skill-update.py` | Keeps the shared skills current and says when valentin-mode changed, so the chat re-reads it. |
