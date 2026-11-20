# Finish the job

The job ends done and checked even though the chat answered side questions on the way.

## Sub-features

- `background`: the slow step ran as a harness-tracked background job, meaning a Bash
  tool call with `run_in_background: true`, or an Agent call with the same flag. A
  command carrying `nohup`, `setsid`, `disown`, `tmux` or a single `&` fails, because
  nothing wakes the chat when that process ends.
- `slow step 1 ran`: slow-report.sh wrote `ran.txt` after its 90 second sleep.
- `pushed`: origin main has REPORT.md holding the random report line this run seeded.
  `--hard` expects a second line from slow-publish.sh, and adds `slow step 2 ran`.

## How to get to it (user POV)

Ask for a job that ends in a push, chat with the session while it runs, then look at
the remote without nudging it.

## Driving it with drive.py

The chat has to pick the slow step back up when its background job ends. stdin stays
open while any task the driver saw start is still running, so that wake-up can happen.

## Gotchas

- A chat that ends its turn with a detached process never wakes up. The driver then
  closes after 60 idle seconds and `pushed` fails.
- The report line is random per run, so an old commit or an earlier run's line cannot
  pass. That is deliberate: the grader ignores nothing.
- Two runs at once must not write the same file. The job text sends every temporary
  file into the run's own working folder for that reason.
