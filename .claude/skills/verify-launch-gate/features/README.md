# Launch gate verification map

Every part of the gate `run` drives, one file each, and the check in [grade.py](../grade.py) that grades it. Read this, then the file for the check.

## Baseline preconditions

- `.claude/skills/verify-launch-gate/run` runs on this VPS: the live check needs a real `vps-state`, found on PATH or at this repo's copy.
- `hooks/launch-gate.py` is executable, because Claude Code runs it as a command.
- The scratch project has its own `HOME`, so a hook registered in the real global settings cannot make `--check-project` pass.

## Driving conventions

- Only `run` drives the hook. It feeds the same JSON Claude Code sends, never a shortened form.
- Every fake `vps-state` is a file in the scratch directory, named by `LAUNCH_GATE_VPS_STATE`. The real one is used only for the live check.
- The install runs twice on purpose. The second run is what proves the command is safe to repeat.
- The registered command is driven through `sh -c`, the way Claude Code runs a hook command, never by calling the hook file directly.

## Proof and skip reporting

- A check reads the saved exit code and stderr, never the run's own summary.
- A check that could not run is reported FAIL with its reason, never PASS.
- The verdict is FAIL when any check fails, including the live host reading.

## Features

| File | Checks | What it proves |
| --- | --- | --- |
| [install.md](install.md) | `install`, `idempotent` | One command registers the hook in a project, and a second run changes nothing |
| [check-project.md](check-project.md) | `check-project` | A project can prove it installed the hook, and an empty one fails with the command |
| [registered-command.md](registered-command.md) | `registered` | The command settings call exits 0 when the hook file is missing, and still blocks at HOLD |
| [hold.md](hold.md) | `hold` | A real incident launch is blocked at HOLD with the reason and the override |
| [verdicts.md](verdicts.md) | `verdicts` | ADD and CAREFUL let the launch through, silently |
| [fail-open.md](fail-open.md) | `fail-open` | A probe failure allows the launch and warns once |
| [live-host.md](live-host.md) | `live` | The real host answers, and its exit code agrees with its brief line |
| [doctor.md](doctor.md) | `doctor` | The hook was worth driving |
