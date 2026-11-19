# Board reconcile

`skills/hypertask-work/reconcile` reads board 2060 and GitHub.
The house-rules `fleet/reconcile` path is a shim that execs this copy.
Board 15 uses the same script with `--board 15`.
Default runs print plans without moving tickets.
`--section Doing` limits a dry run.
`--apply` previews first, then permits five moves.
`--limit N` changes that per-run cap.
A plan over the cap applies only the first N moves.
Moves backed by a live worker or an open or merged PR go first.
Moves back to Todo go last.
Each tier is ordered by ticket number.
The rest print DEFERRED and the next run picks them up.
Any UNKNOWN also refuses every move.
Each move writes an agent-log entry.
Owners and assignees stay unchanged.

## Column rules

Earlier rows take priority.

| Fact | Column |
| --- | --- |
| Already Valentin Review, Done, or Not now | Keep |
| Any column outside this table | Keep |
| Waiting on Valentin or blocked by another ticket | Keep |
| Open PR, checks running, red, or missing | Checks |
| Open PR, checks green | AI Review |
| Every matching PR merged, current-head PASS | AI Review, live proof pending |
| Merged PR without current-head PASS | AI Review |
| Fresh lease with a live local PID, or a live process that names the ticket | Doing |
| In Verification Backlog without the `verification` label | Todo |
| In Verification Backlog with the label | Keep |
| In Todo with the `verification` label | Verification Backlog |
| Ticket touched within two hours | Keep |
| No live worker or matching PR | Todo |

A verification ticket carries the label `verification` and starts in Verification Backlog.
A labelled ticket in Todo moves to Verification Backlog on the next run.
An unlabelled ticket in that column moves back to Todo.
Once worked, a verification ticket follows the same rows as any other ticket, so a PR or a live worker still outranks the label.
Boards without the column are unchanged.

An open or merged PR outranks a live worker.
Recent activity only delays the fallback to Todo.
A waiting ticket or one with a blocker keeps its column.
Building and Verifier are accepted as the renamed forms of Doing and AI Review.
A board that shows them gets moves under those names.

A passing open PR waits in AI Review.
Merged work waits there for live proof.
This script never moves work into Done.
Searches include both fleet owners across repositories.
PR ownership requires one structural link.
The title or branch contains the ticket key.
An anchored `Ticket:` line also qualifies.
An exact Hypertask ticket URL qualifies anywhere.
Other body mentions establish no ownership.
Branch discovery scans both owners.
It reads every open PR, and PRs merged in the last 30 days.
That is two searches per run: one for open PRs, one for the merged range.
Merged PRs are kept in `~/.local/state/fleet/cache` (`FLEET_CACHE_DIR` overrides it).
The next run searches only the days since the last run, plus one day of overlap.
A ticket older than the cache reaches back only as far as it needs.
A cache that cannot be read means one full search, never a failed run.
The window starts later when the oldest candidate ticket is newer than that.
Tickets older than the window also get a search for branches that start with their key.
GitHub matches only the start of a branch name there.
An older merged PR needs a title, `Ticket:` line or URL link, or a branch that starts with the key.
Date partitions avoid GitHub search truncation.
GitHub calls run one after another, never side by side.
An open PR is read every run, with one `gh pr view`.
A merged PR is read once and kept; one without a PASS is read again after six hours.
The PR comments and the verifier policy are read for merged PRs only, and the policy only when a verdict names the head.
Each run prints one line to stderr, `reconcile: github calls=N (graphql=a, rest=b)`.
A paginated read counts once.
Each phase prints one progress line to stderr.
`RECONCILE_TIMING=1` adds a per-phase table of seconds and external calls.
Malformed keys report UNKNOWN without stopping other tickets.
A `createdAt` that does not parse costs that ticket only: it searches full history.
Closed, unmerged PRs count as no PR.
Read failures print UNKNOWN and prevent that move.
Fresh foreign-host leases also prevent moves.
Stale leases expire after fifteen minutes.

A lease is not the only sign of a live worker.
One run reads every local command line under `/proc` once.
A live process counts for a ticket when it is an agent CLI (`hax`, `pi`, `codex`, `cursor-agent`, `claude`, `opencode` or `gemini`, behind any wrapper) and its arguments hold the exact ticket URL,
`https://app.hypertask.ai/detail/project-<board>/<n>`,
or the exact ticket key as a whole token.
Word boundaries keep `SOFT-27` away from `SOFT-2730`, and the key `SOFT-2730b` proves nothing.
This catches workers started outside the lease wrapper: `hax -p`, `pi -p`, `codex exec`,
`cursor-agent`, and `claude -p`.
Own board only; a URL for another board proves nothing.
The reconcile process and its parents never count, because their brief names tickets.
Any other command that names a ticket only looks at it, so it never counts: a search, `grep`, `git`, an editor, a shell or script run in its worktree.
Leases still win; the process fallback only adds liveness.
Board 15 keeps its worker-service facts and does not read processes.
`FLEET_PROC_DIR` overrides the process directory for tests.

