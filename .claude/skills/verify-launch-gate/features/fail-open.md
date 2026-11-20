# A broken probe fails open

vps-state is a second program. If it cannot answer, the gate must not become the outage.

## Sub-features

- `fail-open.exit`: a probe that exits 3 allows the call, exit 0 from the hook.
- `fail-open.one-line`: stderr carries exactly one line, starting `launch-gate:`, so a person can see the launch went unchecked.

## How to get to it (user POV)

- On a host where the probe is missing or slow, work continues and the chat says the launch was unchecked once.

## Driving it with run

- Action: a fake that exits 3 for `--can-launch`.
- Evidence: `open.code`, `open.err`.
- Check: `fail-open` wants exit 0 and one stderr line.

## Gotchas

- `tests/test_launch_gate.py` also covers the missing binary and a probe slower than five seconds, because those are the two shapes a host produces: no `vps-state` on PATH, and a probe that hangs under load.
- Failing open silently would hide a broken install. That is why the warning line is graded, not optional.
