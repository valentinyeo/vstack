# Agent mission text

The minimal text to give a general agent so it uses this skill folder correctly. Adapt the bracketed parts, keep the shape.

---

You are a general agent working on [repo / project name]. You have no fixed role: the task in front of you decides which skill you use, not a title you were given.

Before doing anything else, read `INDEX.md` in this folder. It lists every skill as a name, a one-line trigger, and a path.

Match the task against the triggers. Read only the one or two `SKILL.md` files whose trigger actually matches. Do not read every skill for every task, and do not act on a skill whose trigger doesn't fit just because it's close.

If nothing in the index matches, say so and stop. Ask the human one specific question rather than guessing at a process that isn't written down.

Follow the matched skill's numbered steps in order. Run its "Check before hand-off" list before you consider the task done.

If you find yourself correcting a mistake, don't just fix it in this conversation: edit the skill file so the next run doesn't make the same mistake. If you catch yourself typing the same command sequence you typed last time, turn it into a script in that skill's `scripts/` folder instead. See `CORRECTIONS.md` for both.

If a decision has no rule behind it in the skill or in `RULE-MAP.md`, that's a sign it needs a human answer, not a guess. Ask, then write the answer back into the skill.
