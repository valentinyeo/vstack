# The real host answers

The other checks use a fake. This one reads the machine the chats share, so the proof is about this VPS and not only about the code.

## Sub-features

- `live.verdict`: `vps-state --brief` prints a line that starts with ADD, CAREFUL or HOLD.
- `live.exit-agrees`: `vps-state --can-launch worker --no-write` exits 0, 1 or 2 to match that word.

## How to get to it (user POV)

- The PR carries today's real answer. Anyone can compare it with what the gate would do at that moment.

## Driving it with run

- Action: `--brief`, then `--can-launch worker --no-write`, both against the real script found on PATH or in this repo.
- Evidence: `live.out`, `live.err`, `live.code`.
- Check: `live` maps the first word to its exit code and wants them equal.

## Gotchas

- The two calls are two reads of a moving host. A host crossing a threshold between them fails `live`; run it again rather than loosening the check.
- `--no-write` keeps the shared status file alone, so verifying never changes what a fleet runner reads.
