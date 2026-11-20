# Process breakdown

What is actually running: chats, workers, builds, everything else, and the processes eating CPU and memory.

## Sub-features

- `json`: the `processes` block holds a count, total RSS and total CPU per kind, the top eight by CPU and by RSS, and the median RSS of a chat and of a worker.
- `human`: the block one line names how many of each kind are running and the heaviest two.
- Kinds: a chat is an interactive `claude`; a worker is `claude -p` or `--print`, `pi -p`, `codex exec`, `cursor-agent` or `hax`; a build is node, bun, cargo, zig, pytest, playwright or chrome; a shell wrapper is none of these and counts as other.

## How to get to it (user POV)

- Run `vps-state` and read the `procs` and `heavy` lines.
- `vps-state --json` names the process ids, their CPU share and their RSS.

## Driving it with run

- Action: `run`. The JSON is saved as `json.out`, the block as `human.out`.
- Check: the counts are read from the saved JSON and the human lines must exist. The `human` check also proves the first line is the same verdict line `--brief` printed.
- The unit test on the real capture asserts a live host shows at least one chat and at least five workers, so a classifier that stops recognising them fails.

## Gotchas

- Every `bash -c ...` row is a wrapper, not the worker it launches. Counting wrappers as workers drags the median RSS down and overstates the room line by an order of magnitude.
- On this host a `claude --permission-mode ... --print ...` worker sits under a `python3 -u -c exec(...)` parent. Counting the parent too would double every worker.
- Process arguments are cut to 100 characters. A long brief is not evidence of a broken read.
