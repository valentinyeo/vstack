# Board sync

`skills/hypertask-work/reconcile` reads a board and GitHub and moves each card to its true column. The column rules live in `board.md`. Default runs print plans and move nothing.

The house-rules `fleet/reconcile` path is a shim that execs this copy.

## Run it

Run it yourself, on your own board, as your own login, after you move work:

```bash
skills/hypertask-work/reconcile --board 13556 --label "<your label>"
```

Read every printed reason. Then apply with the cap:

```bash
skills/hypertask-work/reconcile --board 13556 --label "<your label>" --apply --limit 5
```

Set `HT_TOKEN` and `SHIP_SESSION_NAME` first. A plan over the cap applies the first moves and prints `DEFERRED` for the rest.

Flags:

- `--board <id>`: the board to sync. A board read at runtime keeps its own columns, prefix and protected columns.
- `--label <name>`: sync only tickets carrying that label (trimmed, case-insensitive). Always use it, so a session never syncs the whole board.
- `--section <name>`: limit a dry run to one column.
- `--ticket <KEY>`: sync exactly one ticket on the board that ticket belongs to. It takes no `--board`, `--label` or `--section`. The lease uses it as `--ticket KEY --apply --limit 1`.
- `--apply`: move. It previews first, then permits five moves.
- `--limit <n>`: the per-run cap. Board 15 keeps a hard cap of five.
- `--self-test`: run the focused test suite.
- `RECONCILE_AUTO_DRY=1`: drop `--apply`, prove a sync with no board writes.

Moves backed by a live worker or an open or merged PR go first. Moves back to Todo go last. Each tier is ordered by ticket number. Any `UNKNOWN` refuses every move. Each move writes an agent-log entry and leaves owners and assignees unchanged.

`--ticket` shares the board lock and holds its own per-ticket lock. It reads the ticket before anything else, costs a handful of GitHub calls, prints `UNKNOWN` and refuses every move when the ticket cannot be read, and refuses a key from another board's prefix.

## Setup, per project

Board sync is per project and per chat. Nothing user-wide runs it.

1. Add the board line to the project's notes (`AGENTS.md` or `CLAUDE.md`), as `views.md` says.
2. Add the Stop hook to the project's own `.claude/settings.json`, yourself. Keep every hook already there and add this entry to the `Stop` list:

   ```json
   {
     "hooks": {
       "Stop": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "/usr/bin/python3 \"$HOME/.claude/hooks/reconcile-auto.py\""
             }
           ]
         }
       ]
     }
   }
   ```

   Never add it to `~/.claude/settings.json`: several chats share this machine and each owns its own setup. `install` links `hooks/reconcile-auto.py` into `~/.claude/hooks` so the path exists; it never edits a settings file.
3. Run the checkup (`checkup.md`). It verifies the entry is present and the status record is fresh.

## What the hook does

After each turn, at most every 10 minutes, it starts `reconcile --apply --limit 5` for the project's board and the chat's label, detached. A `MULTIPROMPT_TAB` names a Valentin-facing Multibot chat; a headless run passes.

It blocks the chat only for setup the chat is missing: the board line, or the token for its own login. It never blocks on a tool failure. A failed sync is one JSON line in `~/.local/state/reconcile-auto/failures.jsonl`, for the reconcile owner, Hypertask Reconciler. It never stops a chat.

## Records

A sync writes one status record per board and label: `~/.local/state/reconcile-auto/<board>-<label>.json`, with its log beside it. Fields: `at`, `session_name`, `board`, `label`, `ticket`, `exit`, `moved`, `unknown`, `summary_line`, `log`.

The lease writes one card record per phase: `<board>-<ticket>-<phase>.json`, with `phase` `start` or `end` from `RECONCILE_CARD_PHASE`. It has the same fields.

A card sync that cannot read its ticket writes no record; its one line goes to `failures.jsonl`.

