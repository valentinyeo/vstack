# Subscription pacer

Code workers start through `~/.local/bin/plan-pick --run` with the brief in brief.txt, never as a Claude subagent.

## Sub-features

- `pacer.launch`: a `launches.jsonl` line carries the chat's session id.
- `pacer.no-claude-worker`: no `Agent` or `Task` tool call other than read-only `Explore`.
- `pacer.no-lane`: a line with `lane: null` still passes, with the reason "no lane left".
- `task.output`: the worker wrote `hello.txt` with "hello from the worker".

## How to get to it (user POV)

- Ask the chat for any code change.

## Driving it with run

Preconditions: token-ladder PR 41 or later installed, so `plan-pick --run` writes the launch log.

- Action: `run`. Result: `launches.jsonl` in the evidence folder holds this session's lines.
- Check: at least one line, and no Claude subagent worker in `stream.jsonl`.
- Check: `hello.txt` in the evidence folder has the expected line.

## Gotchas

- `launches.jsonl` only records `--run`. A chat that runs `plan-pick` alone to see the pick does not count.
- With every lane used up, the chat may write the file itself. The pacer check passes on the `lane: null` line, and the task check still needs the file.
