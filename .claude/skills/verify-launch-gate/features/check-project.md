# Check a project installed the hook

`launch-gate.py --check-project [DIR]` answers whether this project registered the gate, and prints the install command when it did not.

## Sub-features

- `check-project.passes`: exit 0 after the install, naming the settings file that carries the hook.
- `check-project.fails`: exit 1 on a project with no hook, and the line names `--install-for-project`.

## How to get to it (user POV)

- Any chat can prove it is gated without opening JSON. A project that fails prints the one command that fixes it.

## Driving it with run

- Action: `--check-project` on the scratch project, then on an empty directory.
- Evidence: `check-project.code`, `check-project.out`, `check-empty.code`, `check-empty.out`.
- Check: `check-project` wants exit 0, then exit 1 with the install command in the output.

## Gotchas

- The check also reads the real global settings at `~/.claude/settings.json`, because one registration there covers every project. The run gives the check a scratch `HOME` so the empty project fails as it should.
- The hook never writes the global settings. Only a person edits that file.
