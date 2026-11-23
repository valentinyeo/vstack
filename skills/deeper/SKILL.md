---
name: deeper
description: "make this deeper;how would a pro do this. /deeper [task]: deepen, not widen. Name unasked expert work, rawest sources, exact methods/tools, external proof; rewrite prompt. Felix Rieseberg. Use for /deeper, \"make this deeper\" or \"how would a pro do this\"."
model: opus
effort: medium
disable-model-invocation: true
---

# /deeper

Prompt by Felix Rieseberg, https://x.com/felixrieseberg. Packaged as a skill with a few rules added.

The task is the text after `/deeper`. If there is none, use the most recent task in this conversation.

I want this task deepened, not widened. The four questions and the prompt rewrite are pstack's `sharpen` skill: read it and follow it. This skill adds what sharpen leaves out, below.

Prior art: pstack `sharpen` and `poteto-mode/playbooks/authoring-a-skill.md` were checked; sharpen already owns deeper-not-bigger and the rewrite, so this skill links to it and keeps only the expert-context and proof rules.

## Added on top of sharpen

- Technical, app-building or coding task only: say what Lauren Tan (@poteto, https://x.com/poteto, author of pstack) would do here and how she would approach it. Skip this point for other fields.
- Before writing, look at the real context for the task (files, tickets, systems) so the answer fits this case, not a generic one.

## Rules

- Answer in four short parts (five for technical tasks), then the rewritten prompt in one code block that can be pasted.
- Do not start the deeper task. End by asking whether to run the rewritten prompt.
