# Rule map

Every standing rule this agent follows appears exactly once below, with where it came from and which skill now owns it. If a rule no longer applies, mark it `DROP` and say why, instead of deleting it silently: the next person should be able to see that it was considered, not just missing.

This file exists so rules never live only in a chat reply or a person's memory. When a correction happens, it gets written here and into the owning skill in the same edit.

| # | Rule | Source | Skill |
|---|---|---|---|
| 1 | Example: replace with your first real rule, one row per rule | Where this rule came from (a doc, a person, an incident) | Which skill file now carries it, or `DROP` with a one-line reason |

## How to use this file

1. When you find a rule currently living only in a prompt, a wiki page, or someone's head, add it here as a new row before it goes anywhere else.
2. Decide which skill owns it. A rule with no clear owner probably means you need a new skill, not a home for an orphan rule.
3. Copy the rule's actual text into that skill's `SKILL.md`, in the step where it applies. This file is the map, not the rule text itself: don't let the two drift apart.
4. If a rule stops applying (the system it described was retired, the policy changed), don't delete the row. Change its skill column to `DROP` and add the reason. A gap with no explanation looks like an oversight.
