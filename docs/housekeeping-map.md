# Housekeeping map: every cleanup tool on this VPS, where it goes

VSTA-7 (was SOFT-2940). Measured on this host on 2026-11-20 between 13:00 and 14:00 CET.

The owner's target is three tools and no central instance, no central timer:

- `vps-state`, read-only: load, memory, disk, processes, and the ADD / CAREFUL / HOLD verdict. Built in `soft-2935-vps-state`, and it ships its own "Set up your own check" step.
- `repo-tidy`: all git worktree and branch cleanup, gated on shipped + clean + not in use. Built in `soft-2937-repo-tidy`, and it ships its own "Set up your own check" step.
- `vps-tidy`: files and processes. Built and merged in PR 208 (branch `vsta-7-vps-tidy`), and its skill carries its own "Set up your own check" step.
- No shared housekeeping instance and no shared timer. Each chat runs `vps-state`, `repo-tidy` and `vps-tidy` from its own loop or hooks, and a maintainer never runs one for another chat. The old timers still retire: disable, archive, 7-day undo.

Today housekeeping runs from twelve schedules across eleven tools: five systemd user timers (`tmp-cleanup`, `disk-guard`, `evidence-prune`, `proc-watchdog`, `factory-cleanup`), three services with no timer at all (`host-disk-sweep`, `worktree-reaper`, `agent-provider-reaper`), and four lines in `valentin`'s crontab (`orphan-reaper` hourly at :25, `reap-orphan-devservers` every 15 min, `qa-browser-reaper` every 30 min, `tmp-cleanup` Sunday 04:45). `tmp-cleanup` is the one tool counted twice: its own timer runs Sunday 03:30 and the crontab runs it again Sunday 04:45.

This page is the map. Nothing here deletes anything and nothing here installs a timer. Every caller moves in step order below, and deletions come last, through an archive directory.

Verdict counts: **KEEP 8, MERGE->vps-state 1, MERGE->repo-tidy 3, MERGE->vps-tidy 10, DELETE 7**, 29 rows.

## Retired since this map (2026-11-21 and 2026-11-24)

This map was measured on 2026-11-20. Each retirement below was disabled first, then copied to an archive, so undo is one command. Nothing here is scheduled.

| Tool | Where it went |
|---|---|
| `heavy-guard` + `heavy-guard.service` | Retired 2026-11-21 into `~/.local/state/retired-housekeeping/2026-11-21/`. It killed local zig/build/Wine jobs every 5s. VSTA-162 owns the remaining heavy guard. |
| `proc-watchdog` + `.service/.timer` | Retired 2026-11-21 into the same archive. Its process rules are in the vps-tidy spec. |
| `agent-provider-reaper` + `.service` | Retired 2026-11-21 into the same archive. |
| `mb-watch`, `mp-watch` | Retired 2026-11-21 into the same archive. They restarted chat sessions, so no cleanup tool replaces them. |
| `tmp-cleanup` + `.service/.timer` | Retired 2026-11-24 into `~/.local/state/retired-housekeeping/2026-11-24/`. vps-tidy's tmp and evidence rules replace it. |
| `evidence-prune` + `.service/.timer` | Retired 2026-11-24 into the same archive. vps-tidy's evidence rules replace it. |
| `factory-cleanup.sh` + `.service/.timer` | Retired 2026-11-24 into the same archive. vps-tidy's tmp, caches and docker rules replace it. |

Undo: copy the unit and script back from the archive, then run `XDG_RUNTIME_DIR=/run/user/1000 systemctl --user enable --now <unit>`.

`vps-tidy` has no timer: each chat runs it from its own loop. `disk-guard.timer` still runs as the server's last disk guard; its source lives in `hypertask-ai/hypertask`, so retiring it needs a ticket there.


---

## Real numbers

`df -h /` at 13:55: `/dev/sda1` 678G size, **593G used, 85G free, 88%**. Inodes 19% used. Every `du` below ran with `timeout 60` and `--block-size=1M`.

