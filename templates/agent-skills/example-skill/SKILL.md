---
name: example-skill
description: One sentence describing exactly when this skill applies. This line is the trigger the agent matches against, so make it specific.
---

# example-skill

One sentence saying what job this skill covers and why it exists as its own skill rather than a step inside another one.

## Steps

1. **First bounded action.** Say exactly what to do and what "done" looks like for this step. Name the specific command, file, or check, not a general instruction.
2. **Second bounded action.** Keep each step small enough that it either succeeds or fails clearly. If a step needs a long explanation, move that explanation to `reference.md` and link it here instead of inlining it.
3. **Deterministic step, done through a script.** Anything done the same way every time belongs in `scripts/`, not typed out here. Call it as `scripts/example.sh <args>`, and mention the `--dry-run` flag if the step is risky enough to want a preview first.
4. **Last step: report or hand off.** Say what the agent tells the human or the next system, and in what format.

## Check before hand-off

- [ ] Condition that must be true before this skill's job counts as done
- [ ] Any state changed by this skill has been verified by reading it back, not assumed
- [ ] Nothing was skipped silently; anything skipped is named in the hand-off

## Reference

If this skill needs background material longer than a step should carry (a full API reference, a long list of edge cases, a copied policy document), put it in `reference.md` in this folder and link to it from the step that needs it. Delete this section if you don't need it.
