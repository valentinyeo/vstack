# Corrections workflow

How a mistake gets fixed so it does not happen again, and how a repeated manual step turns into something the agent can run instead of retype.

## The rule

A mistake is fixed by editing the skill file, never by a chat reply alone.

A chat reply fixes the moment. Editing the skill fixes the next hundred times the same situation comes up. If a correction only exists in a conversation, the next agent (or the same agent tomorrow) has no way to see it.

## When the agent gets something wrong

1. Find the skill step that should have caught this and didn't.
2. Edit that step so the same mistake is no longer possible, or add a new numbered step if the gap is a missing step rather than a wrong one.
3. If the mistake came from a rule that wasn't written down anywhere, add it to `RULE-MAP.md` first, then copy it into the skill.
4. Say, in the hand-off or the commit for the fix, which file changed. A correction that isn't traceable to a file edit didn't happen as far as the next run is concerned.

## When a step gets done the same way more than once

1. If you've written out the same sequence of commands for the same step twice, it's a script now, not a step description.
2. Move it into that skill's `scripts/` folder. Give it `--dry-run` and make sure `bash -n` passes on it.
3. Replace the prose in `SKILL.md` with a call to the script.

## When there's no written rule for a decision

1. The agent should not guess. It asks the human one specific question, not a menu of options.
2. Once the human answers, the answer goes into the skill file as a new step or a clarified line, in the same place the question came from.
3. The next time the same situation comes up, the skill already has the answer and the human is not asked again.

## What this workflow prevents

- A rule that only ever lived in someone's memory, so it silently stops applying the day that person is unavailable.
- The same clarifying question being asked more than once.
- Drift between what the agent actually does and what the skill file says it does.