| Target | Size | Which cleaner can reach it today |
|---|---|---|
| `~/.local/state/gh-shared-cache` | **56G** | none |
| `~/.local/state/gh-shared-cache-app` | **19G** | none |
| `~/.cache` (whole) | 14.3G | disk-guard: zig 1.1G at 2+ days, node-gyp 132M, superseded playwright only |
| `~/.cache/ms-playwright` | 3.3G | disk-guard: old versions only |
| `~/.local/share/pnpm` | 7.2G | factory-cleanup: `pnpm store prune` |
| `~/projects/worktrees` | 11G | disk-guard, factory-cleanup, repo-tidy-to-be |
| `~/.local/state/hax` | 5.2G | none |
| `~/.local/state/vcc-evidence` | 5.0G | evidence-prune: builds 2+ days, videos 14+ days; tmp-cleanup: children 30+ days |
| `~/.local/state/drain` | 3.8G | none |
| `~/.npm` | 1.3G | tmp-cleanup: `npm cache clean --force`. Its children are `~/.npm/_npx` 1.3G and `~/.npm/_cacache` 1M; `_npx` is reached by disk-guard at 7 days |
| `~/projects/multiprompt-worktrees` | 1.2G | disk-guard, factory-cleanup |
| `~/projects/.worktrees` | 1.0G | disk-guard |
| `~/projects/hypertask-worker-trees` | 4.0K (empty) | worktree-reaper (dead) |
| docker images | 7.52G, **4.79G reclaimable** | disk-guard at 80%+ (dangling only), host-disk-sweep (dead) |
| docker build cache | 1.53G, **0 reclaimable** | factory-cleanup, `until=72h` |
| docker volumes | 1.05G, 157M reclaimable | host-disk-sweep only (dead); disk-guard never prunes volumes |
| `/tmp` | du did not finish in 60s | tmp-cleanup, factory-cleanup |
| `/tmp/claude-1000` | 127M | tmp-cleanup (3 days), factory-cleanup (24h) |
| `/tmp/tmp.*` 78 dirs | 250M | host-disk-sweep (2 days), factory-cleanup (24h), tmp-cleanup (3 days) |
| `/tmp/igsh*` 29 dirs, `/tmp/mpa-*` 540 dirs | 215M, 100M | factory-cleanup (24h) |
| `/tmp/b15` 1,539 entries | du did not finish in 60s | none, it is a worktree root, not a scratch dir |
| `~/projects/ceo/runs` files over 5M older than 2 days | **0 files** | factory-cleanup finds nothing |

`docker system df` at 13:55: images 7.519GB with 4.791GB reclaimable, volumes 1.049GB with 156.7MB, build cache 1.527GB with 0B. Total docker reclaimable: **4.9G** (4.79G images plus 157M volumes). The build cache is 1.53G but none of it can be reclaimed, so it is not a win.

Worktrees registered in `~/projects/hypertask` alone: **758**.

Biggest files the cleaners keep for themselves: `~/.local/state/worktree-reaper.log` 7.3M, `~/.local/state/factory-cleanup.log` 7.5M, `~/.local/state/disk-guard/log` 1.1M plus `log.1` 5.2M.

### The five biggest disk wins, measured

1. **75G in two GitHub caches nothing prunes**: `gh-shared-cache` 56G, `gh-shared-cache-app` 19G. That is 11% of the 678G volume (and 13% of the 593G in use), and no housekeeping script names either one.
2. **7.2G pnpm store**, reached today by one line inside factory-cleanup.
3. **14.3G of `~/.cache`**, of which disk-guard can only reach 1.2G plus old Playwright versions.
4. **13.2G across the three worktree roots** (11G, 1.2G, 1.0G), with 758 registrations in one repo. This is repo-tidy's whole reason to exist.
5. **4.9G of docker** reclaimable (4.79G images, 157M volumes). The 1.53G build cache has 0 reclaimable, so it is not on this list.

Next in line: `~/.local/state/vcc-evidence` 5.0G, `~/.local/state/hax` 5.2G, `~/.local/state/drain` 3.8G.

---

## The map

One row per item. Paths abbreviate `/home/valentin` as `~`.

