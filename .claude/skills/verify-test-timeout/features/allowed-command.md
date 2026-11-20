# allowed

Feature: a command already under timeout passes untouched.

Check `allowed` in `grade.py`.

## The promise

The guard never stands between a chat and work it did right. A command with a timeout in front of
it runs, prints nothing extra, and the chat sees no block.

## How it is proved

`run` writes `allowed.json` with `timeout 600 python3 -m unittest discover -s tests -p 'test_*.py'`,
the command this repo's own work uses, in the real PreToolUse shape. It feeds that payload to the
hook and saves `allowed.exit` and `allowed.err`.

## PASS

Exit code 0 and empty stderr.

## FAIL

Exit code 2, which is a false block and costs a chat a round trip, or any stderr on a command that
should pass.

## Read

- `allowed.json`, `allowed.exit`, `allowed.err` in the run's evidence folder.
