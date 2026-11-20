# Caches

The tool caches, the browser builds, repo build output, and the three cache commands.

## Rules

| Rule | Threshold | Safety rule, kept from |
| --- | --- | --- |
| `npm-npx-7d` | `~/.npm/_npx/*` untouched 7 days | nothing open in it (disk-guard, factory-cleanup) |
| `cache-2d` | `~/.cache/go-build`, `node-gyp`, `zig`, `uv` untouched 2 days | only caches the owning tool rebuilds alone; puppeteer, prisma and current Playwright are never listed (disk-guard) |
| `next-build-2d` | `.next` build output untouched 2 days | same list; no puppeteer, prisma or current Playwright (disk-guard) |
| `playwright-superseded` | superseded versions only | never the newest revision of a family; never a revision an installed playwright still lists in `.links`; never when open (disk-guard) |
| `repo-cache-1d` | `.zig-cache`, `target`, `.next/cache` untouched 24 hours | `target` counts only with a `CACHEDIR.TAG` file; `gh-shared-cache`, `worktrees` and the other worktree roots are never touched (factory-cleanup) |
| `ceo-runs-5m-2d` | files over 5 MB untouched 2 days under `~/projects/ceo/runs` | small proof files always stay (factory-cleanup) |
| `npm-clean`, `uv-clean`, `pnpm-prune` | run `npm cache clean --force`, `uv cache clean`, `pnpm store prune` | only when no process with that name is running, and only when the tool is installed (tmp-cleanup, factory-cleanup) |

Disk use is read before and after a run, and `freed_bytes` is reported either way.

## How the verify run proves it

1. Seeds a stale and a fresh `_npx` entry, a stale `go-build`, a fresh `zig`, two
   Playwright builds of one family at 9 days (the older at revision 1000, the
   current at 1200), a stale tagged `target`, a stale untagged `target`, and a
   6 MB plus a small file under `~/projects/ceo/runs`.
2. Expects the stale half of each pair gone and the fresh half alive, with the
   untagged `target` kept for want of a `CACHEDIR.TAG`.
3. Puts fake `npm`, `pnpm`, `uv` and `docker` on PATH that log their arguments, so
   each cache command is proven by its own call line, not by the report.
4. Seeds a worktree `node_modules` at 40 days and a `gh-shared-cache` at 40 days,
   and expects both untouched with no item naming them.
5. Reads every result from the filesystem after the run, then from `items.json`.
6. The `.links` reference case, `.zig-cache`, `.next/cache` and the idle npm case
   run in `tests/test_vps_tidy.py`, not in the sandbox.

## Evidence

- `sandbox.json`: the seeded remove and keep lists after the apply run.
- `items.json`: every candidate with its rule, age in seconds and result.
- `json.out`: the plan, so a keep reason can be read beside its result.
- `verdict.txt`: `stale_gone`, `fresh_alive`.
