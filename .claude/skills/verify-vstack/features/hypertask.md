# Hypertask sets up a fresh chat

A fresh chat with only the hypertask skill sets itself up on a board and works one tiny task: it reads the skill, uses its own agent login, makes its view and label, writes the board line in the repo's notes, files one ticket and syncs the board dry then apply. The prompt never names a tool, and the scratch repo has no project notes, so the chat has to write them.

## Sub-features

- `read`: a `Skill` call for `hypertask`, or a `Read` of a path ending `skills/hypertask/SKILL.md`.
- `login.write`: every write on the scratch ticket since the run started is authored by "VVM Test Agent".
- `login.never-valentin`: no write since the run started has another author.
- `view.create`: a `view create` with `--project 2060` and `--label vvm-test`, with no error.
- `view.find`: a `view list --project 2060` whose result names `vvm-test`.
- `board line`: the repo's notes hold one line matching `Hypertask board: 2060`, with no label or with `label: vvm-test`.
- `ticket.one`: exactly one task on board 2060 carries label `vvm-test` and was created at or after `started_at`.
- `sync.dry`: `reconcile --board 2060 --label vvm-test` without `--apply`.
- `sync.apply`: then the same with `--apply --limit 5`, and its result is not an error.

## How to get to it (user POV)

- Start a chat in a repo with no `CLAUDE.md` or `AGENTS.md` board line and say `/hypertask`.
- Ask for setup on a board plus one tiny job, the way a new project starts.
- Read the notes file, the view list and the ticket afterwards to see what the chat did.

## Driving it with verify-vstack

Preconditions:

- `~/.local/share/vstack` holds the skill under test, installed with `./install`. On a PR, install the branch first (`git checkout <branch> && ./install` there), then restore main.
- Test login "VVM Test Agent" on board 2060, token at `~/.config/hypertask-agents/credentials/sessions/vvm-test-agent-agent-token`, mode 600. Never print it.
- Scratch ticket SOFT-2849 on board 2060 with label `vvm-test`; test chats write there and nobody works it.
- `~/.local/bin/plan-pick --claude-helper` exits 0.
- One check at a time: the board sync lock is per board.

- **Real run.** Run `.claude/skills/verify-vstack/tools/hypertask/run`. It gates on plan-pick, makes an empty git repo in `/tmp/vh-scratch.*` with no CLAUDE.md or AGENTS.md, and starts `claude -p` there with `--model sonnet --output-format stream-json --verbose --max-turns 40` under a 25 minute timeout. The prompt starts with `/hypertask` and asks for setup on board 2060 plus one tiny job. Expect `VERDICT PASS`. A run takes 5 to 15 minutes and costs one small Sonnet chat.
- **Collect.** The run saves the notes, the hello file, the board's tasks and views, the ticket's agent log and comments, scrubbing tokens.
- **Check each one.** `read` looks for one of the two reads. `login` needs every activity and comment with `createdAt` at or after `started_at` to carry `agentName` or `agent.displayName` "VVM Test Agent". `view` needs one of the two view calls with the exact board and label. `board line` reads `notes.md`, copied from the scratch project's CLAUDE.md or AGENTS.md. `ticket` counts new tasks in the label and needs exactly one. `sync` needs a dry run before an apply, with no error line in the apply result.
- **Evidence.** Every run keeps `~/.local/state/verify-hypertask/<run-id>/`: `stream.jsonl`, `notes.md`, `tasks.json`, `views.json`, `agent-log.json`, `comments.json`, `hello.txt`, `verdict.txt` and `verdict.json`. Attach both verdict files to a PR, never the raw stream.
- **Regrade a saved run.** Run `.claude/skills/verify-vstack/tools/hypertask/grade.py ~/.local/state/verify-hypertask/<run-id>`.
- **Cleanup.** `run` removes only its own `/tmp/vh-scratch.*`, never the evidence, and prints the key of the ticket the chat filed. Archive that ticket by hand: one per run.

## Gotchas

- Never run a test chat with user hooks off (`--setting-sources`): the guard against writing as Valentin goes too.
- An apply without `--label vvm-test` fails the check, because it can move real tickets.
- A second run at the same time gets `SKIP ... already running` from the board lock.
- SOFT-2849 carries the label and is older than any run, so it never counts as the filed ticket. Zero new tickets fails, and two or more fails.
- A view named "VVM Test Agent" and the label `vvm-test` are reused on later runs. That is expected.
- A chat that works from memory of an old skill, without reading, fails `read` even when its board work is right.
