# Responsive mode verification map

Responsive mode makes two promises. The chat stays free, and the job still finishes.
Every check in `grade.py` proves one of them from a timestamp or from a side effect,
never from the chat's own claim.

## Baseline preconditions

- `plan-pick --claude-helper` exits 0, because the test chat runs on Claude Sonnet.
- The skill under test has a `name: responsive-mode` frontmatter line, so `run` can
  rename it into the scratch repo, and a `# Responsive mode` heading, which is the
  marker the `loaded` check looks for.
- `run` copies the skill's whole folder, following symlinks, into the scratch repo and
  into the evidence folder, so a hook file the frontmatter names is never left behind.
- The skill's own hooks load with it. The chat transcript logs each hook run as a
  record holding an `attachment` whose `type` starts with `hook`, its `hookEvent` and
  the `command` that ran, so `checks loaded` matches that command's file name against
  the frontmatter. Another hook on the box, a hook named only in chat text, and a
  chat that never loaded the skill all count as no run.

## Driving conventions

- Only `run` starts a chat.
- The job never says how to run the slow step. If the chat backgrounds it, the skill
  taught it, not the test.
- The job does say where temporary files belong: inside the run's own working folder.
  Two runs at once used to share `/tmp/vrm-report.out` and grade each other FAIL.

## Proof and skip reporting

- A reply is timed from the moment `drive.py` wrote the question to the first
  assistant text holding the answer.
- Finishing is read from origin, never from the chat saying it pushed.
- A check that could not run reports `not run` and counts as FAIL.

## Features

| File | Checks | Promise |
| --- | --- | --- |
| [fast-replies.md](fast-replies.md) | `reply 1`, `reply 2`, `separate` | Each message gets its own reply inside 60 seconds |
| [finish-the-job.md](finish-the-job.md) | `background`, `slow step 1 ran`, `pushed` | The job still ends pushed, with no nudge |

`--hard` adds `reply 3`, `reply 4` and `slow step 2 ran` to the same two families.
