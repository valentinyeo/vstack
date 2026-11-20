# Test timeout verification map

The guard makes one promise: a test or build command that could hang for hours never starts
without a timeout in front of it. A hung command must be refused, and a wrapped one must not be
disturbed. Every check in `grade.py` reads an exit code or a measured second, never a chat's claim.

## Baseline preconditions

- `hooks/test-timeout-guard.py` exists in the checkout under test, or `run` stops at the doctor.
- `timeout` and `python3` are on PATH, as they are on any Linux host this runs on.

## Driving conventions

- Only `run` feeds the hook, and it feeds the exact JSON shape Claude Code sends: `tool_name` Bash, `tool_input.command`.
- The blocked payload is the real command from 2026-11-20, not a shortened stand-in.
- `run` never edits the hook and never starts a suite of its own.

## Proof and skip reporting

- `blocked` reads the hook's exit code and the block line. A hook that exits 0 on the hung command fails, and so does a block with no timeout in it.
- `allowed` reads the same way, in the other direction: a non zero exit on the wrapped command is a false block, which is as bad as a miss.
- `killed` reads the exit code of a real `timeout 5` and the seconds it took. A sleep that ran to the end fails, and so does one that died outside the 4 to 9 second window.
- A check whose evidence file is missing fails with its reason. It is never reported PASS.

## Features

| File | Check | Promise |
| --- | --- | --- |
| [blocked-command.md](blocked-command.md) | `blocked` | A hung test or build command is refused, with the fix in the block line |
| [allowed-command.md](allowed-command.md) | `allowed` | A command already under timeout passes and prints nothing |
| [timeout-kills.md](timeout-kills.md) | `killed` | A real timeout kills a real runner, and the guard's advice works |
