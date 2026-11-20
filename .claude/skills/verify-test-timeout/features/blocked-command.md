# blocked

Feature: a hung test or build command is refused before it runs.

Check `blocked` in `grade.py`.

## The promise

A Bash command that starts a test or build runner with no timeout in front of it never runs. The
chat gets one line back naming the runner and the fix, so it can retry correctly in the same turn.

## How it is proved

`run` writes `blocked.json` with the command that hung four times on 2026-11-20,
`python3 -m unittest discover -s scripts`, in the real PreToolUse shape. It feeds that payload to
the hook on stdin and saves `blocked.exit` and `blocked.err`.

## PASS

Exit code 2, stderr exactly one line, the line names the timeout fix and the runner it caught.

## FAIL

One of: exit 0 (the hung command would run), a block that names no timeout, a block that names no
runner, or more than one line.

## Read

- `blocked.json`, `blocked.exit`, `blocked.err` in the run's evidence folder.
