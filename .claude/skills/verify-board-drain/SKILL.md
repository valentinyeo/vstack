---
name: verify-board-drain
description: >-
  Prove that a fresh Claude Code chat, restarted after a crash, turns its own board drain loop back on by itself: reads its loop status, arms a 15-minute loop over its view, records it, syncs and passes drain-check. Starts one headless test chat in a scratch project with an expired loop, then grades the side effects PASS or FAIL per check. Use after any change to skills/board-drain or its scripts, as the proof on such a PR, and whenever a chat's loop looks dead.
---

# Verify board drain

Prior art: checked pstack (create-verification-skill), this repo's `verify-valentin-mode` and `skills/board-drain`. `verify-valentin-mode` proves a fresh chat uses its three tools; this proves a restarted chat re-arms its loop as `skills/board-drain/SKILL.md` says.

The proof bar is the restart: the loop state on disk is expired and owned by a chat process that no longer exists, so `loop-state status` exits 2. A chat that only talks about arming fails. The loop must be armed again, recorded with the job id, synced and checked.

Read `features/README.md` for the map.

## One-time setup (already done on this server)

- Test login: agent "VVM Test Agent" on board 2060, token at ~/.config/hypertask-agents/credentials/sessions/vvm-test-agent-agent-token (server only). Never print it.
- Board 2060, label `vvm-test`: the test queue. No real work carries that label.
- `~/.local/bin/plan-pick --claude-helper` exits 0.

If the login is gone, recreate it with `board-identity` steps 4 to 6; never reuse another agent's token.

## Launch

```sh
.claude/skills/verify-board-drain/run                        # real run, expect VERDICT PASS
.claude/skills/verify-board-drain/run --break no-board-drain  # broken setup, expect VERDICT FAIL
```

`run` does, in order:

1. Gate: `~/.local/bin/plan-pick --claude-helper` must exit 0, because the chat runs on Sonnet. Else exit 3.
2. Makes a scratch git repo in `/tmp/vbd-scratch.*` holding this checkout's `skills/board-drain` and `skills/hypertask-work`. Its `CLAUDE.md` names `Hypertask board: 2060, label: vvm-test` and the chat "VBD Test Chat".
3. Seeds `<scratch>/state/vbd-test-chat.json` with an expired loop from a dead chat, so `loop-state status` exits 2. The run refuses to start when the seed reads as armed.
4. Starts `claude -p` there with `BOARD_DRAIN_STATE_DIR=<scratch>/state`, `HT_TOKEN` from the token file and `SHIP_SESSION_NAME="VBD Test Chat"`, under `--model sonnet --output-format stream-json --verbose --max-turns 30`, 15-minute timeout. The prompt starts with `/board-drain`, says the chat just restarted, and never names a script.
5. `--break no-board-drain` drops the leading command. Same flags and hooks otherwise.
6. Collects the evidence, scrubs tokens, grades, removes the scratch repo (keep it with `--keep`).

A run takes 3 to 10 minutes and costs one small Sonnet chat.

## Doctor

Read `loaded` first, then `status-read`: a chat that never ran `loop-state status` skipped the skill's first step. Then `armed`: the job fires every 15 minutes, carries the loop prompt from `skills/board-drain/SKILL.md`, and names board 2060.

The chat reads the installed copy in `~/.local/share/vstack/skills/board-drain`. On a PR, install the branch first, then restore main. The scratch repo carries this checkout's scripts too.

## Drive

Only `run` drives. To regrade a saved run without a new chat:

```sh
.claude/skills/verify-board-drain/grade.py ~/.local/state/verify-board-drain/<run-id>
```

## Evidence

Every run keeps `~/.local/state/verify-board-drain/<run-id>/`:

| File | What it proves |
| --- | --- |
| stream.jsonl | the full chat, tokens scrubbed |
| state-before.json, status-before.txt | the seeded expired loop and the status it printed |
| state.json | the loop the chat left: armed_at, expires_at, job, last_sync |
| prompt.txt | the one prompt the chat got |
| verdict.txt, verdict.json | one PASS/FAIL line per check, then the verdict |

Grading reads side effects, never the chat's claims. On a PR, attach both verdict.txt files, never the raw stream.

## Cleanup

`run` removes only its own `/tmp/vbd-scratch.*` folder, never the evidence.

## When it runs

Every change to `skills/board-drain` or its scripts runs it here. CI runs only `tests/test_verify_board_drain.py`: the live run needs this server, the test login and board 2060.

## Gotchas

- **CronCreate is available in `claude -p`.** Checked on 2.1.329: the init line lists it, and a probe returned `Scheduled recurring job <id> (Every 15 minutes)`. It often arrives through `ToolSearch` first.
- **Second way in:** a `Skill` call to `loop` with `15m` and the same prompt, since `/loop` wraps cron. That path leaves no job id, so `recorded` skips the job comparison.
- **A session-only cron dies with the chat.** That is the point: the state file survives a restart, a live job does not.
- **Order matters.** `loop-state arm` rewrites the state file and drops `last_sync`; `sync` merges into it. Arming after syncing fails `synced`, which drain-check reports as `sync stale`.
- **Keep user hooks on.** Dropping hooks (`--setting-sources`) drops the guard against writing as Valentin.
- **One run at a time.** The board 2060 reconcile takes a lock, so two runs at once get `already running`.
