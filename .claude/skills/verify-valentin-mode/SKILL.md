---
name: verify-valentin-mode
description: >-
  Prove that a fresh Claude Code chat on this server really uses valentin mode's three tools: its own board login, the subscription pacer (plan-pick --run) and the board sync (reconcile). Starts one headless test chat with a tiny task in a scratch project, then grades the evidence PASS or FAIL per tool. Use after any change to skills/valentin-mode, skills/hypertask-work, the valentin-mode load hook, or plan-pick, and as the proof on such a PR.
---

# Verify valentin mode

Prior art: checked pstack (create-verification-skill, maintain-verification-skill), vstack (hypertask-work, do) and house-rules. None fits, because they define the tools or how to build a check, not a check that a fresh chat uses them. This skill is the `verify-<app>` skill pstack create-verification-skill asks for, with valentin mode as the app.

The surface is a whole chat, not one script. Each tool has its own unit tests. This skill proves a fresh chat picks all three up from valentin mode alone and uses them on a real task.

Read `features/README.md` for the map, then the feature file for the check you are looking at.

## One-time setup (already done on this server, 19 Nov 2026)

- Test login: agent "VVM Test Agent" on board 2060. Token at `~/.config/hypertask-agents/credentials/sessions/vvm-test-agent-agent-token`, chmod 600. Never print it.
- Scratch ticket: SOFT-2849 on board 2060, label `vvm-test`. Test chats write there. Nobody works it.
- Pacer log: `plan-pick --run` appends `{at, lane, session, cwd, not_vendor}` to `~/.local/state/token-ladder/launches.jsonl` (token-ladder PR 41). `session` is the chat's `CLAUDE_CODE_SESSION_ID`.

If the test login is gone, recreate it with the `board-identity` skill steps 4 to 6, name "VVM Test Agent", board 2060, slug `vvm-test-agent` (file `vvm-test-agent-agent-token`). Never reuse another agent's token.

## Launch

```sh
.claude/skills/verify-valentin-mode/run            # real run, expect VERDICT PASS
.claude/skills/verify-valentin-mode/run --break no-valentin-mode   # broken setup, expect VERDICT FAIL
```

`run` does, in order:

1. Gate: `~/.local/bin/plan-pick --claude-helper` must exit 0. The test chat runs on Claude Sonnet, so it waits while Claude is ahead of pace (exit 3).
2. Makes a scratch git repo in `/tmp/vvm-scratch.*` whose `CLAUDE.md` names board 2060, label `vvm-test`, the test login and SOFT-2849.
3. Starts `claude -p` there with `--model sonnet --output-format stream-json --verbose --max-turns 40`, under a 25-minute timeout. The prompt asks for a code worker to write `hello.txt`, a note on the ticket, and a board sync. It never names the tools; valentin mode has to.
4. `--break no-valentin-mode` adds `--setting-sources project,local`, so user hooks do not run and valentin mode never loads. That is the known-broken setup.
5. Collects the evidence, scrubs tokens, grades, removes the scratch repo (keep it with `--keep`).

Ready means the stream has a `system/init` line. A run takes 5 to 15 minutes and costs one small Sonnet chat plus one pacer worker.

## Doctor

Before trusting a verdict, read the `loaded` line. It checks that the SessionStart hook `~/.claude/hooks/valentin-mode-load.py` put "valentin-mode is loaded" into the chat. A FAIL there on a run without `--break` means the hook or the `~/.local/share/vstack` install is broken, not the chat.

Also confirm the installed copy is the one under test: `diff ~/.local/share/vstack/skills/valentin-mode/SKILL.md skills/valentin-mode/SKILL.md`. A branch is only tested once installed. On a PR, install the branch first (`cd ~/.local/share/vstack && git checkout <branch> && ./install`), then restore main afterwards.

## Drive

Only `run` drives. To regrade a saved run without a new chat:

```sh
.claude/skills/verify-valentin-mode/grade.py ~/.local/state/verify-valentin-mode/<run-id>
```

## Evidence

Every run keeps `~/.local/state/verify-valentin-mode/<run-id>/`:

| File | What it proves |
| --- | --- |
| `stream.jsonl` | the full chat: hook output, every tool call and result (tokens scrubbed) |
| `launches.jsonl` | pacer lines for this chat's session id |
| `agent-log.json`, `comments.json` | who wrote on SOFT-2849 |
| `hello.txt` | the worker's output |
| `verdict.txt`, `verdict.json` | one PASS/FAIL line per check and the verdict |

Grading reads side effects, not the chat's own claims: the pacer log, the board's author fields, the file on disk, and the reconcile results.

For a PR or ticket, attach `verdict.txt` and a trimmed list of the tool calls, never the raw stream.

## Cleanup

`run` removes only its own `/tmp/vvm-scratch.*` folder. It never deletes the evidence folder. Test notes pile up in the SOFT-2849 agent log; that is expected.

## When it runs

Every change to `skills/valentin-mode`, `skills/hypertask-work`, the load hook or plan-pick runs it on this server, with `verdict.txt` on the PR. GitHub CI runs only the grader tests (`tests/test_verify_valentin_mode.py`), because the live run needs this server's hooks, logins and pacer, and self-hosted runners are banned.

## Gotchas

- Do not run two checks at once. The board sync takes a lock per board and the second run prints `SKIP`.
- The verdict depends on the installed copies under `~/.local/share/vstack`, `~/.claude/skills` and `~/.local/bin`, not on this checkout.
