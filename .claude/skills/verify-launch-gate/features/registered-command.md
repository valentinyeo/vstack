# The command settings call fails open without the hook file

The hook is never run by a person. Settings run one command line, and a command that
names a missing file exits 2, which Claude Code reads as a block. A chat then runs no
Bash at all, which is what happened on 2026-11-24 after a merge left the link broken.

## Sub-features

- `registered-command.missing`: with the hook file absent, the registered command exits 0 and prints nothing.
- `registered-command.hold`: with the hook file present and vps-state at HOLD, the same command exits 2 with the block.

## How to get to it (user POV)

- On a host where the install has not run or the link broke, the chat keeps working and no launch is checked.
- On a host where the file is there, the gate behaves exactly as before.

## Driving it with run

- Action: read the command from the settings the second install wrote, run it through `sh -c` with a scratch `HOME` where `$HOME/.claude/hooks/launch-gate.py` is absent, then link the real hook into that `HOME` and run it again with a fake vps-state at HOLD.
- Evidence: `missing.code`, `missing.err`, `registered-hold.code`, `registered-hold.err`.
- Check: `registered` wants exit 0 and no stderr from the first, exit 2 and the block message from the second.

## Gotchas

- A broken symlink counts as missing: `[ -f "$f" ]` is false for it, and that is the shape the incident had.
- Failing open here is silent on purpose. The gate warns once when the probe is broken, but an absent hook file has no gate to warn from.
- The bare path and `python3 $HOME/.claude/hooks/launch-gate.py` both fail this check, which is how the fix's own regression test starts.
