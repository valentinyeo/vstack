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

Nobody enables this for you, and a rule in a document is not a check. Two steps, once per project.

1. Link the hook. In your vstack checkout run `./install`. It links `hooks/test-timeout-guard.py` into your Claude hooks folder.
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
            "command": "/usr/bin/python3 \"$HOME/.claude/hooks/test-timeout-guard.py\"",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Then prove it in your own chat: run `pytest` and get the block, run `timeout 600 pytest` and watch it start. If the second command is also blocked, your settings file has the old copy of the hook.

## What it blocks

A Bash command whose simple command starts one of these with no `timeout` before it: `python -m unittest`, `pytest`, py.test, `npm`, `pnpm`, `yarn` or `bun` with `test` or `run test`, `vitest`, `jest`, `playwright test`, `cargo test`, `cargo build`, `go test`, `zig build`, `make test`, `make check`, a shell script under `tests/`, `node --test`, and `tsc -b`.

It reads the command the way a shell does, so a timeout still counts through `env`, `nice`, `nohup`, `setsid` and `cd somewhere &&`. A command that only names a runner passes: `grep pytest`, `cat tests/install.sh`, `git log --grep pytest`.

## Prove the guard itself

`.claude/skills/verify-test-timeout/SKILL.md` feeds the real hook real hook input and watches a real 5 second timeout kill a real 60 second sleep. Run it after any change to the hook.
