# Agent skills template

A way to run one coding agent on many kinds of work without giving it one giant prompt full of rules.

## The problem this solves

A single "do everything" prompt grows every time someone finds a new edge case. It gets long, rules contradict each other, and nobody remembers why a line is there. The agent still makes the same mistake twice because the correction only ever lived in a chat reply.

## The idea

One general agent, no fixed roles. It picks up a skill file for the job in front of it, instead of carrying every rule for every job at once.

- `INDEX.md` lists every skill: name, one line saying when it applies, path to its folder. The agent reads this first.
- Each skill is one job, in its own folder, with a `SKILL.md`: numbered steps, and a checklist to run before handing the work off.
- The agent reads only the one or two skills that match the task. This is progressive disclosure: load the index, then load just what's needed, not the whole library.
- `RULE-MAP.md` is where every standing rule lives, once, with where it came from and which skill owns it (or a note that it was dropped, and why).
- Corrections go into files, not chat. Fix a mistake by editing the skill. If a step gets done the same way twice, turn it into a script. If a decision has no written rule, ask the human once and write the answer into the skill so the question never comes up again.

## Adopt this in 5 steps

1. **Copy the folder.** Copy `templates/agent-skills/` into your repo (for example to `.agent-skills/` or wherever your repo keeps agent config) and rename `example-skill/` to your first real skill.
2. **Write one skill for one job.** Fill in `example-skill/SKILL.md`: a name, a one-line trigger sentence, numbered steps that are each one clear action, and a "Check before hand-off" list. Keep long reference material out of the steps; put it in a separate `reference.md` next to the skill if you need it.
3. **List it in INDEX.md.** One row: name, trigger, path. This is the only file the agent reads before picking a skill, so keep each trigger short and specific enough that the agent can tell which skill matches without reading further.
4. **Move deterministic steps into scripts.** Anything the agent does the same way every time (opening a PR, running a fixed check, posting a status update) belongs in `example-skill/scripts/`, not typed out in prose. Every script supports `--dry-run` and passes `bash -n`.
5. **Write your standing rules into RULE-MAP.md.** Take whatever rules currently live in a big prompt or a wiki page, and place each one exactly once: which skill now carries it, or `DROP` with a reason it no longer applies. Read `CORRECTIONS.md` for how new rules get added later.

## Why progressive disclosure matters

Loading every skill for every task defeats the purpose: the agent is back to reading one giant prompt, just split across files. The index step is what keeps the agent's working context small and specific to the task at hand.

## When there's no matching skill

The agent should say so and stop, rather than guess. See `AGENT-PROMPT.md` for the exact mission text that makes this the default behavior.
