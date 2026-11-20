# Temp files

`/tmp`, its per-user claude scratchpads, and the three scratch name families.

## Rules

| Rule | Threshold | Safety rule, kept from |
| --- | --- | --- |
| `tmp-3d` | untouched 3 days, measured by the newest mtime inside the tree, not the directory's own | own uid only; skip `claude-*`, `tmux-*`, `.X*`, `systemd-*` (tmp-cleanup) |
| `tmp-scratch-24h` | untouched 24 hours | name must start `igsh`, `wazi`, `mpa-` or `tmp.`; owned by me (`-O`); nothing open in it (factory-cleanup) |
| `tmp-agent-template-1d` | untouched 1 day | name must match `agent-template-stage.*`; removal stays inside `/tmp` (host-disk-sweep) |
| `tmp-claude-24h` | untouched 24 hours | leaf must be a session UUID; skip projects named `*-hypertask*` and `*ht-marketing*`; nothing open per `lsof` (factory-cleanup) |
| `excluded`, `claude-scratch-skip`, `claude-scratch-uuid` | none, always kept | the exclusions are the safety spine; a session dir without a UUID leaf is never touched (tmp-cleanup, factory-cleanup) |
| `own-uid`, `no-follow`, `special-file` | none, always kept | never a foreign owner, never a symlink, never a device or socket (all) |
| protected tree | none, always kept | a tree holding `.git`, `.config`, `.ssh`, `.claude` or `.codex` stays whole (disk-guard) |

Open check: `lsof` plus a `/proc` scan of cwd, fd and root.

## How the verify run proves it

1. Seeds `tmp/verify-stale` at 5 days and `tmp/verify-fresh` just written.
   `stale_gone` and `fresh_alive` decide the part.
2. Seeds `tmux-verify`, `.X11-unix` and a tree holding `.git`, all at 5 days, and
   expects each kept whole.
3. Seeds `claude-<uid>/verify-project/<uuid>` and
   `claude-<uid>/verify-hypertask/<uuid>` at 2 days. The first goes, the second
   stays because of its project name.
4. Seeds `agent-template-stage.verify` and `igshverify` at 2 days, both past their
   rules, and expects both gone.
5. Seeds a symlink to the shared github cache at 40 days and expects it kept and
   never followed.
6. Runs one `--apply` over the sandbox, then reads each seeded path back from the
   filesystem, not from the report.
7. The newest mtime case, the non-UUID leaf and the foreign owner run in
   `tests/test_vps_tidy.py`, not in the sandbox.

## Evidence

- `sandbox.json`: the seeded remove and keep lists, so survival can be rechecked.
- `items.json`: one record per seeded path, with rule, age, action and result.
- `json.out`: the same plan as data, so an action can be compared with its result.
- `verdict.txt`: `stale_gone`, `fresh_alive`, `protected_alive`.