| Item | Does | Runs | Last run | Callers | Owner | Overlaps | Verdict | Why |
|---|---|---|---|---|---|---|---|---|
| `~/.local/bin/vps-load-check` + `vps-load-check.service` | Writes `add/steady/hold load5=… cores=…` to `~/.local/state/vps-load/status` and appends `history.log` (capped 2000 lines) | `vps-load-check.service` is `static` in systemd, never loaded, and no `.timer` exists anywhere; `systemctl --user list-units '*vps-load*'` = 0 units. `vps-state` now rewrites the status file on every run (PR 175), so what readers see is fresh even though nothing schedules this script | history last line `2026-11-15T00:37:21`; the status file was rewritten `2026-11-20 13:23:59` by `vps-state`, not by this script | `~/.local/share/house-rules/fleet/runner:424` (`grep -q '^add'`), `~/projects/ceo/bin/hax-runner:25` (`grep -q '^hold'`), `~/projects/ceo/RUNNER.md:64`, `~/projects/ceo/red/RUNNER.md` | vstack `house-rules/fleet`; `poteto-2-advisor/bin/jobs.json` already marks it `delete-planned` | `vps-state` answers the same question better | MERGE->vps-state | Move the verdict, not the file: `vps-state` owns the status file from PR 175 and rewrites it each run, so both callers drop the file read and call `vps-state --can-launch worker` (exit 0/1/2). No caller may read `vps-load/status` after that, or a runner depends on a file nothing schedules |
| `~/.local/bin/host-disk-sweep` + `host-disk-sweep.service` | `docker volume prune -f`, `docker image prune -f`, removes `/tmp/agent-template-stage.*` older than 1 day and `/tmp/tmp.*` older than 2 days; logs MB freed, warns at 85% | service `static`, no `.timer`, `is-enabled` = `not-found`, and no crontab line | log last entry `2026-10-08T03:30:01`, `freed 0 MB, now used 82%` | none in any searched tree | none, script lives only in `~/.local/bin` | `tmp-cleanup`, `factory-cleanup` (`/tmp`), `disk-guard` (images), `vps-tidy` | MERGE->vps-tidy | Dead since 2026-10-08, but `docker volume prune` is the only volume rule on the box and disk-guard deliberately never prunes volumes. vps-tidy takes the volume rule first, the file is archived after |
| `~/.local/bin/tmp-cleanup` + `tmp-cleanup.service/.timer` | Removes `/tmp` children untouched 3 days, excluding `claude-*`, `tmux-*`, `.X*`, `systemd-*`; same under `/tmp/claude-<uid>/*/`; `vcc-evidence` children untouched 30 days; `npm cache clean --force`; `uv cache clean` | timer active + enabled, `Sun 03:30`, and `valentin`'s crontab runs the same script Sunday 04:45, so it runs twice every Sunday | `2026-11-15T03:30`, log last line `after: 72%` | its own timer at `Sun 03:30`; `crontab -u valentin`, `45 4 * * 0`; `vps-state` SKILL.md names it as a housekeeping tool | none in a repo, `~/.local/bin` only | `evidence-prune` (vcc-evidence), `factory-cleanup` and `host-disk-sweep` (`/tmp`), everything vps-tidy | MERGE->vps-tidy | The 30-day evidence rule and the `claude-*` / `tmux-*` / `.X*` / `systemd-*` exclusions are the safety spine of vps-tidy. Take them verbatim. Its double schedule is why nobody can say which run freed what |
| `~/.local/bin/worktree-reaper` + `worktree-reaper.service` | Removes worktrees under `~/projects/hypertask-worker-trees` once the count passes `CAP=20` and the branch is merged or gone; keeps dirty and unpushed trees; `rm -rf node_modules .next` in kept trees | service `Type=simple`, no timer, not loaded, no crontab line | log `2026-09-10T00:37:56`, `trees_before=115 trees_after=114` | none in any searched tree | none, `~/.local/bin` only | `repo-tidy`, `disk-guard` worktree rule, `factory-cleanup` | DELETE | No timer, no caller, and its own root is now empty (4.0K). Its one unique trick, dropping `node_modules` and `.next` from a kept tree, goes into the vps-tidy spec so it is not lost |
| `~/.local/bin/worktree-cleanup-weekly` (31K bash) | Removes only worktrees holding a `CLEANUP_READY` lease: merged PR, clean tree, every GitHub and remote-ref query green; moves the tree into a private quarantine path before removal, holds a per-worktree lock, restores on any doubt | no unit and no crontab line; called from `~/.local/bin/fleet-watchdog:153`, and that line calls the other copy `~/.hypertask-worktree-cleanup/bin/worktree-cleanup-weekly` | `~/.local/state/hypertask-worktree-cleanup` last written 2026-09-01 | `~/.local/bin/fleet-watchdog:153` | `hypertask-ai/hypertask` `scripts/worktree-cleanup-weekly.sh` | `repo-tidy`, all of it | MERGE->repo-tidy | It is the only worktree cleaner with a lease. repo-tidy must adopt the lease file and its fields, the quarantine move, the per-worktree lock, and "every GitHub and remote-ref query must succeed before cleanup starts" |
| `~/.local/bin/agent-worktree-refresh` | Fetches `hypertask-ai production` and detaches a dedicated agent worktree to `FETCH_HEAD` | nothing runs it | unknown, no log | none found | none, `~/.local/bin` only | `repo-tidy` | MERGE->repo-tidy | The value is the five skip conditions: dirty tree, branch checked out, commits not on any remote, active advisor unit, `index.lock`. repo-tidy must refuse to move a tree on any of them |
| `~/.local/bin/orphan-reaper` | Kills `chroma-mcp` and `agent-browser-chrome` with `ppid=1` older than `MAX_AGE=7200s`; logs RAM before and after | no unit. `valentin`'s crontab runs it hourly at :25 (`25 * * * *`), read with `sudo -n crontab -l -u valentin` on 2026-11-20 | 2026-08-20T01:25:11 (last kill); log mtime 2026-11-20T13:25 | `crontab -u valentin`, `25 * * * *` | none, `~/.local/bin` only | `vps-tidy` process rules, `proc-watchdog`, `agent-provider-reaper` | MERGE->vps-tidy | Take the `ppid=1` rule, the 2h age, both patterns and the RAM delta line |
| `~/.local/bin/reap-orphan-devservers` | Kills `next dev` whose cwd is inside a `wt-*` worktree, whose top ancestor is init, with no claude or codex cwd in that worktree, older than 30 minutes | no unit. `valentin`'s crontab runs it every 15 minutes (`*/15 * * * *`), read on 2026-11-20 | `2026-11-19T20:15:11`, killed 2 orphans in `/tmp/b15/wt-bombadil` | `crontab -u valentin`, `*/15 * * * *` | none, `~/.local/bin` only | `vps-tidy`, `proc-watchdog` | MERGE->vps-tidy | It is the only rule that protects a dev server belonging to a live claude session. All four criteria must survive the merge |
| `~/.local/bin/qa-browser-reaper` | Kills any `headless_shell`, `chrome --headless` or `agent-browser` older than 120 minutes | no unit. `valentin`'s crontab runs it every 30 minutes (`*/30 * * * *`), read on 2026-11-20 | `2026-11-19T21:30:01` | `crontab -u valentin`, `*/30 * * * *` | none, `~/.local/bin` only | `vps-tidy`, `proc-watchdog` | MERGE->vps-tidy | Take it as-is, with the age cutoff and the explicit note that a legitimate long-lived browser would be killed |
| `~/.local/bin/agent-provider-reaper` + `agent-provider-reaper.service` | Kills a `codex`, `claude`, `hax` or `node` process with `ppid=1`, older than `REAP_GRACE_SECONDS=1800`, whose HOME or cwd sits in `~/.local/state/hypertask-*/`. Never touches a provider attached to a live worker | service `Type=simple`, no timer, inactive, no crontab line | no log or state found | none; named in `company-skills/agents/Hypertask Product/background-jobs.md` | `hypertask-ai/hypertask` worker, ticket HTPR-5591 | `vps-tidy` process rules, `proc-watchdog` | MERGE->vps-tidy | Its kill list contains `claude`. vps-tidy must carry the agent-state-dir proof and a hard "never kill claude outside that proof" rule before this one is retired |
| `~/.local/bin/hetzner-chat-sweep` | Read-only ssh comparison of Hetzner chat replies against the raw transcript. Deletes nothing | never, no unit, no timer, no crontab line | never | none | IGSH-1822, one-off investigation | none | DELETE | Dead and not a cleaner. Archive it |
| `~/.local/bin/stale-agent-assignee-sweep` | Drops agent assignees from tickets sitting in queue sections unless the ticket is pinned, running or behind an open PR | `~/.local/bin/pr-feedback-loop:333`; `pr-feedback.service` is `static` and inactive and there is no `pr-feedback.timer` | `~/.local/state/pr-feedback` last written 2026-09-21 | `pr-feedback-loop:333` | `hypertask-ai/hypertask` worker, HTPR-5685 | none of the three tools | KEEP | It cleans board state, not disk or processes. It also exposes a fault: the loop that calls it has no timer, so it has not run since September |
| `~/.local/bin/fleet-watchdog` | Restarts dead agent workers, breaks the starvation loop, sends one Telegram alert per key per 6h, and at line 153 runs worktree cleanup | its header says cron every 15 minutes, but `valentin`'s crontab (read 2026-11-20) does not list it and `fleet-watch.service` does not exist, only `fleet-watch.service.d` | `~/.local/state/fleet-watch/last.txt` 2026-11-14T15:07 | `~/.local/bin/fleet:30` parses its `SLUGS` and starvation loop | vstack `house-rules/fleet` | `repo-tidy` only through its one worktree call | KEEP | Fleet control, not housekeeping. Its housekeeping call moves in migration step 3, then this file is left alone |
| `~/.local/bin/agent-fleet-watchdog` | Alerts on stalled agents and comment loops with one ticket comment plus a toast | `agent-fleet-watch.service` is gone; `agent-fleet-watch.service.d/paused-2026-09-21.conf` sets `ExecStart=/bin/true` | log `2026-08-20T10:30:01` | none | none, superseded by `fleet-watchdog` | `fleet-watchdog` | DELETE | Paused since 2026-09-21 and replaced. Archive it |
| `agent-fleet-watchdog.bak-1788818272`, `fleet-watchdog.bak-htpr-6308-1788893561`, `fleet-watchdog.before-factory-isolation-1789060825` | Nothing, they are copies | nothing | n/a | none | none | their originals | DELETE | Backup copies with no caller. `~/.local/bin` holds 68 of these in total |
| `~/.local/state/disk-guard/disk-guard.py` (62K) + `disk-guard.service/.timer` + `low-priority.conf` + `hourly.conf` | At 75% used it prunes caches until 70%: docker dangling images at 80%+, tool caches `go-build` `node-gyp` `zig` `uv` at 2 days, `npx` at 7 days, `next-build` at 2 days, worktree `node_modules` at 3 days, superseded Playwright, npm cache. Also removes clean, inactive, old and remotely-contained worktrees, and idle Claude scratchpads. Moves deletions through its own trash, refuses symlinks, mount points, foreign owners and open files, and stops at a time budget | `disk-guard.timer` active + enabled, originally every 15 min, `disk-guard.timer.d/hourly.conf` replaces `OnCalendar` with `hourly` | `2026-11-20T12:12:14`, level `clean`, used 86.51%, removed 1 worktree | its timer; `~/projects/hypertask/scripts/heavy-job.sh:11` reads its `critical` marker to refuse a heavy job at 90% | `hypertask-ai/hypertask` `.claude/skills/ship/scripts/disk-guard.py`. The installed copy is 5 days behind the repo (62371 B at 2026-10-17 vs 62762 B at 2026-10-23) | all four tools | MERGE->vps-tidy, its worktree rule -> repo-tidy | It is the only cleaner with thresholds, a trash, an open-file check and a time budget. vps-tidy should be this script plus the others, not a fourth rewrite. The app repo owns the source, so the move needs their ticket |
| `~/.local/lib/hypertask/evidence-prune` + `.service/.timer` | In `~/.local/state/vcc-evidence`: removes `.next`, `node_modules`, `build-*`, `.pnpm-store`, `node-v*` at 2 days, videos at 14 days only when the ticket is not open and the board read succeeds, and `state/*/tmp` at 2 days. `O_NOFOLLOW`, a device check per path step, an inode recheck before removal | `evidence-prune.timer` active + enabled, daily 00:15 plus up to 30 min jitter, run with `--apply` | `2026-11-20T00:22` | its timer only | ship skill, `hypertask-ai/hypertask` | `tmp-cleanup` (30-day evidence rule), `vps-tidy` | MERGE->vps-tidy | The "board read must succeed or keep the videos" rule and the inode recheck are the strongest safety code on the box. Move the file, do not rewrite the logic |
| `~/projects/ceo/bin/factory-cleanup.sh` + `.service/.timer` | Every 6h: removes `/tmp/claude-<uid>/<project>/<uuid>` untouched 24h with nothing open, skips `*-hypertask*` and `*ht-marketing*`; removes `/tmp` `igsh*` `wazi*` `mpa-*` `tmp.*` owned by me and untouched 24h; removes worktrees of 6 repos 12h after their PR closed or HEAD is on origin, saving dirty ones with `wip-save.sh` first and never WIP-pushing a hypertask tree; removes `~/projects/ceo/runs` files over 5M older than 2 days; removes `.zig-cache`, every `target` holding `CACHEDIR.TAG`, `.next/cache` untouched 24h; runs `npm cache clean`, `pnpm store prune`, `docker builder prune --filter until=72h`; files one urgent board 4060 ticket at 85% used | `factory-cleanup.timer` active + enabled, `00,06,12,18:30` plus 20 min jitter | `2026-11-20T13:13:20`, running while this was written | its timer; `~/projects/ceo/bin/runner-cleanup.sh:8` shares its log path | `~/projects/ceo` (CEO runners) | `tmp-cleanup`, `evidence-prune`, `disk-guard`, `repo-tidy` | MERGE->vps-tidy, its worktree half -> repo-tidy | Take the `lsof` open-path check, the live-session UUID check, the `wip-save` before removal, the `CACHEDIR.TAG` proof and the 85% board alarm. The alarm must move, or the disk stops filing its own ticket |
| `~/.local/lib/hypertask/infra-prune` (from `~/projects/poteto-2-advisor/bin/infra-prune`) + `infra-prune.service` | Archives and merges tickets on board 11514 to hold a cap, waking one Sonnet pass only over the cap | `infra-prune.service` exists, `infra-prune.timer` does not, so it never runs | last run log `~/.local/state/fleet-watch/infra-prune-20261114T0640.log` | `bin/jobs.json` row with `keep=true`, `control.conf` beats it per run | `poteto-2-advisor` (HYCI) | none of the three tools | KEEP | It prunes a board, not disk or processes. Another team owns it and their own plan marks it `delete-planned` |
| `~/.local/lib/hypertask/proc-watchdog/proc-watchdog.py` + `.service/.timer` | Stops test, build and premerge process trees whose root is older than 2h or whose members pass 6 GiB, and 8 GiB for roots marked `PREMERGE_NEXT_BUILD=1`; stops `ht-premerge-*` containers older than 12h; `SIGTERM`, 10s grace, `SIGKILL`; never matches claude, tmux, services or dev servers; one JSON line per kill; one warning per sweep | `proc-watchdog.timer` active + enabled, every 5 min after 3 min from boot | `~/.local/state/proc-watchdog/kills.log` last entry `2026-11-20T00:09:12Z` | timer; `~/projects/hypertask/scripts/premerge-local.sh` | `hypertask-ai/hypertask` scripts, YPER4-278 and YPER4-280 | `vps-tidy` process rules, orphan-reaper, qa-browser-reaper, agent-provider-reaper | MERGE->vps-tidy | This is the process half of vps-tidy: the only process killer with a real schedule, a grace period and a structured log, so move it rather than rewrite it. It also cannot see python test trees, which is the 2026-11-20 incident below |
| `approved-sweep.service` | Records unattended approvals and orphan claims on their tickets | no timer, inactive | unknown | none | `company-skills` kit | none of the three tools | KEEP | A merge-gate bookkeeping tool, not a cleaner. `jobs.json` marks it `delete-planned` for its owner |
| `premerge-evidence.service` | Publishes required premerge browser evidence statuses | no timer, inactive | unknown | referenced by repo workflows | `hypertask-ai/hypertask` | none of the three tools | KEEP | A required-status publisher, not a cleaner. Removing it here would break checks other repos rely on |
| `multibot-watchdog-day.service/.timer` | Reads real desktop watchdog coverage for IGSH-1170 | timer active + enabled, hourly | `2026-11-20T12:30:32` | its timer | Multibot team | none | KEEP | Another team's observation job, not a cleaner |
| `launchpadlib-cache-clean.service/.timer` | Cleans its own `~/.cache/launchpadlib` | distro unit in `/usr/lib/systemd/user`, timer active, daily 20:00 | `2026-11-19T20:00:03` | distro package | Ubuntu `python3-launchpadlib` | none | KEEP | Ships with the OS, touches only its own cache, costs nothing |
| `~/.claude/skills/clean-up` | Human-run session cleanup: only this session's worktrees, clean tree, PR merged, local tip equals the PR `headRefOid`, never stash, never another session's tree, keeps `vcc-evidence` | invoked by hand and from `/ship` | n/a | `/ship` checklist, `ship-check cleaned` | vstack house-rules | `repo-tidy`, entirely | MERGE->repo-tidy | The `headRefOid` equality rule and "never another session's worktree" must survive as `repo-tidy --mine`. The skill then becomes a one-line wrapper |
| `~/.hypertask-worktree-cleanup/bin/worktree-cleanup-weekly` (56K, 2026-09-02) | An older second copy of the leased cleaner, and the copy `fleet-watchdog` actually calls | via `fleet-watchdog:153` | 2026-09-01 | `fleet-watchdog:153` | none | `repo-tidy`, its own newer copy | DELETE | Two copies differ and the scheduled caller uses the older, unowned one. Archive it after step 3 |
| `~/.local/lib/hypertask/evidence-prune/{evidence-prune.service,evidence-prune.timer}`, `~/.local/lib/hypertask/proc-watchdog/{proc-watchdog.service,proc-watchdog.timer}`, `~/projects/poteto-2-advisor/systemd/infra-prune.service` | Copies of unit files that also live in `~/.config/systemd/user` | n/a, these are install sources | n/a | the `--install` paths | each owning repo | every unit row above | DELETE | Two sources of truth for the same unit. Keep the repo copy as the source, remove the `~/.local/lib` copies once installs read from the repo |
| `~/.config/systemd/user/fleet-watch.service.d/`, `agent-fleet-watch.service.d/` | Drop-in directories whose unit files no longer exist | n/a | n/a | none | none | `fleet-watchdog`, `agent-fleet-watchdog` | DELETE | Leftovers. `agent-fleet-watch.service.d/paused-2026-09-21.conf` keeps a unit alive that is otherwise `/bin/true` |
| `house-rules` skills that mention cleanup: `hypertask-triage/scripts/board-health`, `hypertask-triage/scripts/agent-feedback`, `tickets/scripts/blocker-sweep.py`, `support-manager`, `solo-dev`, `tickets` | Board and process hygiene: scorecards, feedback filing, stale blocker questions, prod data prunes | on demand | n/a | the skills that call them | vstack `house-rules` | none of the three tools | KEEP | They never touch disk or processes. Out of scope |

