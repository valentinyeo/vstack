# Status file

`~/.local/state/vps-load/status`, the line every fleet runner reads before it starts a slot.

## Sub-features

- `status`: the file starts with the word for this run's worker verdict (`add`, `steady` or `hold`), then `load5=<x>` with two decimals and `cores=<n>`.
- Freshness: the run rewrites it on every call, atomically, so a reader never sees half a line.
- Off switch: `--no-write` leaves the file alone, which is what the tests use.

## How to get to it (user POV)

- Run `"$HOME/.local/bin/vps-state"` once. Then `cat ~/.local/state/vps-load/status` shows what the runner will see.
- A stale file is worse than none: on 2026-11-15 it said `add load5=7.55 cores=18` while the host ran at 30 load on 18 cores today.

## Driving it with run

- Action: `run` calls the script without `--no-write`, then reads the file back into `status.txt`.
- Check: the state word must match the worker verdict in the JSON, and `load5=` must carry the reported number. A file that says `add` while the JSON says HOLD fails.

## Gotchas

- The fleet runner also re-reads load5 and MemAvailable itself, so the file only has to be honest about the state word. Writing `add` when any gate failed would open a slot on a busy host.
- When /proc/loadavg cannot be read the file says `load5=unknown`. That never matches `^add`, so a broken probe holds the fleet rather than flooding it.
- The `verify-reconcile` proofs and any test that sets a temp HOME never touch this file. Only a real run on this host rewrites it.
