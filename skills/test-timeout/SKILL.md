---
name: test-timeout
description: >-
  Makes every test or build a chat starts die on its own. Blocks a Bash command that starts a
  test or build runner with no timeout in front of it and names the one line fix. Use before
  running a suite or a build, and when a server stops answering because something hung.
---

# Test timeout

Prior art: pstack checked. `tdd` and the `poteto-mode` bug-fix playbook say how to run a failing test first; neither has a rule about a test that never ends. The host watchdog stops node and bun tools only, so python, pytest and shell test scripts run unbounded there.

**Rule: no suite, no build and no desktop app on this host. Push and read CI. A syntax check or one named test file under `timeout` of 90s or less is the only heavy-ish local command left.**

```
timeout 60 python3 -m unittest tests.test_one -v   # good, one named test
python3 -m unittest discover -s tests              # blocked, a full suite
timeout 600 npm run build                          # blocked, a build
```

## Why

On 2026-11-20 four `python3 -m unittest discover -s scripts` runs hung for 10 to 15 hours and each kept a core busy; with parallel builds the 18 core VPS reached load 38 and no chat could answer the owner. The watchdog matches node and bun tools only, so hung python is invisible to it.

## Set up your own check

Registering the hook in a project is your step, once per project.

1. The shared install linked the hook as `$HOME/.claude/hooks/test-timeout-guard.py`. Never run `./install` yourself: from a worktree it repoints every chat's skills at your branch, and it refuses to run anywhere but `$HOME/.local/share/vstack`. If the file is missing, say so; `run-hook` then lets every call through, so no check runs until the install is fixed.
2. Add this to your own project's `.claude/settings.json`. Merge it into the `PreToolUse` list you already have; do not replace that list.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "\"$HOME/.local/share/vstack/hooks/run-hook\" \"$HOME/.claude/hooks/test-timeout-guard.py\"",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

`run-hook` exits 0 and logs a warning when the script is missing or not executable. A bare Python call would exit 2, which Claude Code reads as a block. An existing guard still blocks at 2 when it rejects an unbounded test.

Then prove it: `pytest` gets the block, `timeout 60 pytest tests/test_one.py` starts. If the second is blocked too, your settings file has the old hook.

## What it blocks

A Bash command that starts a test or build runner with no `timeout` before it, read the way a shell reads it: a timeout still counts through `env`, `nice`, `nohup`, `setsid` and `cd somewhere &&`. A command that only names a runner passes: `grep pytest`, `cat tests/install.sh`, `git log --grep pytest`.

A runner hidden in `bash -c '...'` or built by a pipe, such as `printf ... | xargs -I{} {}`, slips through on purpose: the guard reads the command, not the command the command would build. Do not dodge it that way; add the timeout.

## Heavy work stays on GitHub

Each chat merges this entry into its own project's Bash `PreToolUse` hooks in `.claude/settings.json`. Preserve existing hooks. The shared install supplies `$HOME/.claude/hooks/heavy-local-guard.py`; report a missing link. Never run `./install` yourself.

```json
{
  "type": "command",
  "command": "\"$HOME/.local/share/vstack/hooks/run-hook\" \"$HOME/.claude/hooks/heavy-local-guard.py\"",
  "timeout": 5
}
```

The guard reads its blocked list from `config/heavy-local.json`. Gradle, Wine and `xvfb-run`, the Windows desktop app, Zig, any package-manager `test` or `build`, `pytest`, `cargo` and `go` builds and tests, and `python3 -m unittest discover -s tests` on this host are refused with or without `timeout`, naming `gh workflow run` or a branch push. The only exceptions are the lines in `config/heavy-local-allow.txt`, each with its reason: a syntax check, `--help` or `--version`, and one named test file (no wildcards) under `timeout` of 90s or less.

Pacer workers on OpenCode and Antigravity never run these hooks. `scripts/worker-shims` writes the same refusal as a command shim into a worker-shims folder in vstack's local state, and plan-pick puts that folder first on a worker's PATH. A shim sees only its own words (never a wrapping `timeout`), so a worker gets no single-file test exception: it pushes and reads CI.

Light tests still pass. Prove registration with JSON payloads using [the heavy-local feature](../../.claude/skills/verify-vstack/features/heavy-local.md), never a real job. Shell `-c` is inspected; aliases and generated commands are not expanded.

## Prove the guard itself

`.claude/skills/verify-test-timeout/SKILL.md` feeds the real hook real input and watches a real 5 second timeout kill a real 60 second sleep. Run it after any change to the hook.
