---
name: verify-valentin-mode
description: >-
  Prove that a fresh Claude Code chat on this server really uses valentin mode's three tools: its own board login, the subscription pacer (plan-pick --run) and the board sync (reconcile). Starts one headless test chat with a tiny task in a scratch project, then grades the evidence PASS or FAIL per tool. Use after any change to skills/valentin-mode, skills/hypertask-work or plan-pick, and as the proof on such a PR.
---

# Verify valentin mode

Prior art: checked pstack (create-verification-skill, maintain-verification-skill), vstack (hypertask-work, do) and house-rules. None fits, because they define the tools or how to build a check, not a check that a fresh chat uses them. This skill is the `verify-<app>` skill pstack create-verification-skill asks for, with valentin mode as the app.

Each tool has its own unit tests; this proves a whole chat uses them. Valentin mode never starts on its own; only `/valentin-mode` starts it (Valentin, 19 Nov). A chat started with it must use all three tools; a chat without it must fail and must not start it by itself.

Read `features/README.md` for the map.

## One-time setup (already done on this server, 19 Nov 2026)

- Test login: agent "VVM Test Agent" on board 2060. Token at ~/.config/hypertask-agents/credentials/sessions/vvm-test-agent-agent-token (server only), chmod 600. Never print it.
- Scratch ticket: SOFT-2849 on board 2060, label `vvm-test`. Test chats write there. Nobody works it.
- Pacer log: `plan-pick --run` appends `{at, lane, session, cwd, not_vendor}` to ~/.local/state/token-ladder/launches.jsonl (server only) (token-ladder PR 41). `session` is the chat's `CLAUDE_CODE_SESSION_ID`.

If the test login is gone, recreate it with `board-identity` steps 4 to 6: name "VVM Test Agent", board 2060. Never reuse another agent's token.

## Launch

```sh
.claude/skills/verify-valentin-mode/run            # real run, expect VERDICT PASS
.claude/skills/verify-valentin-mode/run --break no-valentin-mode   # broken setup, expect VERDICT FAIL
```

`run` does, in order:

1. Gate: `~/.local/bin/plan-pick --claude-helper` must exit 0, because the test chat runs on Claude Sonnet. Else exit 3.
2. Makes a scratch git repo in `/tmp/vvm-scratch.*` whose `CLAUDE.md` names board 2060, label `vvm-test`, the test login and SOFT-2849.
3. Starts `claude -p` there with `--model sonnet --output-format stream-json --verbose --max-turns 40`, under a 25-minute timeout. The prompt starts with `/valentin-mode`, then asks for a worker-written hello file, a ticket note and a board sync. It never names the tools.
4. `--break no-valentin-mode` drops the command. Same flags, hooks and guards.
5. Collects the evidence, scrubs tokens, grades, removes the scratch repo (keep it with `--keep`).

A run takes 5 to 15 minutes and costs one small Sonnet chat plus one pacer worker.

## Doctor

Read the `loaded` line first. It needs the `/valentin-mode` prompt, the command in the chat's command list, and an installed copy with the Three tools section and `disable-model-invocation: true` (saved as installed-valentin-mode.md). Any Skill call for valentin-mode fails it: the chat started it by itself.

The chat reads the installed copy in ~/.local/share/vstack, not this checkout. On a PR, install the branch first (`git checkout <branch> && ./install` there), then restore main.

## Drive

Only `run` drives. To regrade a saved run without a new chat:

```sh
.claude/skills/verify-valentin-mode/grade.py ~/.local/state/verify-valentin-mode/<run-id>
```

## Evidence

Every run keeps `~/.local/state/verify-valentin-mode/<run-id>/`:

| File | What it proves |
| --- | --- |
| stream.jsonl | the full chat, tokens scrubbed |
| launches.jsonl | pacer lines for this chat's session id |
| agent-log.json, comments.json | who wrote on SOFT-2849 |
| hello.txt | the worker's output |
| verdict.txt, verdict.json | one PASS/FAIL line per check, then the verdict |

Grading reads side effects, never the chat's claims. On a PR or ticket, attach both verdict.txt files, never the raw stream.

## Cleanup

`run` removes only its own `/tmp/vvm-scratch.*` folder, never the evidence.

## When it runs

Every change to `skills/valentin-mode`, `skills/hypertask-work` or plan-pick runs it here, verdicts on the PR. GitHub CI runs only `tests/test_verify_valentin_mode.py`: the live run needs this server, and self-hosted runners are banned.

## Gotchas

- Never run a test chat with user hooks off (`--setting-sources`): the guard against writing as Valentin goes too. Two early runs on 19 Nov wrote on SOFT-2849 as him. The guard still misses `ht` writes and the claude.ai connector (SOFT-2857).
- A `reconcile --apply` without `--label vvm-test` fails the check: it can move real tickets.
- One check at a time: the board sync lock is per board (SOFT-2853).
