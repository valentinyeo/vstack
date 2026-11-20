---
name: verify-test-timeout
description: >-
  Prove that hooks/test-timeout-guard.py still refuses a hung test command and still lets a
  wrapped one through. Feeds the real hook real PreToolUse JSON, then runs a real 5 second
  timeout against a real 60 second sleep, and grades the three results PASS or FAIL from exit
  codes and one measured second count. Use after any change to the guard or to skills/test-timeout,
  and as the proof on such a PR.
---

# Verify test timeout

The guard's whole job is to stop a command that would hang a core for hours. Only a real run shows that: a unit test reads the parser, never the hook process Claude Code actually calls.

Prior art: pstack checked (`create-verification-skill`, `maintain-verification-skill`), and this repo's `verify-reconcile` and `verify-responsive-mode`. None of them is a check that a Bash guard refuses a command, so this is the `verify-<app>` skill `create-verification-skill` asks for, with the hook as the app.

Read `features/README.md` for the map.

## Launch

```sh
.claude/skills/verify-test-timeout/run                                   # this checkout's hook
.claude/skills/verify-test-timeout/run --hook hooks/test-timeout-guard.py   # any other copy
```

One run costs about 6 seconds and touches no board, no network and no model.

The order of work:

1. Makes `~/.local/state/verify-test-timeout/<run-id>/`, with a `-2` suffix when the name is taken, and writes `meta.json`.
2. Runs the doctor. Exit 3 when the hook is missing.
3. Writes the two payloads in the shape Claude Code sends a PreToolUse Bash hook: the command that hung four times on 2026-11-20, and the same command already under `timeout 600`.
4. Feeds each payload to the real hook on stdin and saves its exit code, stdout and stderr.
5. Runs `timeout 5 python3 -c 'import time; time.sleep(60)'` and saves its exit code and the seconds it took.
6. Grades, prints the verdict, exits with its code.

## Doctor

`doctor.txt` holds one line per check. The only one today: the hook file exists. A missing hook stops the run before it drives anything, because a feed against nothing grades FAIL for the wrong reason.

## Drive

Only `run` drives. To regrade a saved run, with no new hook call and no new sleep:

```sh
.claude/skills/verify-test-timeout/grade.py ~/.local/state/verify-test-timeout/<run-id>
```

## Evidence

Every run keeps `~/.local/state/verify-test-timeout/<run-id>/`:

| File | What it proves |
| --- | --- |
| meta.json | which hook, at which commit, and the 5 second budget |
| doctor.txt | the hook was there to drive |
| blocked.json, blocked.exit, blocked.err | the hung command was refused, with the fix named |
| allowed.json, allowed.exit, allowed.err | the wrapped command passed with no output |
| killed.exit, killed.seconds, killed.out | a real timeout killed a real sleep at about 5 seconds |
| verdict.txt | one PASS or FAIL line per check, then the verdict |

On a PR, attach `verdict.txt`. The CI test `tests/test_test_timeout_guard.py` covers the grade path on synthetic evidence, so a broken grader fails on GitHub too.

## Cleanup

`run` deletes nothing. It starts one `sleep 60` under a 5 second timeout, and that process is gone before the run prints its verdict.

## Gotchas

- `killed` expects exit 124 and 4 to 9 seconds. A machine under heavy load can push past 9. Rerun before you call it a broken guard.
- A run proves the hook file it was pointed at. `--hook` exists so a PR branch's copy can be graded, not the installed one.
- The block message is graded for one line, the word timeout, and the runner's name. Changing that wording on purpose means changing `grade.py` and `tests/test_test_timeout_guard.py` in the same commit.
