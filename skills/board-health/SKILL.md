---
name: board-health
description: >-
  Health-check this chat's own Hypertask board or view and fix what it finds: stale agents, wrong columns, missing or duplicate tickets, misfiled tickets, no sync routine, no own view. Use for /board-health, "check your board", "is your board in sync", or when Valentin asks why a board looks wrong.
---

# Board health

Prior art: checked pstack, hypertask-work and board-identity. hypertask-work owns the board rules but nothing makes a chat audit its own board; it has no room left under its word budget, so the audit lives here.

Check your own board or view against the `hypertask-work` rules, then fix your own gaps.
That skill owns every rule; this one only makes you look.
Act as your own agent login, from the board-identity skill. Never write as Valentin.

## Nine checks

1. **Stale agents.** List assignees on your view's open tickets. An agent that is revoked, renamed or has no live chat is stale.
2. **Clean them up.** Unassign a stale agent from your tickets and reassign the live owner. Never revoke, rename or delete an agent. A stale agent on another chat's tickets: tell that chat.
3. **You are on it.** Your login is a board member and assigned to every ticket you work.
4. **True columns.** Doing means a worker runs now. An open PR means Checks. Run the reconcile preview, then apply. A ticket that waits on Valentin stays where it is; never move one into Valentin Review.
5. **Sync routine.** Your project's agent notes carry `Hypertask board: <id>, label: <label>`, and your loop runs the reconcile. Add whichever is missing.
6. **Ticket per task.** Each open branch, PR, worktree and running worker has a ticket in your view. File one for any that lacks it.
7. **Outdated or duplicate.** Close each with a one-line reason and a link to the ticket that replaces it. Move it to Done; never delete.
8. **Misfiled.** A ticket another chat owns moves to that chat's label or board. Tell that chat. A ticket of yours on another view gets your label.
9. **Own view.** You own a view named after your repo, or after your Multibot name. Create it with your label when missing, then work from it.

## Report

One line per check: ✅ fine, 🔧 fixed (what), or ❓ needs Valentin (the question, with your pick).
Then the view's link. Put the same report on your view's newest open ticket.
