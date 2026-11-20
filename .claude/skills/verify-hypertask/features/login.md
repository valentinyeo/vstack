# Own login

A chat writes on the board under its own agent login, never Valentin's and never the shared fallback.

## Sub-features

- `login.write`: the chat's writes on SOFT-2849 are authored by "VVM Test Agent".
- `login.never-valentin`: no write since the run started has another author.

## Driving it with run

Preconditions: the token file `vvm-test-agent-agent-token` exists; `run` sets `SHIP_SESSION_NAME="VVM Test Agent"`.

- Action: `run`. Result: `agent-log.json` and `comments.json`.
- Check: every activity and comment with `createdAt` at or after `started_at` has `agentName` or `agent.displayName` "VVM Test Agent".

## Gotchas

- Another session writing on SOFT-2849 during the run fails this check.
- A comment whose `agent` is null came from a human login and fails.
