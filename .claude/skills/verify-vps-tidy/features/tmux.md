# Tmux

Stale private tmux servers, dead socket files under `/tmp/tmux-<uid>/`, and idle
default-server sessions that outlived a chat.

## Rules

| Rule | Threshold | Safety rule |
| --- | --- | --- |
| `tmux-server-24h` | private socket, server older than 24h | every pane `cat`/`sleep` or an interactive shell with no children; no attached session; no protected session name; roster `name`/`tmux`/`multibot` and `{n}`/`{*}` patterns count as protected |
| `tmux-dead-socket` | socket with no server, mtime older than 60m | two matching no-server probes with one 3s sleep for the whole batch; never delete `default` |
| `tmux-default-3d` | default session older than 3d | not attached, one pane, idle shell only, name not under `live-*`, `term-*`, `projects*`, `mp-*`, or roster |

`kill-server` runs with `TMUX` cleared and `MULTIPROMPT_ALLOW_TMUX_KILL_SERVER=1` in
the child only. The tmux part runs after `processes` so the shared time budget
still reaches orphan reaping.

## How the verify run proves it

Sandbox unittest coverage in `tests/test_vps_tidy.py` (`TmuxRules`,
`TmuxProbeContract`) exercises temp sockets only. The host dry run includes a
`tmux` part entry in `HOST_PARTS` and saves `host-tmux.json` with no deletes on
the live server.