# Board login

A chat writes on the board under its own agent login, never under Valentin's user, the shared fallback "Valentins Claude Code CLI", or another chat's login.

## Sub-features

- `login.write`: the chat's note on SOFT-2849 is authored by "VVM Test Agent".
- `login.never-valentin`: no write since the run started has another author.

## How to get to it (user POV)

- The chat leaves a note or comment on its ticket after its work.

## Driving it with run

Preconditions: the token file `vvm-test-agent-agent-token` exists; `run` sets `SHIP_SESSION_NAME="VVM Test Agent"`.

The lease and the Stop hook read `skills/hypertask-work/session_login.py`. A chat with no `MULTIPROMPT_TAB` (a headless test run) resolves its login from `SHIP_SESSION_NAME` and that name's token file on disk. `run` exits 3 when the token file is missing.

`run` also strips the caller's `MULTIPROMPT_*`, `HT_TOKEN` and `HYPERTASK_*` from the chat's environment. Leaked, they made the lease resolve the caller's tab and sync the card as the caller (20 Nov: "board write by Vstack Maintainer").

- Action: `run`. Result: `agent-log.json` and `comments.json` hold the ticket's writes.
- Check: every activity and comment with `createdAt` at or after `started_at` has `agentName` or `agent.displayName` "VVM Test Agent". A comment whose `agent` is null came from a human login and fails.

## Gotchas

- Another session writing on SOFT-2849 during the run fails this check. Nobody else should touch that ticket.
- The scratch `CLAUDE.md` names the login. The check proves the chat writes with it, not that it found it alone.