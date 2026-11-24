# Docker

Images, the builder cache and leaked smoke volumes.

A real reclamation needs a running docker daemon. The sandbox has fake `docker` on
PATH that logs every call and exits 0, so the run proves the gate and the exact
command it would run. What a live daemon actually frees is **reported only, machine
check**.

## Rules

| Rule | Threshold | Safety rule, kept from |
| --- | --- | --- |
| `docker-images-80` | disk 80% used or more | dangling images only, never a tagged image (disk-guard) |
| `docker-builder-72h` | `docker builder prune --filter until=72h` | only a builder nobody is waiting on (factory-cleanup) |
| `docker-volumes-smoke` | only names matching `ht-smoke-(build\|state\|dependencies)-*` | never a blanket `docker volume prune`: 12 volumes are attached to containers. Removes one only when `docker ps -a --filter volume=` proves nothing attached (host-disk-sweep, tightened) |
| `docker-missing` | none | with no docker on PATH, the part reports and does nothing |

The builder prune runs on every pass. The image prune runs only past the 80% gate.
The volume rule runs below the gate too, because a leaked volume is not a size
decision.

## How the verify run proves it

1. Sets the sandbox disk at 90% used, past the gate.
2. Expects exactly one `docker image prune -f` call in the fake daemon log.
3. Expects `docker builder prune -f --filter until=72h` in the same log.
4. Expects `docker volume rm ht-smoke-build-1` and `docker volume rm
   ht-smoke-state-2`, from a fake `volume ls` and a fake `ps -a` that shows nothing
   attached.
5. Expects no `docker volume prune` line anywhere, because that command would take
   volumes other containers still use.
6. Reads `items.json` for the gate, the rule and the result of each action.
7. The 60% pass, a volume with a container attached, and the no-docker case run in
   `tests/test_vps_tidy.py`, not in the sandbox.

Reported only, machine check: how many bytes a live prune frees, and whether the
real daemon answers at all. `host-dry-run.json` holds the real host read, with
nothing pruned.

## Evidence

- `json.out`: the docker items, rule by rule.
- `items.json`: gate, command and result for every docker action.
- `host-dry-run.json`: the real daemon read, with nothing pruned.
- `verdict.txt`: `docker_prune`, plus the note that reclamation is unproven.
