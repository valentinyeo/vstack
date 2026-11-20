# Processes

The stray programs: orphaned dev servers, orphaned providers, headless browsers and
the agent helpers.

## Rules

| Rule | Threshold | Safety rule, kept from |
| --- | --- | --- |
| `headless-browser-2h` | older than 120 minutes | blanket age cutoff; a real QA case finishes in minutes, and a legitimate long browser is killed anyway (qa-browser-reaper) |
| `chroma-mcp-7200` | `ppid 1` and older than 7200 seconds | RAM before and after, logged (orphan-reaper) |
| `dev-server-2h` | older than 2 hours | cwd inside a `wt-*` worktree, top ancestor init, and no `claude` or `codex` cwd in that same worktree (reap-orphan-devservers) |
| `provider-1800` | `ppid 1`, older than 1800 seconds | HOME or cwd must sit inside `~/.local/state/hypertask-*/`; a provider attached to a live worker is never touched; `claude` is never killed outside that proof (agent-provider-reaper) |
| `protected` | none, always kept | never `claude`, `tmux`, `codex`, `pi`, and never a tree holding a shell, `systemd`, `sshd` or `init` (proc-watchdog, agent-provider-reaper) |
| `own-uid` | none, always kept | only this user's processes, never root's or another account's (all) |
| `zombies-report` | none, reported only | a zombie is named and never signalled (proc-watchdog) |

Stop sequence: `SIGTERM`, a 10 second grace, then `SIGKILL`. One JSON line per kill
in `~/.local/state/vps-tidy/kills.log` with pid, kind, reason and cwd.

The spec said 30 minutes for `next dev`. The script now uses 2 hours, the same age
as any other dev server. Worth a board 2060 ticket if 30 minutes was the intent.

## How the verify run proves it

1. Starts real sleeping children with `start_new_session`, then writes rows into
   the sandbox process table with `ppid 1`. The kill is a real signal to a real pid,
   and the fake table is what makes the orphan rule fire. No host process is
   touched.
2. One orphan `next dev` at 3 hours in a `wt-*` worktree: gone afterwards, and the
   grade key is `orphan_gone`.
3. The same server with a live `claude` cwd in that worktree, a `claude -p` child,
   and a young dev server at 600 seconds: all three alive after the run.
4. A `codex` at 99 hours inside a hypertask state dir, and another user's headless
   chrome: both alive, and both named as kept with their reason.
5. A `hax` provider at 3600 seconds inside a hypertask state dir: gone. A headless
   chrome at 9 hours: gone.
6. A zombie row at 5 hours: reported with action `report`, never signalled, and
   `zombie_reported` is its grade.
7. The `SIGTERM`-ignoring child, `chroma-mcp`, `tmux` and `pi` run in
   `tests/test_vps_tidy.py`, not in the sandbox.

## Evidence

- `sandbox.json`: the pids the run started, split into those that must die and
  those that must live.
- `items.json`: pid, kind, age, rule, action, result and the signals used.
- `json.out`: the plan, so a would-kill is visible beside the kill that followed.
- `verdict.txt`: `orphan_gone`, `protected_alive`, `zombie_reported`.
