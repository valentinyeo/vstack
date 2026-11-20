---
name: verify-launch-gate
description: >-
  Prove that hooks/launch-gate.py blocks a chat's worker, build or test run while the server is full, and that one command switches it on in a project. Installs the hook into a scratch project, feeds the real hook real PreToolUse JSON, grades PASS or FAIL per check, and prints the live host verdict. Use after any change to the hook or its installer, as proof on such a PR, and whenever a chat doubts it is gated.
---

# Verify launch gate

Prior art: checked pstack (`create-verification-skill`), this repo's `verify-vps-state` and `verify-reconcile`. Neither grades a hook decision, so this drives the hook the way Claude Code does.

The proof bar: the real hook, real PreToolUse JSON, and a fake vps-state whose verdict the run picked. A HOLD that exits 2 with the reason, an ADD that passes silently, an install that survives a second run, and one live host reading is a PASS. A hook that only passes its own self-test is not proof.

Read `features/README.md` for the map.

## Launch

```sh
.claude/skills/verify-launch-gate/run                # this checkout's hook
.claude/skills/verify-launch-gate/run --hook PATH     # a branch's copy
```

`run` does, in order:

1. Makes ~/.local/state/verify-launch-gate/<run-id>/ and writes meta.json (hook path, git shas, host).
2. Runs the doctor into doctor.txt. Exit 3 when it fails.
3. Makes a scratch project and runs --install-for-project on it twice.
4. Runs --check-project on that project and on an empty directory.
5. Feeds the real hook the incident command `~/.local/bin/plan-pick --run` as PreToolUse JSON, with a fake vps-state at HOLD, CAREFUL, ADD and a probe failure.
6. Reads the real host with `vps-state --brief`, then --can-launch worker --no-write.
7. Grades every check and prints one line per check, then the verdict.

Exit codes: 0 PASS, 1 FAIL, 3 doctor failure.

## Doctor

doctor.txt holds one line per check, and each must pass before anything is driven:

- the hook is a file and is executable, because Claude Code runs it as a command;
- `launch-gate.py --self-test` exits 0, the same line GitHub's hook job runs.

## Drive

Only `run` drives the hook. It writes a fake `vps-state` into the scratch directory and points the hook at it with a fake `LAUNCH_GATE_VPS_STATE`, so no check depends on what this host happens to be doing. The scratch project gets its own `HOME`, so a hook registered in the real global settings cannot make `--check-project` pass.

The live check is the only real read, and it never writes the shared status file.

## Evidence

Every run keeps ~/.local/state/verify-launch-gate/<run-id>/:

| File | What it proves |
| --- | --- |
| meta.json | which hook, which commits, which host |
| doctor.txt | the hook was worth driving |
| install-1.json, settings-1.json | the install exit code and the file it wrote |
| install-2.json, settings-2.json | the second run changed nothing |
| check-project.code, check-empty.code | a gated project passes, an empty one fails |
| hold.code, hold.err | the blocked launch, its reason and the override line |
| add.code, careful.code and their .err | allowed launches stay silent |
| open.code, open.err | a probe failure fails open with one warning |
| live.out, live.code | today's real host verdict and its exit code |
| verdict.txt, verdict.json | one PASS/FAIL line per check, then the verdict |

Attach verdict.txt to the PR or ticket.

## Cleanup

`run` deletes the scratch project when it ends, and keeps every evidence directory. `--keep` leaves the scratch project in place for a look. It starts no long-lived process and writes no settings outside the scratch directory.

## When it runs

Every change to `hooks/launch-gate.py`, its installer or its skill runs it, with the verdict on the PR. GitHub CI runs `tests/test_launch_gate.py` and the hook's self-test; a live host reading needs this server.

## Gotchas

- The live check makes two reads of a moving host. A host crossing a threshold between them fails `live`; run it again rather than loosening the check.
- Failing open is graded, not excused. A probe that hangs, exits 3 or is missing must still allow the launch, with exactly one warning line.
- A block on a healthy host is as wrong as a launch on a full one. `verdicts` fails if ADD or CAREFUL prints anything.
- The scratch project's settings are evidence, not a live registration. To gate a real project, run `--install-for-project` in it.
- The grade path has its own unit tests in `tests/test_launch_gate.py`, so a broken grade fails on GitHub without a board login.
