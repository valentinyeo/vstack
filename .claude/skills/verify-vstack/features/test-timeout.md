# The test guard refuses a hung command

`hooks/test-timeout-guard.py` refuses a test or build command that could hang a core for hours, and still lets a wrapped one through. A unit test reads the parser; only a real run shows what the hook process Claude Code actually calls does.

## Sub-features

- `blocked`: a Bash command that starts a test or build runner with no timeout in front of it never runs, and the chat gets one line naming the runner and the fix.
- `allowed`: a command already under `timeout` runs, prints nothing extra, and the chat sees no block.
- `killed`: a real `timeout` really kills a real runner, so the advice in the block line works.

## How to get to it (user POV)

- A chat starts a suite or a build with no timeout. It gets the block line and retries with `timeout 900` in front.
- A chat starts a wrapped command. It runs as before, with nothing added to its output.
- A chat that ignores the advice would hold a core for hours, so the guard stands in front of every Bash call.

## Driving it with verify-vstack

Preconditions:

- `hooks/test-timeout-guard.py` exists in the checkout under test, or `run` stops at the doctor.
- `timeout` and `python3` are on `PATH`, as on any Linux host this runs on.
- `run` never edits the hook and never starts a suite of its own. One run costs about 6 seconds and touches no board, no network and no model.

- **Doctor first.** `doctor.txt` holds one line: the hook file exists. A missing hook stops the run with exit 3 before it feeds anything, because a feed against nothing would grade FAIL for the wrong reason.
- **Real run.** Run `.claude/skills/verify-vstack/tools/test-timeout/run`. It makes `~/.local/state/verify-test-timeout/<run-id>/`, writes the two payloads in the shape Claude Code sends a `PreToolUse` Bash hook (`tool_name` Bash, `tool_input.command`) and feeds each to the real hook on stdin. Then it runs `timeout 5 python3 -c 'import time; time.sleep(60)'` and saves the exit code and the seconds. Expect `VERDICT PASS`.
- **Any other copy.** Run `.claude/skills/verify-vstack/tools/test-timeout/run --hook hooks/test-timeout-guard.py`, which grades the file it was pointed at.
- **Read the checks.** The blocked payload is the real command that hung four times on 2026-11-20, `python3 -m unittest discover -s scripts`, not a shortened stand-in: `blocked` passes on exit code 2 with exactly one stderr line naming the timeout fix and the runner, and fails on exit 0, a block naming no timeout, a block naming no runner, or more than one line. The allowed payload is `timeout 600 python3 -m unittest discover -s tests -p 'test_*.py'`: `allowed` passes on exit 0 with empty stderr, and exit 2 there is a false block, as bad as a miss. `killed` passes on exit code 124 in 4 to 9 seconds.
- **Evidence.** `meta.json` (which hook, which commit, the 5 second budget), `doctor.txt`, `blocked.json`/`blocked.exit`/`blocked.err`, `allowed.json`/`allowed.exit`/`allowed.err`, `killed.exit`/`killed.seconds`/`killed.out`, `verdict.txt`. Attach `verdict.txt` to a PR.
- **Regrade a saved run.** Run `.claude/skills/verify-vstack/tools/test-timeout/grade.py ~/.local/state/verify-test-timeout/<run-id>`, with no new hook call and no new sleep.
- **Cleanup.** `run` deletes nothing. Its one `sleep 60` is gone before the verdict prints.

## Gotchas

- A machine under heavy load can push `killed` past 9 seconds. Rerun before calling the guard broken.
- The block message is graded for one line, the word timeout and the runner's name. Changing that wording on purpose means changing `grade.py` and `tests/test_test_timeout_guard.py` in the same commit.
- A check whose evidence file is missing fails with its reason, never as PASS.
