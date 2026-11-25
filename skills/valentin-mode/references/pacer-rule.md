# The pacer rule

An owner chat, the one Valentin talks to, only writes briefs and starts code workers. It never
edits code itself.

- Put the work in `brief.txt`, then run `~/.local/bin/plan-pick --run` from the worktree.
- A worker writes the code and opens the pull request; the owner chat reads one result line.
- Reviews go through `plan-pick --run` too.
- Tests, builds, linters, installs, merges and long loops go to a worker as well.
- Reading files, tickets and board state stays in the owner chat.

On this harness the rule is also checked by `hooks/pacer-guard.py` before a tool runs, so a code
edit is refused with the reason and the fix. Workers started by `plan-pick --run` are never
refused: plan-pick unsets the chat marker they would inherit.
