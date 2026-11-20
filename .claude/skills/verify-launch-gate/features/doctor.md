# The hook was worth driving

## Sub-features

- `doctor.hook`: `hooks/launch-gate.py` is a file and is executable, because Claude Code runs it as a command.
- `doctor.self-test`: `launch-gate.py --self-test` exits 0, which is the same line the hook-self-tests job runs on GitHub.

## How to get to it (user POV)

- A green run means the hook that was driven is the one that ships.

## Driving it with run

- Action: the doctor runs before anything else and writes `doctor.txt`.
- Check: `doctor` fails when any line in `doctor.txt` is not PASS.

## Gotchas

- A doctor failure exits 3 and drives nothing. On a PR that means the hook is not installed the way Claude Code needs it.
