# Evidence

`~/.local/state/vcc-evidence`, the build folders inside it, the videos, and the
state tmp dirs.

A video goes only when the board read answers. The sandbox has no logged in
Hypertask, so the run proves the safe half: with no board answer, the video stays.
A live board answer is **reported only, machine check**.

## Rules

| Rule | Threshold | Safety rule, kept from |
| --- | --- | --- |
| `evidence-30d` | each child of `vcc-evidence` untouched 30 days | never a cache target, ever; the folder is on disk-guard's `NEVER_CACHE` list (tmp-cleanup, disk-guard) |
| `evidence-build-2d` | inside a kept child, `.next`, `node_modules`, `build-*`, `.pnpm-store`, `node-v*` untouched 2 days | `O_NOFOLLOW`, a device check per path step, and an inode and mtime recheck just before removal (evidence-prune) |
| `evidence-video-14d` | videos at 14 days, and only then | ticket id must be in the path, the board read must succeed, and the ticket must be closed (evidence-prune) |
| `state-tmp-2d` | `~/.local/state/<parent>/tmp` untouched 2 days | the parent must be a known state dir, on the fixed list (evidence-prune) |
| `no-follow` | none, always kept | a symlink or a non-directory child is never removed (all) |

Build folders are walked only inside a child the 30 day rule kept. A whole stale
ticket folder goes as one item, not as its parts.

## How the verify run proves it

1. Seeds one evidence child at 40 days and one fresh child, and expects the first
   gone and the second intact.
2. Inside the fresh child, seeds `.next` at 3 days and a fresh `.next`, and expects
   the stale one gone, the fresh one alive and the parent app folder still there.
3. Seeds `~/.local/state/hax/tmp` at 3 days and expects it gone.
4. Seeds a 20 day video in a path that carries no ticket id, with no board reader
   configured, and expects it kept. That is the fail-safe the old cleaner had: a
   failed or missing board read never costs a video.
5. Expects no item anywhere under `vcc-evidence` with action `prune`, because that
   folder is never a cache.
6. The three board answers (failed, open, closed) and an unknown-parent tmp dir run
   in `tests/test_vps_tidy.py`, not in the sandbox.

Reported only, machine check: whether the real board answers for a real ticket, and
what a live run would then remove.

## Evidence

- `items.json`: each child, build folder and video, with age, rule and result.
- `sandbox.json`: the seeded remove and keep lists after the apply run.
- `json.out`: the plan, including the keep reason each video rested on.
- `host-dry-run.json`: the real evidence folder read, with nothing removed.
- `verdict.txt`: `stale_gone`, `fresh_alive`, `untouched_alive`, plus the note that
  the live board read is unproven.