A record older than 30 minutes is stale and the next turn starts a run. `exit` 0 and `unknown` 0 is healthy.

## Assignment on the lease start

The lease's start sync runs `agent take` for the ticket as the chat's own login when the ticket has no agent assignee. It leaves an existing agent assignee alone, and it never assigns a person. A ticket with only a person assignee gets the agent added next to the person. This is what makes ownership visible on a board nobody assigned.

## GitHub budget

A run spends GitHub calls, and the account shares one hourly budget. The first response that reports a spent budget stops the run at once: 403 and 429 errors that name a rate limit or a secondary rate limit, and GraphQL's `RATE_LIMITED`. The run prints one line with the reset time from `gh api rate_limit`, applies no move, and exits 0. Only error text counts, so a PR or comment that talks about a rate limit is not one. Every run prints its call count to stderr: `reconcile: github calls=N (graphql=a, rest=b)`. A PR's state comes from the search the run already paid for, so no PR costs a call of its own.

## A miss

When the reconcile leaves a card in the wrong column, or moves one it should not:

1. Fix the card by hand if the board is wrong now (`board.md`), and say why in an agent-lane note.
2. Report the miss to Hypertask Reconciler in one message: board, ticket, the column you expected, the command you ran, and its `PLAN`/`KEEP` line. That chat owns the reconcile code, its tests and its deployments.
3. Keep working. Do not wait for the fix.

Never patch the card and say nothing: the next run undoes it or repeats it. The checkup's "fix the tool, not just the card" rule is in `checkup.md`.

## Board 15

`skills/hypertask-work/reconcile --board 15` previews Hypertask product moves. Dedicated rules:

- Ticket keys start with `HTPR-`. PRs come from every repo the board ships from: `hypertask-ai/hypertask` (release branch `production`) and `valentinyeo/vstack` (release branch `main`). One search covers them all.
- Live workers move tickets to In Progress. Open and merged PRs move them to AI Review. An open PR outranks a live worker.
- A merged PR counts only when its base is that repo's release branch. A stacked PR merged into a feature branch is not a ship.
- An open PR or a live worker moves a ticket even inside the two-hour grace. The grace only protects an idle ticket.
- An In Progress ticket with no live worker and no shipped PR moves to Backlog after two hours. Tickets in Backlog stay unless a shipped PR now names them.
- UX needed, UX Sign-off, Agent Blocked (Infra), Valentin Review, QA and every Flag column stay. No Flag and unknown columns also stay.
- Each run permits at most five moves, even with a higher `--limit`.
- Worker facts come from the installed Hypertask workers. An active service alone proves no ticket work: its local PID must exist and its queue must name that board's ticket. Claiming, launching and running count as active. Progress expires after 15 minutes. A live lease or a process that names the ticket also counts. Unreadable worker facts refuse all moves.
- A shell without `XDG_RUNTIME_DIR` or `DBUS_SESSION_BUS_ADDRESS` gets `/run/user/<uid>` defaults first. If worker facts still cannot be read, the run prints one `reconcile: worker facts unreadable: ...` line, moves nothing and exits non-zero.
- The script verifies the connected agent before a write. Missing, personal or other agent tokens fail. Never supply Valentin's personal token.

## Server timer

The supplied timer runs every fifteen minutes and enables capped board moves after preview. Its environment comes from `~/.config/fleet/reconcile.env`, mode 0600, which supplies `HT_TOKEN`; `SHIP_SESSION_NAME` defaults to Poteto in the service. Runs serialize through the board lock; an overlapping run prints `SKIP` and succeeds.

The board-15 service template installs no timer and reads `~/.config/fleet/reconcile-board15.env`. Use the vcc or HT Product Lead token. The vcc identity is `Valentins Claude Code`.

After release approval:

```bash
~/.local/share/house-rules/bin/install-fleet-reconcile.sh
```

## Self-test

```bash
python3 skills/hypertask-work/reconcile --self-test
```
