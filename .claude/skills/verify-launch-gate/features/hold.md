# A launch is blocked at HOLD

The incident was one chat starting 35 processes at load 40 on 18 cores, then starting them again after they were killed. The gate exists to make that call fail.

## Sub-features

- `hold.exit`: the hook exits 2, the code Claude Code reads as a block.
- `hold.message`: stderr opens with `BLOCKED by launch-gate: server is full (`, carries the `vps-state --brief` line, and ends with `Only the user can lift this: LAUNCH_GATE=off.`
- `hold.command`: the blocked command is the real one from the incident, `~/.local/bin/plan-pick --run`, sent as PreToolUse JSON.

## How to get to it (user POV)

- A chat under HOLD sees the block and the reason instead of a new worker. It finishes, merges or cleans up, tells the user, and asks the host again in ten minutes.

## Driving it with run

- Action: a fake `vps-state` that exits 2 and prints the brief line, set as `LAUNCH_GATE_VPS_STATE`, then the real hook with real JSON on stdin.
- Evidence: `hold.code`, `hold.err`, `brief.txt`.
- Check: `hold` wants exit 2, the opening words, the brief line, and the override line.

## Gotchas

- The fake is a file, not a stub inside the hook, so the probe runs the same way it does in production: a child process with a five second timeout.
- A block is only as good as its message. A failure that says nothing, or names no way out, fails this check.
