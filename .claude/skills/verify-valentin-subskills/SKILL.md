---
name: verify-valentin-subskills
description: >-
  Prove that a fresh Claude Code chat on this server follows valentin mode's sub-rules: plain words before a ticket
  comment, report-page for a report, each ask becomes a ticket, the long-chat handover first line, and
  pr-housekeeping with --mine. Starts one cheap Sonnet chat per scenario and grades the side effects, never the
  chat's claims. Use on a change to skills/valentin-mode or to one of those skills, beside verify-valentin-mode.
skill-word-budget: 800
skill-word-budget-reason: Five scenarios, each with its break mode, plus the shared evidence and cost rules.
---

# Verify valentin mode's sub-rules

Prior art: checked pstack `create-verification-skill`, `maintain-verification-skill` and `tdd`, and vstack `verify-valentin-mode`. The first three say how to build a check; `verify-valentin-mode` proves the three tools but not the sub-rules below. This skill adds one graded scenario per sub-rule.

Each scenario is a whole chat: a small job that triggers one rule, then a grade from what the chat did (tool calls, files, board writes), never from what it said. A `--break` run strips the rule's source from the scratch copy, so the same chat skips it and the same check fails.

## Run

```sh
.claude/skills/verify-valentin-subskills/run --scenario plain-words
.claude/skills/verify-valentin-subskills/run --scenario plain-words --break plain-words
```

Scenarios: `plain-words` (unjargon read before a ticket comment), `report` (report-page read before an HTML page), `ticket` (a ticket for a new ask before the work), `handover` (the long-chat handover file, first line right), `prs` (`pr-queue --mine` run).

`run` does, in order:

1. Gate: `~/.local/bin/plan-pick --claude-helper` must exit 0. Else exit 3. One Sonnet chat per run, `--max-turns 30`, under a 20-minute timeout.
2. Makes a scratch git repo in `/tmp/vvs-scratch.*` holding just a notes file and a short project rules file, and copies `valentin-mode`, `responsive-mode` and the scenario's own skill into it.
3. `--break <scenario>` deletes the rule's line from `valentin-mode/SKILL.md` and renames that scenario's skill folder to `<name>.off`, in the installed tree as well as the scratch copy, because the chat's `/valentin-mode` loads the installed copy. An EXIT trap puts both back.
4. Starts `claude -p` as the test agent with `--model sonnet`, `--permission-mode bypassPermissions`, a debug log and `--output-format stream-json`. The prompt starts with `/valentin-mode` and asks for the scenario's job. It never names a skill.
5. Writes the scenario name into the evidence and regrades. Evidence keeps the stream, the debug log, the prompt and the verdict.

## Grades

One PASS/FAIL line per scenario run, then `VERDICT`. All five read the stream's ordered tool calls:

| Scenario | PASS when |
| --- | --- |
| plain-words | a read of `unjargon/SKILL.md` (or `pospeak/SKILL.md`) comes before the first ticket comment write |
| report | a read of `report-page/SKILL.md` comes before the first HTML file write |
| ticket | a board ticket is created before the ask's file is written |
| handover | `~/.local/state/long-chat/<session>.md` starts with the handover's required first line, and `long-chat/SKILL.md` was read before it was written |
| prs | a `pr-queue` run carries `--mine` and a chat name |

## Cost and honesty

One run costs one small Sonnet chat and no worker. A FAIL is a finding about the chat, not a broken check: the break run has to FAIL, and a real run that fails means valentin mode did not get that rule across. Read the `--break` verdict on the PR, and say which scenarios were run live.
