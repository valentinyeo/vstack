---
name: test-timeout
description: >-
  Makes every test or build a chat starts die on its own. Blocks a Bash command that starts a
  test or build runner with no timeout in front of it, names the one line fix, and proves the
  check on your own machine. Use before running a suite or a build, and when a server stops
  answering because something hung.
---

# Test timeout

Prior art: pstack checked. `tdd` and the `poteto-mode` bug-fix playbook say how to run a failing test first; neither has a rule about a test that never ends. The host watchdog stops node and bun tools only, so python, pytest, go, cargo, make and shell test scripts run unbounded there.

**Rule: every test or build you start runs under `timeout`. 10 minutes is the default. Full builds get 30 minutes at most.**

```
timeout 600 python3 -m unittest discover -s tests     # good
timeout 1800 npm run build                           # good, full build
python3 -m unittest discover -s scripts              # blocked
```

## Why

On 2026-11-20 four `python3 -m unittest discover -s scripts` runs hung for 10 to 15 hours and each kept a core busy. With parallel builds the 18 core VPS reached load 38 and no chat could answer the owner. Nothing stopped them: the watchdog on this host matches node, bun, vitest, jest, playwright, next and vite, and hung python is invisible to it. A timeout of 10 minutes turns that freeze into a failed test.

## Set up your own check

A rule in a document is not a check. The hook file is already there; registering it in a project is your step, once per project.

1. The shared vstack install already linked the hook: `hooks/test-timeout-guard.py` sits at `$HOME/.claude/hooks/test-timeout-guard.py`. Never run `./install` yourself. From a worktree it repoints every chat's skills at your branch, and it now refuses to run anywhere but `$HOME/.local/share/vstack`. If the file is missing, say so; the command below then lets every call through instead of blocking you, so no check runs until the install is fixed. Do not run `./install` to fix it.
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
            "command": "sh -c 'f=\"$HOME/.claude/hooks/test-timeout-guard.py\"; [ -f \"$f\" ] || exit 0; exec /usr/bin/python3 \"$f\"'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The `[ -f "$f" ] || exit 0` is not noise. A missing or broken link makes python exit 2, and Claude Code reads exit 2 as a block, so a bare `python3 $HOME/.claude/hooks/test-timeout-guard.py` entry stops the chat running any Bash at all. This form exits 0 when the file is gone and still blocks at 2 when the guard says so.

Then prove it in your own chat: run `pytest` and get the block, run `timeout 600 pytest` and watch it start. If the second command is also blocked, your settings file has the old copy of the hook.

## What it blocks

A Bash command whose simple command starts one of these with no `timeout` before it: `python -m unittest`, `pytest`, py.test, `npm`, `pnpm`, `yarn` or `bun` with `test` or `run test`, `vitest`, `jest`, `playwright test`, `cargo test`, `cargo build`, `go test`, `zig build`, `make test`, `make check`, a shell script under `tests/`, `node --test`, and `tsc -b`.

It reads the command the way a shell does, so a timeout still counts through `env`, `nice`, `nohup`, `setsid` and `cd somewhere &&`. A command that only names a runner passes: `grep pytest`, `cat tests/install.sh`, `git log --grep pytest`.

Two shapes slip through on purpose: a runner hidden inside `bash -c '...'`, and one a pipe builds, such as `printf ... | xargs -I{} {}`. The guard reads the command, not the command the command would build. Do not use those shapes to dodge it; add the timeout.

## Heavy work stays on GitHub

Each chat merges this entry into its own project's Bash `PreToolUse` hooks in `.claude/settings.json`. Preserve existing hooks. The shared install supplies `$HOME/.claude/hooks/heavy-local-guard.py`; report a missing link. Never run `./install` yourself.

```json
{
  "type": "command",
  "command": "sh -c 'f=\"$HOME/.claude/hooks/heavy-local-guard.py\"; [ -f \"$f\" ] || exit 0; exec /usr/bin/python3 \"$f\"'",
  "timeout": 5
}
```

Refuses heavy jobs under `timeout`, naming `gh workflow run` or push-to-CI. Light tests still pass. Prove registration with JSON payloads using [the heavy-local feature](../../.claude/skills/verify-vstack/features/heavy-local.md), never a real heavy job. Shell `-c` is inspected; scripts, aliases and generated commands are not expanded. Do not use them to dodge the rule.

## Prove the guard itself

`.claude/skills/verify-test-timeout/SKILL.md` feeds the real hook real hook input and watches a real 5 second timeout kill a real 60 second sleep. Run it after any change to the hook.
