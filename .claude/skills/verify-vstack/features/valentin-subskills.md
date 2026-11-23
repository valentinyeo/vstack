# Valentin mode's sub-rules reach the chat

A fresh chat follows the sub-rules valentin mode sets: plain words before a ticket comment, `report-page` before a report, a ticket for each ask, the long-chat handover's first line, and `pr-queue --mine`. Each scenario is a whole chat with a small job that triggers one rule, graded from what the chat did (tool calls, files, board writes), never from what it said.

## Sub-features

- `plain-words`: a read of `unjargon/SKILL.md` (or `pospeak/SKILL.md`) comes before the first ticket comment write.
- `report`: a read of `report-page/SKILL.md` comes before the first HTML file write.
- `ticket`: a board ticket is created before the ask's file is written.
- `handover`: `~/.local/state/long-chat/<session>.md` starts with the handover's required first line, and `long-chat/SKILL.md` was read before it was written.
- `prs`: a `pr-queue` run carries `--mine` and a chat name.

## How to get to it (user POV)

- Load `/valentin-mode`, then ask for one of those jobs: a ticket comment, a report page, a small piece of work, a handover, or what is open for this chat.
- The rules apply without the user naming them, and each one arrives from the skill rather than from the prompt.

## Driving it with verify-vstack

Preconditions:

- `~/.local/share/vstack` holds the valentin-mode under test, installed with `./install`.
- `~/.local/bin/plan-pick --claude-helper` exits 0, or `run` stops with exit 3.
- One run at a time: the `--break` run mutates the installed tree, so it must not overlap a real run.
- Each grade reads the stream's ordered tool calls: a read, then the side effect it should have come before.

- **One scenario.** Run `.claude/skills/verify-vstack/tools/valentin-subskills/run --scenario plain-words`, which builds a scratch git repo in `/tmp/vvs-scratch.*` holding a notes file and a short project rules file and copies `valentin-mode`, `responsive-mode` and the scenario's own skill into it. It then starts `claude -p` as the test agent with `--model sonnet`, `--permission-mode bypassPermissions`, a debug log and `--output-format stream-json`, under `--max-turns 30` and a 20 minute timeout. The prompt starts with `/valentin-mode` and asks for the scenario's job, never naming a skill. One Sonnet chat per run, no worker.
- **Every scenario.** The names are `plain-words`, `report`, `ticket`, `handover` and `prs`, one run each.
- **Break run.** Run `.claude/skills/verify-vstack/tools/valentin-subskills/run --scenario plain-words --break plain-words`. It deletes the rule's line from `valentin-mode/SKILL.md` and renames that scenario's skill folder to `<name>.off`, in the installed tree as well as the scratch copy, because the chat's `/valentin-mode` loads the installed copy. An EXIT trap puts both back, so the same run must FAIL.
- **Evidence.** Each run keeps its stream, debug log, prompt, scenario name and verdict under `~/.local/state/verify-valentin-subskills/`. Say which scenarios ran live on a PR.
- **Regrade a saved run.** Run `.claude/skills/verify-vstack/tools/valentin-subskills/grade.py ~/.local/state/verify-valentin-subskills/<run-id>`.

## Gotchas

- The chat reads skills through its own tool names, so match a read by path suffix, not by a fixed tool.
- Read the installed state path for the handover, not a copy inside the scratch repo.
- `pr-queue` may exit non-zero on an empty queue; grade the arguments, not the exit code.
- A report written as markdown instead of HTML still counts as the side effect: grade the first file write, not the extension.
- The scratch repo's fake board resolves writes to the test login, so a ticket on another board does not count.
- A FAIL is a finding about the chat, not a broken check. A real run that fails means valentin mode did not get that rule across.