---

## 2026-11-20 incident: a python test tree is invisible to proc-watchdog

Four `python3 -m unittest discover -s scripts` runs took 10 to 15 hours each. `proc-watchdog` never stopped one. Lines 45-53 of `proc-watchdog.py` match `node`, `bun`, `vitest`, `jest`, `playwright`, `next` and `vite` only, so a python test tree matches nothing and runs until it finishes or the box gives out.

The fix is a test-timeout guard in VSTA-37, a separate PR. It does not wait for vps-tidy: vps-tidy only inherits the gap if it copies the pattern list as-is, so the python pattern belongs in VSTA-37 first.

---

## vps-tidy spec

The union of every behaviour above that is still wanted, each with the safety rule that came with it. vps-tidy is one program with one lock and one log. `--dry-run` is the default; `--apply` is the only way to delete or kill. It has no timer of its own: each chat calls it from that chat's loop or hooks.

### Files

| What | Age and size rule | Safety rule, kept from |
|---|---|---|
| `/tmp` top-level children | untouched 3 days, by newest mtime inside the tree, not the directory's own mtime | skip `claude-*`, `tmux-*`, `.X*`, `systemd-*`; own uid only (tmp-cleanup) |
| `/tmp/claude-<uid>/<project>/<session>` | untouched 24h | the leaf must match a UUID; nothing open in it per `lsof`; skip `*-hypertask*` and `*ht-marketing*` (factory-cleanup) |
| `/tmp/igsh*`, `/tmp/wazi*`, `/tmp/mpa-*`, `/tmp/tmp.*` | untouched 24h | the dir must be owned by me (`-O`); nothing open (factory-cleanup) |
| `/tmp/agent-template-stage.*` | 1 day | name must match; `rm -rf` only inside `/tmp` (host-disk-sweep) |
| `~/.local/state/vcc-evidence` | whole folder children untouched 30 days | never a cache target, ever; the folder is on disk-guard's `NEVER_CACHE` list (tmp-cleanup, disk-guard) |
| `~/.local/state/vcc-evidence` builds inside it | `.next`, `node_modules`, `build-*`, `.pnpm-store`, `node-v*` at 2 days | `O_NOFOLLOW`, device check per path step, inode and mtime recheck immediately before removal (evidence-prune) |
| `~/.local/state/vcc-evidence` videos | 14 days | the board read must succeed and the ticket must not be open, or the video stays (evidence-prune) |
| `~/.local/state/*/tmp` | 2 days | the parent must be a checked state dir (evidence-prune) |
| npm cache | `npm cache clean --force` | only after a run has shown the tool is idle (tmp-cleanup, factory-cleanup) |
| uv cache | `uv cache clean` | same (tmp-cleanup) |
| `~/.npm/_npx/*` | untouched 7 days | nothing open in it (disk-guard, factory-cleanup) |
| tool caches `go-build`, `node-gyp`, `zig`, `uv` | untouched 2 days | only caches the owning tool rebuilds alone. Puppeteer, prisma and current Playwright are never listed (disk-guard) |
| Playwright browsers | superseded versions only | never the current version (disk-guard) |
| `.next` build output | untouched 2 days | (disk-guard) |
| worktree `node_modules` | untouched 3 days, worktree unchanged 3 days | only when `git check-ignore -q node_modules` passes; never in a worktree with an open PR; never when a process has cwd, fd or root inside (disk-guard, factory-cleanup) |
| repo build caches: `.zig-cache`, `target`, `.next/cache` | untouched 24h | `target` counts only with a `CACHEDIR.TAG` file; slowdown-free proof that the build regenerates (factory-cleanup) |
| pnpm store, docker builder cache | `pnpm store prune`, `docker builder prune --filter until=72h` | only builders nobody is waiting on (factory-cleanup) |
| docker dangling images | disk 80%+ used | dangling only, never tagged images (disk-guard) |
| docker volumes | only leaked `ht-smoke-(build\|state\|dependencies)-*` volumes | never a blanket `docker volume prune`: 12 volumes are attached to containers. This is the one behaviour taken from host-disk-sweep, tightened |
| `~/projects/ceo/runs` files over 5M | older than 2 days | small proof files always stay (factory-cleanup) |
| orphans: worktrees whose main repo no longer exists | report only, never delete | 33 such folders exist today and disk-guard refuses all of them (disk-guard) |

