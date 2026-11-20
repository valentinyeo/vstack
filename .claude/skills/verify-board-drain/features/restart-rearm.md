# Restart re-arm

A chat that restarts finds its old loop dead: session cron jobs die with the process, and a recurring cron expires after 7 days. `skills/board-drain/SKILL.md` says read the status, arm a loop over your own view, then record it. On Claude Code that arm is a tracked background `watch` plus a safety cron; Codex keeps a plan-paced cron (at least every 2 hours).

## Sub-features

- `rearm.load`: the chat loads board drain, through the `/board-drain` command or the `Skill` tool.
- `rearm.status`: it asks `loop-state status --name "<its name>"` before arming, because exit 0 means already armed.
- `rearm.arm`: either (a) a `Bash` call with `run_in_background: true` whose command runs `skills/board-drain/watch` (or `./watch`) with this chat's `--board` and `--label`, plus a safety `CronCreate` that fires at least every 6 hours; or (b) a recurring job on the plan pace (from `~/.local/bin/plan-pick --loop-interval`, at least every 2 hours), whose prompt is the loop prompt from the skill, naming its own board and view. Path (a) needs no loop prompt on the cron: the watcher is the loop, the cron is the net under it.
- `rearm.record`: `loop-state arm` writes `armed_at` in this run, `expires_at` about 7 days later, and the job id the harness handed back, without dropping `last_sync` or watch fields.

## How to get to it (user POV)

- A chat restarts, or `drain-check` prints `loop state: not armed`.
- The user asks it to keep its board work going. It should not need to be told to arm again.

## Driving it with run

Preconditions: the run seeds an expired state file with the pid of a dead process, and refuses to start unless `loop-state status` exits 2 on it.

- Action: `run`. Result: `stream.jsonl` holds the `loop-state status` call, the watcher and safety cron (or plan-paced cron) and the `loop-state arm` call; `state.json` is what the chat left behind.
- Check `armed`: either the background watcher on board `2060` and label `vvm-test` with a safety cron firing within 6 hours, or a recurring cron firing no sooner than every 2 hours with the loop prompt.
- Check `recorded`: `armed_at` is at or after the run start, `expires_at - armed_at` is 7 days within an hour, and `job` equals the id in the create's tool result.

## Gotchas

- `CronCreate` is deferred behind `ToolSearch` on this Claude Code version. The chat often searches for the tool first; that is normal and does not fail anything.
- The tool result text is `Scheduled recurring job <id> (Every 6 hours)...` for safety crons. The grade reads the id from there.
- `--break no-board-drain` runs the same prompt without the command and with `--disable-slash-commands`. Expect `loaded` to fail and the expired loop to stay untouched.
- Dropping the command alone is not a break on this server. The installed description ends "Use at session start, after a restart or handover", so the prompt "you just restarted after a crash" makes the chat load board drain by itself, and a measured run passed every check without being told. That is VSTA-4 working, not a rubber stamp: the break has to take the skill away.
- A one-shot job (`recurring: false`), a cron firing more often than every 2 hours, or an hourly cron fails `armed` on purpose. Those rhythms drain the Claude plan or leave the queue idle too long.
- A watcher on another board or label, or one the chat did not start in the background, fails `armed`: it wakes nobody in this chat, and a foreground call blocks the chat instead of waking it. A safety cron that fires once a day fails too; six hours is the longest silence allowed.