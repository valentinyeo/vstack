# vps-state verification map

The parts of the host answer this skill proves, each one check in `run`. Read this, then the file for the check.

## Baseline preconditions

- `.claude/skills/verify-vps-state/run` runs on the shared VPS, where /proc, `ps`, `free` and `df` describe the real machine.
- A GitHub runner can run the unit tests only. There is no host worth reading there, so the live run stays on this server.
- `~/.local/bin/vps-state` may be an older installed copy. `run` drives this checkout unless `--script` says otherwise.

## Driving conventions

- One run per second. Run ids are whole seconds and a rerun in the same second reuses a directory.
- Never edit `~/.local/state/vps-load/status` by hand to make a check pass. The run rewrites it from what it measured.
- Read the verdict from `verdict.txt`, never from a chat's summary.

## Proof and skip reporting

- Every check reads a saved file: the script's own output, an exit code, or the second read in `live.json`.
- A check that could not run is reported FAIL with its reason, never PASS. A probe that says unknown never counts as agreement.
- A FAIL on `load5` under heavy load is usually two reads minutes apart. Rerun before chasing it; do not widen the tolerance to hide it.

## Features

| File | Checks | What it proves |
| --- | --- | --- |
| [verdict.md](verdict.md) | `json`, `cores`, `load5`, `mem_avail_gb`, `disk_free_gb`, `disk_used_pct`, `exit-codes` | The verdict and its numbers match a second read, and the exit codes match the verdict |
| [process-breakdown.md](process-breakdown.md) | `json`, `human` | Chats, workers and builds are counted, and the top talkers are named |
| [housekeeping.md](housekeeping.md) | `cleanup` | The clean-up section names the tools and the rule, and deletes nothing |
| [status-file.md](status-file.md) | `status` | The file every fleet runner reads carries this run's worker verdict |
| [session-hook.md](session-hook.md) | `hook`, `brief`, `speed` | Every session opens with the one line, in under 3 seconds |