Global file rules, non-negotiable:

1. `--one-file-system` and a `st_dev` check per path. Never cross a mount, never follow a symlink (`O_NOFOLLOW`).
2. Never touch `.git`, `.config`, `.ssh`, `.claude`, `.codex`, or `~/.local/state/vcc-evidence` as a cache.
3. Never touch a path with a foreign owner, a special file, or a process holding it open (`lsof` plus a `/proc` cwd, fd and root scan).
4. Delete through a trash directory first (`~/.local/state/disk-guard/trash` already exists and does this), so an interrupted run can finish or a mistake can be undone.
5. Recheck inode, device and mtime immediately before removal. Uncertainty blocks deletion, always.
6. A time budget per run, resuming where the last run stopped. disk-guard's log shows `time budget reached` 29,036 times in one hour on this host, so the budget is not optional.
7. Log one line per action with bytes freed, and a summary with `used_percent`, `removed`, `would_free` and a keep reason for every candidate.
8. Keep the 85% board alarm: one urgent ticket on board 4060, updated instead of duplicated. This is the only thing today that tells a human the disk is filling.

### Processes

| What | Threshold | Safety rule, kept from |
|---|---|---|
| test, build and premerge trees | root older than 2h, or any member over 6 GiB (8 GiB for a root marked `PREMERGE_NEXT_BUILD=1`) | never match claude, tmux, a systemd service or a dev server; `SIGTERM`, 10s grace, `SIGKILL`; one JSON line per kill; add a python test-tree pattern, which proc-watchdog lacks today (VSTA-37) |
| `ht-premerge-*` containers | older than 12h | marker-only, never a plain container (proc-watchdog) |
| provider processes `codex`, `claude`, `hax`, `node` | `ppid=1`, older than 1800s | HOME or cwd must sit inside `~/.local/state/hypertask-*/`; a provider attached to a live worker is never touched; never kill `claude` outside that proof (agent-provider-reaper) |
| `next dev` | older than 30 minutes | cwd inside a `wt-*` worktree, top ancestor init, and no claude or codex cwd in the same worktree (reap-orphan-devservers) |
| `chroma-mcp`, `agent-browser-chrome` | `ppid=1`, older than 7200s | logged with RAM before and after (orphan-reaper) |
| headless chrome, `agent-browser` | older than 120 minutes | a real QA case finishes in minutes; blanket age cutoff (qa-browser-reaper) |

