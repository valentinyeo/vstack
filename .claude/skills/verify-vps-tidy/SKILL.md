---
name: verify-vps-tidy
description: >-
  Prove that skills/vps-tidy/vps-tidy deletes exactly the stale items, stops exactly the orphan programs and leaves everything else alone. Builds a real sandbox with real sleeping processes, applies the tool to it, grades PASS or FAIL, then dry runs the live host. Use after any change to vps-tidy, as proof on such a PR, and when a chat doubts a tidy result.
---

# Verify vps-tidy

Prior art: checked pstack create-verification-skill, this repo's verify-vps-state and verify-reconcile. Neither drives a destructive tool, so this is the verify-<tool> skill create-verification-skill asks for, with vps-tidy as the app.

The proof bar: the tool's own report is never the evidence. The run seeds a sandbox where every rule has a stale item and a fresh twin, applies the tool to that sandbox only, then reads the filesystem and the process table itself. A run where exactly the stale items are gone, the orphan programs are gone, and every fresh, protected, foreign and shared item survives is a PASS.

Read features/README.md for the map.

## Launch

```sh
.claude/skills/verify-vps-tidy/run                    # this checkout
.claude/skills/verify-vps-tidy/run --script ~/.local/bin/vps-tidy
```

`run` does, in order:

1. Makes ~/.local/state/verify-vps-tidy/<run-id>/ and writes meta.json (script path, git shas, host).
2. Runs the doctor into doctor.txt. Exit 3 when it fails.
3. Builds the sandbox: its own tmp, home, caches, evidence, proc root, process table and PATH shims for npm, pnpm, uv and docker. Stale and fresh twins for every rule, a gh-shared-cache, a worktree, and real sleeping children reported as ppid 1.
4. Runs `--apply` once against the sandbox, then one more pass with no `--root` as a dry run.
5. Kills any child that survived, reads every seeded path back, and grades.
6. Runs one dry run per part against the real host, merged into host-dry-run.json. Nothing is deleted and no process is signalled.
7. Writes verdict.txt and verdict.json.

Exit codes: 0 PASS, 1 FAIL, 3 doctor failure.

## Doctor

- the script exists and is executable;
- python3 and ps are on PATH;
- statvfs works and the run directory is writable.

A failed doctor exits 3 and proves nothing.

## Drive

Only `run` builds the sandbox and only `run` applies the tool to it. Nothing on this host is deleted, signalled or repointed: the apply run is bounded by `--root`, its own proc root and a statvfs fixture.

The process kills are real signals to real pids that the run started, in its own session, with a process table that says ppid 1. A kill that misses shows up as `orphan_gone` FAIL, not as a leftover sleep.

## What makes it fail

- A stale item that is still there, or a fresh twin that went.
- An orphan that survived, or a protected process that died.
- A removal outside the seeded remove list.
- A docker call that prunes all volumes, or an image prune under the 80% gate.
- A zombie named with a kill action instead of `report`.
- A run that exits non-zero, prints no JSON, or overruns.

## Evidence

Every run keeps ~/.local/state/verify-vps-tidy/<run-id>/:

| File | What it proves |
| --- | --- |
| meta.json | which copy of vps-tidy, which commits, which host |
| doctor.txt | the host was worth driving |
| sandbox.json | the seeded remove and keep lists, and the pids |
| json.out, json.err | everything the apply run reported |
| human.out | the report a person sees |
| items.json | one record per item, with rule and result |
| host-<part>.json | the live host read for one part, dry run |
| host-dry-run.json, host-dry-run.txt | the merged live totals |
| verdict.txt, verdict.json | one PASS or FAIL line per check, then the verdict |

Attach verdict.txt to the PR or ticket. CI runs only tests/test_vps_tidy.py; a live host read needs this server.

## Cleanup

`run` deletes nothing outside its sandbox, and kills only the children it started. The sandbox stays inside the run directory as evidence, together with the surviving processes' output, so a person can delete the run directory when it is no longer needed.

## Gotchas

- The sandbox process table is a fixture; the pids in it are real. That is how an ordinary sleep becomes an orphan: the table says ppid 1.
- The docker and board checks are machine checks against shims, not against a live daemon or a logged in board. features/docker.md and features/evidence.md mark those as reported only.
- The live host dry run is per part, because one run over 36k /tmp entries would spend its whole budget before the caches. host-dry-run.txt shows each part's own budget line.
- A host dry run takes about 90 seconds, almost all of it in /tmp.
