# vps-tidy verification map

The five parts of `skills/vps-tidy/vps-tidy`, and the check that proves each rule.
Every rule comes from the "vps-tidy spec" section of `docs/housekeeping-map.md`.
Read this, then the file for the part.

## The five parts

| File | Part | Rules it covers |
| --- | --- | --- |
| [tmp.md](tmp.md) | `tmp` | `tmp-3d`, `tmp-scratch-24h`, `tmp-agent-template-1d`, `tmp-claude-24h`, plus the name, uid, symlink and protected-tree keeps |
| [caches.md](caches.md) | `caches` | `npm-npx-7d`, `cache-2d`, `next-build-2d`, `playwright-superseded`, `repo-cache-1d`, `ceo-runs-5m-2d`, `npm-clean`, `uv-clean`, `pnpm-prune` |
| [docker.md](docker.md) | `docker` | `docker-images-80`, `docker-builder-72h`, `docker-volumes-smoke` |
| [evidence.md](evidence.md) | `evidence` | `evidence-30d`, `evidence-build-2d`, `evidence-video-14d`, `state-tmp-2d` |
| [processes.md](processes.md) | `processes` | `headless-browser-2h`, `chroma-mcp-7200`, `dev-server-2h`, `provider-1800`, `protected`, `own-uid`, `zombies-report` |

`--only files` means the first four parts. `--dry-run` is the default.

## What a run does

One run id, one directory: `~/.local/state/verify-vps-tidy/<run-id>/`. It holds the
sandbox at `sandbox/` and every evidence file.

1. Writes `doctor.txt` first: python3, `ps`, a working `statvfs`, an executable
   script, a writable run directory. A failed doctor exits 3 and proves nothing.
2. Seeds the sandbox: a `tmp/`, a `home/` with caches, state and projects, a proc
   root and a fake process table. Every rule gets a stale item and a fresh twin.
   Foreign (another uid), protected and shared items go in too.
3. Starts real sleeping children with `start_new_session`. Their rows in the fake
   process table say `ppid 1`, so the orphan rules apply and each kill still lands
   on a real pid. Nothing on this host is signalled.
4. Runs `--apply` once over the sandbox, all five parts, with `--statvfs-json` for
   the disk gate and fake `npm`, `pnpm`, `uv` and `docker` on PATH.
5. Runs one dry run per part with no `--root` against the real host, saved as
   `host-<part>.json` and merged into `host-dry-run.json`. Nothing is deleted and
   no process is signalled.
6. Grades every check and writes `verdict.txt`.

## The grading rule

PASS only when every check holds. The five that decide it:

- `stale_gone`: exactly the seeded stale items are gone.
- `orphan_gone`: every seeded orphaned process is gone, none left half killed.
- `fresh_alive`, `protected_alive`: every fresh, protected, foreign and shared
  item survives, and every protected process still runs.

Then `removed_count` must match the stale list, `nothing_else_removed` must find no
path outside it, `zombie_reported` must show the zombie named and not signalled,
and `docker_prune` must show the right pruning and no blanket volume prune. The run
itself must exit 0, its JSON must parse, and it must finish inside its time budget.

A fresh item that went, or a stale item that stayed, is a FAIL. A check that could
not run is a FAIL with its reason, never PASS. A sandbox with nothing stale in it
proves nothing, so the run refuses to grade it.

## Evidence

| File | What it proves |
| --- | --- |
| meta.json | which copy of vps-tidy, which commits, which host |
| doctor.txt | the host was worth driving |
| json.out | the apply run's own report as data |
| items.json | one record per item from the apply run, with rule and result |
| sandbox.json | the seeded remove and keep lists, and the pids the run started |
| host-<part>.json | the live host read for one part, dry run |
| host-dry-run.json, host-dry-run.txt | the merged live totals |
| verdict.txt | one PASS or FAIL line per check, then the verdict |

CI runs only `tests/test_vps_tidy.py`. A run that touches the real host stays on the
server.