Global process rules:

1. Only this user's processes (`-u "$USER"`). Never root's, never another account's.
2. Check the whole tree, not just the top pid, and never kill a tree with a member whose cwd is inside a path on the protect list.
3. Log every stop to one file, `~/.local/state/vps-tidy/kills.log`, with pid, kind, reason, processes and cwd.
4. One warning per sweep to INFRA MANAGER, so a repeated kill is visible.

### Shape

- One binary, `vps-tidy`, with `--dry-run` (default), `--apply`, `--json`, `--only files|processes`.
- No central timer and no central instance. Each tool ships a `## Set up your own check` step with the loop or hook snippet that calls it, and vps-tidy refuses a run it cannot attribute to a calling session. Old timers retire by disable, archive, 7-day undo, not by replacement with one shared timer.
- One `flock`, so two runs can never overlap.
- `vps-state` reads vps-tidy's status file and prints it. vps-tidy never prints a verdict of its own.

---

## Migration order

Eleven steps. Callers first, timers off before files go, archive instead of `rm`, delete last. Every step ends in a check that must be seen passing.

1. **Land vps-state on main.** Check: `skills/vps-state/vps-state --brief` prints a verdict on this host, and `--can-launch worker` exits 0, 1 or 2.
2. **Move the two `vps-load/status` readers to the command, not the file.** `vps-state` already rewrites that file on each run (PR 175), so the file is fresh, but a caller must stop depending on it. Change `~/.local/share/house-rules/fleet/runner:424` and `~/projects/ceo/bin/hax-runner:25` to call `vps-state --can-launch worker` and `--can-launch chat`. Check: `grep -rn 'vps-load/status' ~/.local/share/house-rules ~/projects/ceo` returns nothing, and one runner tick logs the new verdict line.
3. **Move the one worktree caller.** Point `~/.local/bin/fleet-watchdog:153` at the repo copy of `worktree-cleanup-weekly`, then at `repo-tidy --leased`. Check: `grep -c worktree-cleanup-weekly ~/.local/bin/fleet-watchdog` is 0 and `~/.hypertask-worktree-cleanup/bin/worktree-cleanup-weekly` is never read again.
4. **Land repo-tidy with the lease.** Check: `repo-tidy --dry-run` prints one keep or remove line per worktree, and every removal names merged-or-pushed, clean, no open PR and not in `lsof`. Run it beside disk-guard for one week and diff their decisions.
5. **Move the /ship clean-up skill onto repo-tidy.** Check: `/ship` on a scratch ticket reaches `ship-check cleaned` printing `cleaned ok` with no manual `git worktree remove`.
6. **Turn off the two worktree rules at their source.** Stop disk-guard's worktree pass and factory-cleanup's worktree pass (both are env switches today: `FC_SKIP_WORKTREES` for factory-cleanup). Check: one week of logs shows repo-tidy removed every worktree those two would have removed, and neither log has a removal line.
7. **Land vps-tidy as disk-guard's body plus the union rules above.** Check: `vps-tidy --dry-run` prints a keep reason for every candidate, its plan frees at least what tmp-cleanup, evidence-prune, factory-cleanup and proc-watchdog last freed in total, and `used_percent` is reported.
8. **Move the three cron reapers to each chat's own loop.** Replace the crontab lines with `vps-tidy --only processes` called from the loop or hooks of the chat that owns those processes. Check: `crontab -u valentin` has no reaper line left, the calling chat's loop logs one vps-tidy process pass, and `pgrep -f 'orphan-reaper|qa-browser-reaper|reap-orphan-devservers'` is empty.
9. **Disable, do not delete, the five timers and the four crontab lines, for 7 days.** `systemctl --user disable --now tmp-cleanup.timer evidence-prune.timer proc-watchdog.timer factory-cleanup.timer disk-guard.timer`, and comment out the `orphan-reaper`, `reap-orphan-devservers`, `qa-browser-reaper` and `tmp-cleanup` cron lines. Check: systemd has no housekeeping timer left, `crontab -u valentin` has no housekeeping line left, each tool is called by a chat's own loop, and after 7 days `df -h /` used percent is no higher than the day they were disabled.
10. **Archive the dead files.** `mkdir -p ~/.local/state/retired-housekeeping/2026-11-20` and `mv`, never `rm`, every DELETE row into it: `worktree-reaper` and `worktree-reaper.service`, `hetzner-chat-sweep`, `agent-fleet-watchdog`, its three copies `agent-fleet-watchdog.bak-1788818272`, `fleet-watchdog.bak-htpr-6308-1788893561` and `fleet-watchdog.before-factory-isolation-1789060825`, `~/.hypertask-worktree-cleanup/bin/worktree-cleanup-weekly`, the duplicate unit files and the two orphaned drop-in directories. The files retired by an earlier merge (`host-disk-sweep`, the old `worktree-cleanup-weekly`) go in the same pass. Check: every DELETE row resolves inside the archive, and none of the names remains in `~/.local/bin` or `~/.config/systemd/user`.
11. **Empty the archive after 7 clean days.** Check: `~/.local/state/retired-housekeeping/2026-11-20` is gone and `systemctl --user list-timers` still starts clean.

One line to hold onto: nothing in this map may delete anything until step 4 and step 7 have run one real cycle with their dry-run decisions logged.
