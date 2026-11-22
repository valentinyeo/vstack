# The checkup

Health-check your own board and view, then fix your own gaps. Run it on a new project and daily. Act as your own agent login (see `identity.md`), never as Valentin.

## Checks

1. **Stale agents.** List assignees on your view's open tickets. An agent that is revoked, renamed or has no live chat is stale.
2. **Clean them up.** Unassign a stale agent from your tickets and reassign the live owner. Never revoke, rename or delete an agent. A stale agent on another chat's tickets: tell that chat.
3. **You are on it.** Your login is a board member and assigned to every ticket you work. List open tickets in your label with no agent assignee and take yours: `hypertask agent take <ticket> --project <board>`. Never assign a person, and never replace an existing agent.
4. **True columns.** Each card sits where the `board.md` rules put it. Run the reconcile preview, then apply. A ticket that waits on Valentin stays. Never move one into Valentin Review.
5. **Sync routine.** Follow `sync.md`: worker start and end sync through the lease, and your own board-drain watcher syncs the view. Run drain-check with this chat's state name; fix a missing watcher, failed sync or stale sync. Tool failures in `~/.local/state/reconcile-auto/failures.jsonl` belong to Hypertask Reconciler; report them, do not move cards to hide them.
6. **Ticket per task.** Each open branch, PR, worktree and running worker has a ticket in your view. File one for any that lacks it.
7. **Outdated or duplicate.** Close each with a one-line reason and a link to the ticket that replaces it. Move it to Done by hand; never delete. A ticket waiting on Valentin is his to close: ask him.
8. **Misfiled.** A ticket another chat owns moves to that chat's label or board. Tell that chat. A ticket of yours on another view gets your label.
9. **Own view.** You own a view named after your Multibot chat, or after your repo when the repo has one chat. Create it with your label when missing (`views.md`), then work from it.

## Fix the tool, not just the card

Every card you move by hand is a gap in the reconcile. For each one:

1. Write down why the reconcile missed it: board, ticket, column, and the `PLAN`/`KEEP` line it printed.
2. Send that case to Hypertask Reconciler with the card as the test case, through a plan-pick worker. That chat owns the reconcile code and its tests.
3. Prove it: run the reconcile, then preview again. The preview shows no moves.

## Report

One line per check: ✅ fine, 🔧 fixed (what), or ❓ needs Valentin (the question, with your pick).

Then the view's full https:// URL. Put the same report on your view's newest open ticket, in the agent lane.
