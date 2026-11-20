# Restart re-arm

A chat that restarts finds its old loop dead: session cron jobs die with the process, and a recurring cron expires after 7 days. `skills/board-drain/SKILL.md` says read the status, arm a loop over your own view, then record it. On Claude Code that arm is a tracked background `watch` plus a safety cron; Codex keeps the 15-minute cron.

## Sub-features

- `rearm.load`: the chat loads board drain, through the `/board-drain` command or the `Skill` tool.
- `rearm.status`: it asks `loop-state status --name "<its name>"` before arming, because exit 0 means already armed.
- `rearm.arm`: either (a) a recurring job that fires every 15 minutes of every hour (`*/15 * * * *`, `0,15,30,45 * * * *`, `7,22,37,52 * * * *`), whose prompt is the loop prompt from the skill, naming its own board and view; a `Skill` call to `loop` with `15m` and that prompt counts too; or (b) a `Bash` call with `run_in_background: true` whose command runs `skills/board-drain/watch` (or `./watch`) with this chat's `--board` and `--label`, plus a safety `CronCreate` that fires at least every 6 hours. Path (b) needs no loop prompt: the watcher is the loop, the cron is the net under it.
- `rearm.record`: `loop-state arm` writes `armed_at` in this run, `expires_at` about 7 days later, and the job id the harness handed back.

## How to get to it (user POV)

- A chat restarts, or `drain-check` prints `loop state: not armed`.
- The user asks it to keep its board work going. It should not need to be told to arm again.

## Driving it with run

Preconditions: the run seeds an expired state file with the pid of a dead process, and refuses to start unless `loop-state status` exits 2 on it.

- Action: `run`. Result: `stream.jsonl` holds the `loop-state status` call, the `CronCreate` (or `loop`) call and the `loop-state arm` call; `state.json` is what the chat left behind.
- Check `armed`: either the 15-minute create above, or the background watcher on board `2060` and label `vvm-test` with a safety cron firing within 6 hours.
- Check `recorded`: `armed_at` is at or after the run start, `expires_at - armed_at` is 7 days within an hour, and `job` equals the id in the create's tool result.

## Gotchas

- `CronCreate` is deferred behind `ToolSearch` on this Claude Code version. The chat often searches for the tool first; that is normal and does not fail anything.
- The tool result text is `Scheduled recurring job <id> (Every 15 minutes)...`. The grade reads the id from there. A chat that arms through `/loop` leaves no id, and `recorded` then skips the job comparison only.
- `--break no-board-drain` runs the same prompt without the command and with `--disable-slash-commands`. Expect `loaded` to fail and the expired loop to stay untouched.
- Dropping the command alone is not a break on this server. The installed description ends "Use at session start, after a restart or handover", so the prompt "you just restarted after a crash" makes the chat load board drain by itself, and a measured run passed every check without being told. That is VSTA-4 working, not a rubber stamp: the break has to take the skill away.
- A one-shot job (`recurring: false`) or an hourly cron fails `armed` on purpose. Neither keeps a queue moving through the day.
- A watcher on another board or label, or one the chat did not start in the background, fails `armed`: it wakes nobody in this chat, and a foreground call blocks the chat instead of waking it. A safety cron that fires once a day fails too; six hours is the longest silence allowed.
