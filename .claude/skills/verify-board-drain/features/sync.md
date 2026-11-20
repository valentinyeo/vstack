# Sync

Every tick syncs the board as the chat's own login: the reconcile preview, then `--apply --limit 5`, then `loop-state` records the result so `drain-check` can see it.

## Sub-features

- `sync.run`: `./sync --board <id> --label <label> --name "<chat>"` runs the preview and the apply.
- `sync.ok`: `last_sync.ok` is true, with `at` after the run started.
- `sync.kept`: the record survives the arming. `loop-state arm` rewrites the file and drops `last_sync`, so a chat that arms after syncing fails here.

## How to get to it (user POV)

- A tick starts, or `drain-check` prints `sync stale` or `sync failed`.
- The chat runs its sync before it checks, so the check sees a fresh record.

## Driving it with run

Preconditions: `HT_TOKEN` holds the "VVM Test Agent" token and `SHIP_SESSION_NAME` is "VBD Test Chat", because `reconcile --apply` on board 2060 refuses without an agent name. `run` sets both.

- Action: `run`. Result: `state.json` carries `last_sync`: `{at, ok, reason}`.
- Check `synced`: `ok` is true, `at` parses and is at or after `started_at`. A failed sync passes its `reason` into the check line.

## Gotchas

- The sync writes on board 2060 as "VVM Test Agent". Nothing else should be writing there during a run.
- A `sync: FAIL` prints its reason and records `ok: false`; the check reports the reason instead of the chat's summary of it.
- The 45-minute staleness rule is drain-check's, not this check's. `synced` only asks that the record exists, is ok, and is from this run.
