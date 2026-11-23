# vstack verification map

This directory is the maintained source for proving one thing: a vstack change keeps every chat working. A chat is the user surface here, so Launch builds a chat's world and Drive starts one. Read this index before driving, then use the matching feature file.

## Baseline preconditions

- Launch installs the checkout under test into a scratch HOME under `/tmp/vstack-verify-home.*`, with its own `.claude` and `.local/bin`. The real `~/.claude`, `~/.local/bin` and `~/.local/share/vstack` are never written.
- The scratch wiring is copied as hook entries only, filtered to hooks this repo owns. No token, credential, permission or model setting is copied.
- `--base REF` (default `origin/main`) is the wiring a chat had before this change. Doctor measures the change against that commit.
- Doctor must pass before Drive runs. A chat wired to missing hooks cannot prove anything.
- Never run the real install from a worktree (VSTA-47). Launch sets `VSTACK_INSTALL_ANYWHERE=1` and `VSTACK_DIR` inside the scratch HOME for exactly this reason.

## Driving conventions

- Only `run` drives. `launch.py`, `doctor.py`, `drive.py` and `grade.py` are its steps, run in that order.
- Doctor is read-only and runs in CI. Drive needs Claude credentials and pace, so it runs on the PR owner's machine.
- Every check reads the harness or the filesystem, never a chat's claim.
- Keep commands literal. Do not edit the scratch HOME mid-run to make a check pass.

## Proof and skip reporting

- A Doctor check that could not run is a FAIL with its reason, never a PASS.
- `DRIVE SKIP` is reported as skipped. It never counts as a pass, and it never fails the run; on a paced host Doctor alone is the merge gate.
- A FAIL on `base-wiring` is a finding about the change, not a broken check. Do not widen the check to make a hook deletion pass.
- Do not report a skipped entry point as verified through another feature.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph. It then uses exactly four H2 sections in this order: `Sub-features`, `How to get to it (user POV)`, `Driving it with verify-vstack`, `Gotchas`.

## Features

| File | Checks | What it proves |
| --- | --- | --- |
| [install-update.md](install-update.md) | `install`, `skill-links`, `drive-skill` | The install that reaches a chat records the commit it came from and links a whole skill tree |
| [hook-wiring.md](hook-wiring.md) | `settings`, `base-wiring`, `wiring`, `hook-links`, `bin-links`, `frontmatter` | Every hook a chat calls resolves, and a change never orphans one |
| [board-drain.md](board-drain.md) | verify-board-drain | A restarted chat re-arms its own drain loop |
| [cloud-agent.md](cloud-agent.md) | `tests/test_cloud_agent.py` | Direct cloud workers refuse a skipped or ahead-of-pace lane before any vendor runs |
| [hypertask.md](hypertask.md) | verify-hypertask | A fresh chat sets itself up on a board and works a task |
| [reconcile.md](reconcile.md) | verify-reconcile | Board sync reads a real board and plans the right moves |
| [repo-tidy.md](repo-tidy.md) | verify-repo-tidy | Worktree and branch cleanup keeps exactly the right ones |
| [responsive-mode.md](responsive-mode.md) | verify-responsive-mode | A chat answers fast and still finishes the job |
| [heavy-local.md](heavy-local.md) | heavy-local hook journey | Each chat blocks heavy jobs locally and points to GitHub |
| [test-timeout.md](test-timeout.md) | verify-test-timeout | The test guard refuses a hung command and passes a wrapped one |
| [valentin-mode.md](valentin-mode.md) | verify-valentin-mode | A fresh chat uses valentin mode's three tools |
| [valentin-subskills.md](valentin-subskills.md) | verify-valentin-subskills | A fresh chat follows valentin mode's sub-rules |
| [vps-state.md](vps-state.md) | verify-vps-state | The host verdict matches a second read of the same host |