PASS requires a structured `verify-verdict` comment.
The comment must name the current PR head.
The base `.verify/policy.json` controls trusted verifier identities.
Author and verifier model families must differ.
The verdict must link successful GitHub-hosted verification.
The run must match head and approved workflow.
Missing policy means no accepted PASS.
Plain PASS prose and green checks cannot qualify.

## Worker leases

Spawn helpers wrap the worker command.
Add this one line at worker launch.

```sh
skills/hypertask-work/lease "$KEY" run -- worker-command worker-arguments
```

The wrapper records the worker PID.
It renews every sixty seconds.
It removes the lease when that worker ends.
`fleet/runner` watches each launched attempt automatically.
Other launchers can watch an existing worker.

```sh
skills/hypertask-work/lease "$KEY" watch --pid "$WORKER_PID" &
```

Manual lifecycle commands remain available.

```sh
skills/hypertask-work/lease "$KEY" start --pid "$WORKER_PID"
skills/hypertask-work/lease "$KEY" beat --pid "$WORKER_PID"
skills/hypertask-work/lease "$KEY" end --pid "$WORKER_PID"
```

Leases live in `~/.local/state/fleet/leases/<KEY>.json`.
Each contains `pid`, `host`, `started`, and `last_beat`.
Timestamps use Unix seconds.
Atomic writes prevent partial JSON reads.
A live worker cannot replace another worker's lease.
Repeated starts retain the original start time.
Repeated ends are harmless.
`FLEET_LEASE_DIR` overrides the directory for tests.

## Server timer

The supplied timer runs every fifteen minutes.
Installation enables capped board moves after preview.
The current backlog may exceed the default cap.
Such runs apply the first moves and report the rest as DEFERRED.
Later runs work through the remainder.
Keep installation for the approved release.

The service uses the house-rules shim `~/.local/share/house-rules/fleet/reconcile`.
The shim execs this skill's copy.
Its environment comes from `~/.config/fleet/reconcile.env`.
That file supplies the agent's `HT_TOKEN`.
Use mode `0600` for the environment file.
`SHIP_SESSION_NAME` defaults to Poteto in the service.
Override it alongside the matching agent token.
GitHub access uses the server's `gh` login.

After release approval, install the timer.

```sh
~/.local/share/house-rules/bin/install-fleet-reconcile.sh
```

The installer installs supplied user-service files.
Runs serialize through the board-specific lock.
An overlapping run reports SKIP and succeeds.
Apply rechecks tickets and PR facts after preview.
Changed tickets skip that run.

## Self-test

Run the focused self-test from the vstack checkout.

```sh
python3 skills/hypertask-work/reconcile --self-test
```


## Board 15

`skills/hypertask-work/reconcile --board 15` previews Hypertask moves.
`--board 2060` preserves Software Factory behavior.
Omitting `--board` also selects Software Factory.
Board 15 ticket keys start with `HTPR-`.
PRs come from `hypertask-ai/hypertask`.
Live workers move tickets to In Progress.
Open PRs move tickets to AI Review.
Live workers take priority over open PRs.
Recent changes keep their two-hour grace.
Idle tickets stay in their current column.
Tickets never move back to Backlog.
UX needed and UX Sign-off stay.
Agent Blocked (Infra) and Valentin Review stay.
QA and every Flag column stay.
No Flag and unknown columns also stay.
Each run permits at most five moves.
Board 15 keeps this hard cap, even with a higher `--limit`.
Moves over the cap print DEFERRED and wait for the next run.

Worker facts use the installed Hypertask workers.
An active service alone proves no ticket work.
Its local PID must still exist.
Its queue must name that board's ticket.
Claiming, launching, and running count as active.
Progress expires after fifteen minutes.
Unreadable worker facts refuse all moves.

The board-15 service template installs no timer.
Its environment file is `~/.config/fleet/reconcile-board15.env`.
Supply `HT_TOKEN` there, with mode `0600`.
Use the vcc or HT Product Lead token.
The vcc identity is "Valentins Claude Code".
The script verifies the connected agent before writes.
Missing, personal, or other agent tokens fail.
Never supply Valentin's personal token.
