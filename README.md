# vstack

Writing skills for Claude Code and other AI agents. Each one is a single `SKILL.md`.

| Skill | What it does |
|---|---|
| [report-page](skills/report-page/SKILL.md) | Turns research or a plan into one clean HTML page you can scan in a minute: bottom line up front, Minto pyramid, reading time. Runs web-writing, unslop and zinsser-english-style, then builds from a bundled template. |
| [unjargon](skills/unjargon/SKILL.md) | Turns technical and AI-sounding writing into plain English a non-coder can act on, without hiding risk or detail. |
| [web-writing](skills/web-writing/SKILL.md) | Makes web text scannable: conclusion first, half the words, no hype. Based on Jakob Nielsen's NN/g study "How Users Read on the Web". |
| [schneider-deutsch-stil](skills/schneider-deutsch-stil/SKILL.md) | Writes and edits German in Wolf Schneider's style: short sentences, strong verbs, no Nominalstil. |
| [deeper](skills/deeper/SKILL.md) | Turns a task into a deeper version, not a bigger one: what a top professional would add, the rawest sources, the exact methods and tools, and outside proof, then rewrites the prompt. Prompt by [Felix Rieseberg](https://x.com/felixrieseberg). |
| [zinsser-english-style](skills/zinsser-english-style/SKILL.md) | The English counterpart: writes and edits English in the plain style of William Zinsser ("On Writing Well") and George Orwell's six rules. |
| [ptacek-copyedit](skills/ptacek-copyedit/SKILL.md) | Copyedits a draft you wrote yourself without touching your voice: flags problems pass by pass, never suggests words, never praises. Method by Thomas and Erin Ptacek, ["How To Write With An LLM"](https://sockpuppet.org/blog/2026/09/17/how-to-write-with-an-llm/). |

## Install

Claude Code:

```bash
git clone https://github.com/valentinyeo/vstack.git
cp -r vstack/skills/* ~/.claude/skills/
```

Then call a skill by name, for example `/web-writing`.

Any other model: paste the body of a `SKILL.md` (below the frontmatter) as the system prompt, followed by your text.

By Valentin Yeo, https://valentinyeo.com
