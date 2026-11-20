# Install in one project

`launch-gate.py --install-for-project [DIR]` writes the hook into a project's own settings. Nobody watches the fleet, so each chat switches the gate on for itself.

## Sub-features

- `install`: the command exits 0, creates `.claude/settings.local.json` in the project, and registers one PreToolUse entry with matcher `Bash`, whose command names `$HOME/.claude/hooks/launch-gate.py` behind `sh -c` with a `[ -f "$f" ] || exit 0` guard.
- `idempotent`: a second run exits 0, says it changed nothing, and leaves the file byte for byte the same. An entry in the older bare-path form is upgraded in place, not duplicated.

## How to get to it (user POV)

- A chat that runs this once gets a block instead of a launch while the server is full. Nothing else in its project settings moves.

## Driving it with run

- Action: `--install-for-project <scratch project>` twice, with the scratch project's own `HOME`.
- Evidence: `install-1.json`, `settings-1.json`, `install-2.json`, `settings-2.json`.
- Check: `install` reads the first exit code and the registered entry; `idempotent` compares the two settings files and the second run's line.

## Gotchas

- The scratch project's `HOME` is not the real one, so the gate cannot pass `install` on a hook that lives only in the global settings.
- The install keeps every other key and every other hook entry. A test in `tests/test_launch_gate.py` pins that, because merging by replacement would wipe another guard.
- An upgrade keeps that entry's `matcher` and every other item in its `hooks` list, and changes only the `command` string.
