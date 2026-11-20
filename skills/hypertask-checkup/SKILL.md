---
name: hypertask-checkup
description: >-
  Health-check this chat's own Hypertask board or view and fix what it finds: stale agents, wrong columns, missing or duplicate tickets, misfiled tickets, no sync routine, no own view. Use for /hypertask-checkup, "check your board", "is your board in sync", or when Valentin asks why a board looks wrong.
---

# Hypertask checkup

Prior art: pstack poteto-mode — no board audit; vstack hypertask-work owns the board rules but is near its word budget, so the audit lives here.

Check your own board or view against the `hypertask-work` rules, then fix your own gaps.
That skill owns every rule; this one only makes you look.
Act as your own agent login, from the board-identity skill. Never write as Valentin.

## Nine checks

1. **Stale agents.** List assignees on your view's open tickets. An agent that is revoked, renamed or has no live chat is stale.
2. **Clean them up.** Unassign a stale agent from your tickets and reassign the live owner. Never revoke, rename or delete an agent. A stale agent on another chat's tickets: tell that chat.
3. **You are on it.** Your login is a board member and assigned to every ticket you work.
4. **True columns.** Each card sits where the `hypertask-work` column rules put it; this check adds none of its own. Run the reconcile preview, then apply. A ticket that waits on Valentin stays where it is; never move one into Valentin Review.
5. **Sync routine.** The status record under ~/.local/state/reconcile-auto for your board and label is under 30 minutes old, exit 0, unknown 0. If not, fix the cause it names (board line, token named like the Multibot chat, bus, lock). Never fix it by moving cards by hand.
6. **Ticket per task.** Each open branch, PR, worktree and running worker has a ticket in your view. File one for any that lacks it.
7. **Outdated or duplicate.** Close each with a one-line reason and a link to the ticket that replaces it. Move it to Done by hand; never delete. A ticket waiting on Valentin is his to close: ask him instead.
8. **Misfiled.** A ticket another chat owns moves to that chat's label or board. Tell that chat. A ticket of yours on another view gets your label.
9. **Own view.** You own a view named after your repo, or after your Multibot name. Create it with your label when missing, then work from it.

## Fix the tool, not just the card

Every card you move by hand is a gap in the reconcile.
For each one, write down why the reconcile missed it.
Add that case to the reconcile with a test built from the real card, through a plan-pick worker.
Proof: run the reconcile, then preview again; the preview shows no moves.

## Report

One line per check: ✅ fine, 🔧 fixed (what), or ❓ needs Valentin (the question, with your pick).
Then the view's link. Put the same report on your view's newest open ticket.
