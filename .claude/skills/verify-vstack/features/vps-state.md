# The host verdict matches a second read

`skills/vps-state/vps-state` answers whether this server can take another chat, worker, build or test run, and a second read of the same host agrees with every number it prints. A script that prints a nice block nobody checked is not proof.

## Sub-features

- `json`: `--json` parses and carries a verdict and a facts block.
- `cores`, `load5`, `mem_avail_gb`, `disk_free_gb`, `disk_used_pct`: each reported number agrees with a read by another tool, inside its tolerance.
- `exit-codes`: `--can-launch worker` and `--can-launch chat` exit with the code the verdict names, 0 ADD, 1 CAREFUL, 2 HOLD.
- `human`: the block leads with the same verdict line `--brief` printed, names how many chats, workers and builds run and the heaviest two, and carries the `procs` and `heavy` lines.
- `cleanup`: the clean-up section names the clean-up skill, `~/.local/bin/host-disk-sweep` and `~/.local/bin/tmp-cleanup`, and states the rule: clean only what this session made, never another session's files.
- `status`: `~/.local/state/vps-load/status` starts with this run's worker verdict word (`add`, `steady` or `hold`), then `load5=<x>` with two decimals and `cores=<n>`.
- `hook`: `hooks/vps-state-hook` exits 0 and prints `Server: <the brief line>` plus the hint `run ~/.local/bin/vps-state before starting chats or workers`, in under three seconds.
- `brief`: `--brief` prints one line, and it is the same verdict line the human block leads with.
- `disk-warning`: at 85% used or more on `/`, the worker and chat verdicts stop at CAREFUL (never HOLD), and the reason line names `repo-tidy --prune-caches --project .` and `vps-tidy --apply`. Below 85% the verdict is unchanged. Driven by `tests/test_vps_state.py` `DiskWarning`, which feeds a fixture statvfs so the check does not depend on this host's free space.
- `speed`: the slowest of the JSON, brief and human runs stays under five seconds.

## How to get to it (user POV)

- Open a session and read the first line: `Server: HOLD worker, CAREFUL chat: load5 1.9x cores`.
- Run `"$HOME/.local/bin/vps-state"` for the block, or `--brief` for the same one line, or `--json` for every number.
- Run `"$HOME/.local/bin/vps-state"` and read the last section before cleaning up, then run the tool it names from the session that owns those files.
- A script asks `"$HOME/.local/bin/vps-state" --can-launch worker` and reads the exit code.

## Driving it with verify-vstack

Preconditions:

- This shared VPS, where `/proc`, `ps`, `free` and `df` describe the real machine. A GitHub runner has no host worth reading, so the live run stays on this server.
- `~/.local/bin/vps-state` may be an older installed copy: `run` drives this checkout unless `--script` says otherwise.
- `python3`, `ps`, `free` and `df` are on `PATH`, because the independent read uses them, and `/proc/loadavg` is readable. Anything missing stops the run with exit 3 before it drives.
- One run per second: run ids are whole seconds and a rerun in the same second reuses a directory.

- **Real run.** Run `.claude/skills/verify-vstack/tools/vps-state/run`. It writes `meta.json`, runs the doctor, then drives `--json`, `--brief`, the human block, `--can-launch chat`, `--can-launch worker` and the SessionStart hook, then reads the host again with `nproc`, `/proc/loadavg`, `free -b` and `df -B1 /` into `live.json` and grades. Exit 0 PASS, 1 FAIL, 3 doctor failure. There is no server to start and nothing to seed.
- **Another copy.** Run `.claude/skills/verify-vstack/tools/vps-state/run --script ~/.local/bin/vps-state`.
- **How each check reads.** The five numbers and `cores` are compared with `live.json`: load5 within 25%, memory within 5%, disk free and disk percentage within 2%, cores exact. The exit codes are compared with the verdict inside the JSON, never with a chat's claim. `human` needs the `cleanup` heading and its rule line in the saved block, and the `procs` and `heavy` lines. `hook` needs two lines, the `Server: ` prefix, exit 0 and under three seconds, and `run` executes it with its own HOME and a `PATH` without vps-state, so the installed link cannot hide a broken repo copy.
- **How processes are counted.** A chat is an interactive `claude`; a worker is `claude -p` or `--print`, `pi -p`, `codex exec`, `cursor-agent` or `hax`; a build is node, bun, cargo, zig, pytest, playwright or chrome; a shell wrapper is none of these and counts as other. `--no-cleanup` skips the scans and still prints the rules.
- **Evidence.** `meta.json`, `doctor.txt`, `json.out`, `brief.out`, `human.out`, `can-launch-chat.code`, `can-launch-worker.code`, `hook.out`, `hook.code`, `reported.json`, `live.json`, `status.txt`, `verdict.txt` and `verdict.json`, under `~/.local/state/verify-vps-state/<run-id>/`. Attach `verdict.txt` to the PR or ticket.
- **Cleanup.** `run` deletes nothing and starts no long-lived process, and every evidence directory stays until a person deletes it. It does rewrite `~/.local/state/vps-load/status` on purpose: that is the state every fleet runner reads.

## Gotchas

- Tolerances are part of the grade. A failing `load5` on a host under 40 load usually means the two reads landed in different minutes, not a broken script.
- `--can-launch` exits 3 when a core probe failed. That is a FAIL for the run, not a HOLD. `--can-launch` also never counts an unknown probe as agreement.
- The hook prints nothing when vps-state is missing, and still exits 0, because a session must never fail to start over a capacity probe. That silence is a FAIL for `hook`, by design.
- The worker ADD rule is also the fleet runner gate in house-rules `fleet/runner`: load5/cores below 1.0 and integer gigabytes above 24. `RunnerGate` fails when the two drift, so change both or neither.
- The two host reads are seconds apart, so on a host near a threshold the verdict itself can flip between them. Only the numbers behind it are compared.
- The `/tmp` total adds top-level entry sizes only, so a big directory can show as 0M: treat the count as the fact and the size as a hint. Worktrees whose PR closed but did not merge are not listed, because nothing here calls GitHub.
- Every `bash -c ...` row is a wrapper, not the worker it launches, and on this host a `claude --print` worker sits under a `python3 -u -c exec(...)` parent. Counting either would double the workers and overstate the room line. Process arguments are cut to 100 characters.
- The hook finds its script through `$VPS_STATE_BIN`, then `~/.local/bin/vps-state`, then the checkout next to it, always by absolute path, because a Claude Code Bash shell's `PATH` has no `~/.local/bin`. Each chat registers the SessionStart hook in its own project's `.claude/settings.json` with the JSON in `skills/vps-state/SKILL.md`; this repo only ships and links the file.
- Never edit `~/.local/state/vps-load/status` by hand to force a verdict: the run rewrites it from what it measured, and that rewrite is one of the checks. When `/proc/loadavg` cannot be read the file says `load5=unknown`, which never matches `^add`, so a broken probe holds the fleet rather than flooding it.
- Exit 3 means the doctor failed, not that the host is fine.
