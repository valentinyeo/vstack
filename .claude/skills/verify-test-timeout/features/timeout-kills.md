# killed

Feature: a real timeout really kills a real runner, so the advice in the block line works.

Check `killed` in `grade.py`.

## The promise

The fix the guard asks for is the thing that saves the server. Ten minutes of python under
`timeout` ends, and the process is gone rather than lingering on a core.

## How it is proved

`run` measures a real pair: `timeout 5 python3 -c 'import time; time.sleep(60)'`. A short budget
stands in for the 600 seconds in the advice, so the check costs 5 seconds instead of 10 minutes.
It saves the exit code in `killed.exit` and the elapsed seconds in `killed.seconds`.

## PASS

Exit code 124, the timeout's own "I killed it" code, and 4 to 9 seconds elapsed.

## FAIL

Exit 0 with the sleep reaching 60 seconds (no timeout at all), any other exit code, or an elapsed
time outside the window. A slow host can drift past 9 seconds; rerun before calling the guard broken.

## Read

- `killed.exit`, `killed.seconds`, `killed.out` in the run's evidence folder.
