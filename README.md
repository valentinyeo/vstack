# vstack

Writing and design skills for Claude Code and other AI agents. Each one is a single `SKILL.md`.

| Skill | What it does |
|---|---|
| [report-page](skills/report-page/SKILL.md) | Turns research or a plan into one clean HTML page you can scan in a minute: bottom line up front, Minto pyramid, reading time. Runs web-writing, unslop and zinsser-english-style, then builds from a bundled template. |
| [unjargon](skills/unjargon/SKILL.md) | Turns technical and AI-sounding writing into plain English a non-coder can act on, without hiding risk or detail. |
| [web-writing](skills/web-writing/SKILL.md) | Makes web text scannable: conclusion first, half the words, no hype. Based on Jakob Nielsen's NN/g study "How Users Read on the Web". |
| [schneider-deutsch-stil](skills/schneider-deutsch-stil/SKILL.md) | Writes and edits German in Wolf Schneider's style: short sentences, strong verbs, no Nominalstil. |
| [deeper](skills/deeper/SKILL.md) | Turns a task into a deeper version, not a bigger one: what a top professional would add, the rawest sources, the exact methods and tools, and outside proof, then rewrites the prompt. Prompt by [Felix Rieseberg](https://x.com/felixrieseberg). |
| [zinsser-english-style](skills/zinsser-english-style/SKILL.md) | The English counterpart: writes and edits English in the plain style of William Zinsser ("On Writing Well") and George Orwell's six rules. |
| [ptacek-copyedit](skills/ptacek-copyedit/SKILL.md) | Copyedits a draft you wrote yourself without touching your voice: flags problems pass by pass, never suggests words, never praises. Method by Thomas and Erin Ptacek, ["How To Write With An LLM"](https://sockpuppet.org/blog/2026/09/17/how-to-write-with-an-llm/). |
| [deep-work](skills/deep-work/SKILL.md) | Hand a big task to an agent and walk away for 60 to 90 minutes: it first proves it can check its own work, asks every question in one go, runs alone on [pstack](https://github.com/cursor/plugins/tree/main/pstack)'s full autopilot with those checks as its pass/fail, and ends with a two minute report. Shaped after [Cal Newport](https://calnewport.com)'s book [Deep Work](https://calnewport.com/deep-work-rules-for-focused-success-in-a-distracted-world/). |
| [responsive-mode](skills/responsive-mode/SKILL.md) | Keeps the chat free while background agents do the work, and makes sure every job still ends done and checked. |
| [valentin-mode](skills/valentin-mode/SKILL.md) | Valentin's working style on top of pstack: how to talk to him, which model does which job, and how a result gets checked. The same rules in every harness. |
| [hypertask](skills/hypertask/SKILL.md) | Everything an agent needs on Hypertask: its own agent login, the CLI, tickets and comments, columns and leases, views and labels, board sync with the Stop hook, the checkup, and what to file a ticket for. One skill; seven reference files. |
| [design-lead-setup](skills/design-lead-setup/SKILL.md) | Sets an agent up as design lead for an existing app: real screenshots and code tokens in Figma, a rule-cited audit (top 5, deletions first), one problem ticket per case, and fixes shown as edits on the real screen. Nothing ships until the owner says yes. Built on Hypertask; sources include Emil Kowalski, Vercel's guidelines, pstack, Peng Zheng's "first 5%" and the Figma MCP skills. |
| [join-slack](skills/join-slack/SKILL.md) | Puts a lead session in Slack #fleet: reuses the lead's bot, points @mentions at its tmux session, then checks the doctor and a dry-run reply. |
| [ratstack-transition](skills/ratstack-transition/SKILL.md) | Plans a forced rewrite of an existing app onto [Rat Stack](https://github.com/joelhooks/rat-stack): pins one commit, diffs packages and layout, maps every behaviour onto Rat Stack nouns, and files one Hypertask ticket per slice. Hidden until typed; no app code. |

Nine writing and design skills (design-lead-setup, join-slack, pospeak, ptacek-copyedit, report-page, schneider-deutsch-stil, unjargon, web-writing, zinsser-english-style), deep-work, deeper, ratstack-transition and valentin-mode are hidden from the model's skill list; open them through the valentin-mode index or their slash command. responsive-mode stays visible because valentin-mode loads it with the Skill tool. hypertask, board-drain, pr-housekeeping and vps-state stay visible so a session can reach tickets, drain its board, tidy its PRs and check server load without reading the index first.

## Install

One command links every skill into Claude Code, Codex, Cursor and pi:

```bash
git clone https://github.com/valentinyeo/vstack.git
cd vstack
./install
```

Safe to run again. Each harness entry is a symlink to this checkout, so there is one copy of each skill. A stale symlink is replaced. A real folder with the same skill name is moved to `~/.local/state/skill-dupes-<epoch>/` and kept.

Then call a skill by name, for example `/web-writing` or `/valentin-mode`.

Any other model: paste the body of a `SKILL.md` (below the frontmatter) as the system prompt, followed by your text.

By Valentin Yeo, https://valentinyeo.com

## Shared checks

pstack holds workflow rules. vstack holds shared checks.
Product repos hold their own facts.

[The rules table](CLAUDE.md) names each hook.
[The book checklist](book/CHECKLIST.md) records pstack sources.
`advisor-checks` installs pstack from `cursor/plugins`.
It runs every `hooks/*.py --self-test`.
Migration tests and installer tests run there too.
A verifier from another model family than the author checks PRs on GitHub-hosted runners.
`scripts/pick-verifier-model` reads the PR body's `Author model: <family>/<model>` lines and picks DeepSeek Flash, else GLM, else Kimi.
A PR without that line fails its verifier.
Its command trace becomes a workflow artifact.
Its verdict appears on the PR.

Project boundaries use local environment values:

- `VSTACK_READ_ONLY_PROJECT`, default `read-only-project`.
- `VSTACK_BLOCKED_PROJECT`, default `restricted-project`.

Keep private project names outside this repo.
This change installs no runtime hooks.
Configure hook paths from your vstack checkout.
