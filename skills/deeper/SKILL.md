---
name: deeper
description: Turn a task into a deeper version, not a bigger one. Says what a top professional would do that was not asked for, the rawest source material, the exact methods and tools, and what outside proof would show the result is right, then rewrites the prompt to ask for exactly that. Prompt by Felix Rieseberg. Use for /deeper, optionally followed by the task, or "make this deeper", "how would a pro do this".
---

# /deeper

Prompt by Felix Rieseberg, https://x.com/felixrieseberg. Packaged as a skill with a few rules added.

The task is the text after `/deeper`. If there is none, use the most recent task in this conversation.

I want a deeper version of this task, not a bigger one. Before rewriting it:

1. Say what a top professional in this field would do here that I'm not asking for.
2. Name the rawest material they would start from instead of what has already been digested for me.
3. Name the specific methods and tools they would use.
4. Say what, other than you or me, would show the result is right.

Then rewrite my prompt to ask for exactly that.

## Rules

- Deeper means sharper method, rawer sources and outside proof. Do not add scope, features or extra deliverables.
- Name the field first, in a few words, so the professional is concrete.
- Raw material is a primary source: logs, files, git history, provider dashboards, the live system, real users, original documents. Not summaries, docs about the thing, or earlier agent output.
- Methods and tools are named and specific: the actual tool, command, test or technique.
- Proof must come from outside this conversation: a scanner, a test, a provider's own record, a live measurement, a third party. Never "I checked" or "you confirm".
- Before writing, look at the real context for the task (files, tickets, systems) so the answer fits this case, not a generic one.
- Answer in four short parts, then the rewritten prompt in one code block that can be pasted.
- Do not start the deeper task. End by asking whether to run the rewritten prompt.
