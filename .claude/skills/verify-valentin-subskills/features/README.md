# Valentin mode sub-rules verification map

Five sub-rules valentin mode names, each proved by one scenario in `run` and graded in `grade.py`. Read this, then the file for the scenario. Each scenario starts one cheap Sonnet chat and grades the side effects, never the chat's claims.

## Baseline preconditions

- `~/.local/share/vstack` holds the valentin-mode under test, installed with `./install`.
- `~/.local/bin/plan-pick --claude-helper` exits 0. `run` stops with exit 3 when it does not.
- One run at a time; the `--break` run mutates the installed tree, so it must not overlap a real run.

## Driving conventions

- Only `run` starts a chat. The prompt names valentin mode, never a tool.
- `.claude/skills/verify-valentin-subskills/run --scenario <name>` is the only way to drive a scenario.
- `.claude/skills/verify-valentin-subskills/run --scenario <name> --break <name>` is the run that must FAIL.

## Proof and skip reporting

- Each grade reads the stream's ordered tool calls: a read, then the side effect it should have come before.
- A run that could not start (gate closed, no stream) is reported as not run, never as PASS.
- Say which scenarios were run live and read the `--break` verdict on the PR.

## Features

| File | Scenario | Sub-rule |
| --- | --- | --- |
| [plain-words.md](plain-words.md) | `plain-words` | unjargon read before a ticket comment |
| [report.md](report.md) | `report` | report-page read before an HTML page |
| [ticket.md](ticket.md) | `ticket` | a ticket for a new ask before the work |
| [handover.md](handover.md) | `handover` | the long-chat handover file, first line right |
| [prs.md](prs.md) | `prs` | `pr-queue --mine` for the chat's own PRs |
