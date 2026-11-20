# In-hook heal

When launch-gate.py runs as a PreToolUse hook, it rewrites a stale launch-gate command in the project's own `.claude/settings.local.json` to the fail-open `sh -c` form, the same upgrade `--install-for-project` already performs.

## Sub-features

- `heal`: one hook run on a scratch project that still carries the old bare-path command upgrades it in place, leaves every other hook entry alone, and a second run does not rewrite the file.

## How to get to it (user POV)

- A chat that installed the gate before PR 225 keeps working: the next Bash call heals the settings line automatically. The gate still blocks launches at HOLD while it heals.

## Driving it with run

- Action: write an old-form `.claude/settings.local.json` in `heal-project`, call the hook once with a harmless Bash command and `CLAUDE_PROJECT_DIR`, then call it again.
- Evidence: `heal-before.json`, `heal-after.json`, `heal-mtime.txt`.
- Check: `heal` compares the registered command before and after, and the two mtimes on the settings file.

## Gotchas

- Healing touches only `.claude/settings.local.json` in the project directory, never `settings.json` or global settings.
- A malformed JSON file is left as-is; the hook verdict is unchanged.
- Errors while healing are swallowed: at most one stderr line, and the gate decision is unchanged.