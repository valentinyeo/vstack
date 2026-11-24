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

A PR names a ticket when the key or its board URL appears in the title, in the branch name, on a `Ticket:` body line, or on a body line that starts with a GitHub closing keyword (`Closes`, `Fixes`, `Resolves`, and their forms) followed by that key or URL; a mention anywhere else does not. A branch names its ticket when the branch starts with the key, whatever the PR's date; an open PR also counts when the key sits anywhere in its branch name.

## Setup, per project

Board sync is per project and per chat. Nothing user-wide runs it.

1. Add the board line to the project's notes (`AGENTS.md` or `CLAUDE.md`), as `views.md` says.
2. Start workers through `skills/hypertask-work/lease`. Its start and end events sync the ticket whose work moved.
3. Keep your own `/board-drain` watcher armed. It runs `skills/board-drain/sync` before its snapshot, every fifteen minutes, and records the result for drain-check. A failed sync wakes this chat.
4. Run the checkup (`checkup.md`). It checks this chat's loop and last sync, not a turn-end hook.

## Records

A sync writes one status record per board and label: `~/.local/state/reconcile-auto/<board>-<label>.json`, with its log beside it. Fields: `at`, `session_name`, `board`, `label`, `ticket`, `exit`, `moved`, `unknown`, `summary_line`, `log`.

The lease writes one card record per phase: `<board>-<ticket>-<phase>.json`, with `phase` `start` or `end` from `RECONCILE_CARD_PHASE`. It has the same fields, plus `worker_exit` from `RECONCILE_WORKER_EXIT` and `worker_note`, which reads `nothing ran, waiting for a lane` when that exit is 75.

An end sync with `worker_exit` 75 puts the card back with `nothing ran, waiting for a lane`, even inside the two-hour grace. The start moved it to Doing because a lease existed; the 75 says no worker ran, so the card waits instead of reading as started.

A card sync that cannot read its ticket writes no record; its one line goes to `failures.jsonl`.

The watcher records its last sync in this chat's board-drain state. `drain-check` rejects a failed sync or one older than 45 minutes. A lease record with `exit` 0 and `unknown` 0 is healthy.

## Assignment on the lease start

The lease's start sync runs `agent take` for the ticket as the chat's own login when the ticket has no agent assignee. It leaves an existing agent assignee alone, and it never assigns a person. A ticket with only a person assignee gets the agent added next to the person. This is what makes ownership visible on a board nobody assigned.

## GitHub budget

A run spends GitHub calls, and the account shares one hourly budget. The first response that reports a spent budget stops the run at once: 403 and 429 errors that name a rate limit or a secondary rate limit, and GraphQL's `RATE_LIMITED`. The run prints one line with the reset time from `gh api rate_limit`, applies no move, and exits 0. Only error text counts, so a PR or comment that talks about a rate limit is not one. Every run prints its call count to stderr: `reconcile: github calls=N (graphql=a, rest=b)`. A product board takes a PR's state from the search it already paid for. Every other board reads fifty PRs per call, the verifier policy at each base commit in one call per fifty commits, and the jobs of one verifier run once ever, because a finished run does not change.

A chat over its own gh budget skips the tick instead of dying. Reconcile prints exactly one line, `sync skipped: gh budget (wait until HH:MM UTC)`, moves nothing and rewrites no saved fact, and exits 0 whatever step the refusal hit. `sync` prints that same one line, records the tick as skipped, and does not run its apply step. The watcher prints the line and keeps watching, so the next tick inside the budget carries on. `drain-check` never calls a skip a failed sync; it judges the view by the last sync that really read the board, so skips that last over 45 minutes still read as `sync stale`.

When saved facts exist, reconcile keeps one REST probe and reuses them from `~/.cache/vstack/reconcile/board-facts-<board>.json`. That probe covers every repository the board ships from, plus any repository it has already seen, as `repo:` terms in the one query: a board with two repos still costs one call. A ticket the probe or the board flagged is read at once, and so is a new ticket. A ticket whose facts have reached three hours is read whatever else happens, and once the oldest facts pass an hour the oldest quarter of the rest is read too: no run is fully cold while facts exist, and no saved fact ends a run older than four hours. A probe that fills its one page says so on stderr, and the quarter reads on. A refused `gh` budget (exit 75) skips the tick: the saved facts stay as they were, nothing new is planned, and no update is written.

Finding a ticket's PRs costs one aliased search per ticket, plus one sweep of the board's open PRs (a board-sized run only), plus one branch lookup per ticket those searches left empty. Nothing reads the whole merge history: a fleet with thousands of daily merges used to cost a page per hundred of them on every run.

A merged PR that a later merged PR reverts is not a ship. Reconcile reads the three forms GitHub writes: a title `Revert "<title>"`, a body line `Reverts #<n>` or `Reverts <owner>/<repo>#<n>`, and `This reverts commit <sha>`. The reverted merge and the revert itself leave the ticket's facts, so a card whose only PR was reverted plans the same column on the next run instead of flapping between review and Todo.

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
- The script verifies the connected agent before a write. Missing, personal or other agent tokens fail. Never supply Valentin's personal token. vcc (`Valentins Claude Code`) and HT Product Lead move any card. Any other login needs a board 15 membership and `--label` naming its own agent, and then moves only cards carrying that label: another lead's card and an unlabelled card stay where they are. `--ticket` takes no `--label`, so a lead cannot apply with it.

## Server timer

The supplied timer runs every fifteen minutes and enables capped board moves after preview. Its environment comes from `~/.config/fleet/reconcile.env`, mode 0600, which supplies `HT_TOKEN`; `SHIP_SESSION_NAME` defaults to Poteto in the service. Runs serialize through the board lock; an overlapping run prints `SKIP` and succeeds.

The board-15 service template installs no timer and reads `~/.config/fleet/reconcile-board15.env`. A whole-board apply uses the vcc or HT Product Lead token; the vcc identity is `Valentins Claude Code`. A board 15 lead applies on its own label only, for example `--board 15 --label 'Mobile Designer' --apply` as the Mobile Designer agent.

After release approval:

```bash
~/.local/share/house-rules/bin/install-fleet-reconcile.sh
```

## Self-test

```bash
python3 skills/hypertask-work/reconcile --self-test
```
