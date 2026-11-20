---
name: verify-hypertask
description: >-
  Prove that a fresh Claude Code chat with only the hypertask skill can set
  itself up on a board and work a task: read the skill, use its own agent login,
  make its view and label, write the board line, file one ticket, and sync the
  board dry then apply. Starts one headless chat in an empty scratch repo, then
  grades the evidence PASS or FAIL per check. Use after any change to
  skills/hypertask, hooks/reconcile-auto.py or skills/hypertask-work/lease.
---

# Verify hypertask

Prior art: pstack `create-verification-skill` was checked for the shape of a check; this is its `verify-<app>` skill with the hypertask skill as the app. It follows `verify-valentin-mode` in this repo.

Each rule has its own tests; this proves one whole chat uses the skill from one prompt. The prompt starts with `/hypertask` and never names a tool. No project notes exist, so the chat must write the board line itself.

Read `features/README.md` for the map.

## One-time setup

- Test login: agent "VVM Test Agent" on board 2060. Token at `~/.config/hypertask-agents/credentials/sessions/vvm-test-agent-agent-token`, mode 600. Never print it.
- Scratch ticket: SOFT-2849 on board 2060, label `vvm-test`. Test chats write there. Nobody works it.
- `plan-pick --claude-helper` exits 0.

If the login is gone, recreate it with the `/hypertask` skill's identity steps: name "VVM Test Agent", board 2060. Never reuse another agent's token.

## Launch

```sh
.claude/skills/verify-hypertask/run            # real run, expect VERDICT PASS
.claude/skills/verify-hypertask/run --keep     # keep the scratch repo
```

`run` does, in order:

1. Gates on `plan-pick --claude-helper`, because the chat runs on Claude Sonnet.
2. Makes an empty git repo in `/tmp/vh-scratch.*`, with no CLAUDE.md or AGENTS.md.
3. Starts `claude -p` with `--model sonnet --output-format stream-json --verbose --max-turns 40`, under a 25-minute timeout. The prompt starts `/hypertask` and asks for setup on board 2060 plus one tiny job.
4. Collects the notes, the hello file, the board's tasks and views, the ticket's agent log and comments, scrubs tokens, grades, and removes the scratch repo.

A run takes 5 to 15 minutes and costs one small Sonnet chat.

## Doctor

Six checks in `grade.py`. Read `features/README.md` for each one.

The chat reads the installed copy in `~/.local/share/vstack`, not this checkout. On a PR, install the branch first (`git checkout <branch> && ./install` there), then restore main.

## Drive

Only `run` drives. To regrade a saved run:

```sh
.claude/skills/verify-hypertask/grade.py ~/.local/state/verify-hypertask/<run-id>
```

## Evidence

Every run keeps `~/.local/state/verify-hypertask/<run-id>/`:

| File | What it proves |
| --- | --- |
| stream.jsonl | the full chat, tokens scrubbed |
| notes.md | the board line the chat wrote |
| tasks.json, views.json | the ticket in the label, and the view |
| agent-log.json, comments.json | who wrote on SOFT-2849 |
| hello.txt | the tiny job ran |
| verdict.txt, verdict.json | one PASS/FAIL line per check, then the verdict |

Grading reads side effects, never the chat's claims. Attach both verdict files to a PR, never the raw stream.

## Cleanup

`run` removes only its own `/tmp/vh-scratch.*`. It never deletes evidence.

The chat files one ticket in label `vvm-test` on board 2060. `run` prints it. Archive it by hand after a run: one test ticket per run.

## When it runs

Every change to `skills/hypertask`, `hooks/reconcile-auto.py` or `skills/hypertask-work/lease` runs it here, verdict on the PR. GitHub CI runs only `tests/test_verify_hypertask.py`: the live run needs this server, and self-hosted runners are banned.

## Gotchas

- Never run a test chat with user hooks off (`--setting-sources`): the guard against writing as Valentin goes too.
- A sync apply without `--label vvm-test` fails the check: it can move real tickets.
- One check at a time: the board sync lock is per board.
- A view named "VVM Test Agent" and the label `vvm-test` are reused on later runs. That is expected.
