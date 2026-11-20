# User bus

Reconcile reads live workers through `systemctl --user`. That needs the user session bus, which a headless chat does not always have.

## Sub-features

- `bus.reachable`: the first dry run prints no `Failed to connect to bus` in its output or its error file.
- `bus.env`: `run` sets `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` when they are unset, so the bus is there by default.

## How to get to it (user POV)

- From a chat started by a timer or a shell with no login session, run the board sync. It should still know which tickets have a live worker.

## Driving it with run

- Action: `run --board 15`. Result: `dry1.out` and `dry1.err` as the chat saw them.
- Check: `bus`.
- To prove the check itself, run it with the bus deliberately missing:

```sh
env -u XDG_RUNTIME_DIR -u DBUS_SESSION_BUS_ADDRESS \
  .claude/skills/verify-reconcile/run --board 15 --keep-bus
```

That run must FAIL `bus`. A check that never fails is not a check.

## Gotchas

- Without the bus, every ticket read fails with `systemctl --user failed: Failed to connect to bus: No medium found`. On board 15 that was 224 UNKNOWN lines in one run, which also drives `unknown` to FAIL.
- `--keep-bus` is for proving the check, never for a proof run on a PR.
- A bus address set to the wrong uid fails the same way. `run` builds both paths from `id -u`; do not export your own unless you mean it.
