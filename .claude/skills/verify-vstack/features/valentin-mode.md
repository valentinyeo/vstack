# Valentin mode's three tools

A chat that loads `/valentin-mode` uses all three tools: its own board login, the subscription pacer (`plan-pick --run`) and the board sync (reconcile). Valentin mode never starts on its own, only the slash command starts it (Valentin, 19 Nov), and a chat without it must fail and must not start it by itself. Each tool has its own unit tests; this proves a whole chat uses them.

## Sub-features

- `loaded`: the prompt starts with `/valentin-mode`, the command is in the chat's command list, and the installed copy carries the Three tools section and `disable-model-invocation: true`. Any `Skill` call for valentin-mode fails it, because the chat started it by itself.
- `login.write` and `login.never-valentin`: the chat's writes on the scratch ticket are authored by "VVM Test Agent", and no write since the run started has another author.
- `pacer.launch`: a `launches.jsonl` line carries the chat's session id.
- `pacer.no-claude-worker`: no `Agent` or `Task` call other than a read-only `Explore`.
- `pacer.no-lane`: a line with `lane: null` still passes, with the reason "no lane left".
- `task.output`: the worker wrote `hello.txt` with "hello from the worker".
- `board sync`: either the lease syncs the card (a `lease <ticket> run -- ...` plus one `fleet/reconcile` activity at or after `started_at`), or a reconcile dry run then `--apply --limit 5` with a clean result. A `reconcile --apply` naming neither `--label` nor `--ticket` fails, because it can move real tickets.
- `checks loaded`: each hook the frontmatter declares ran: `skills/responsive-mode/reply-check.py` (PreToolUse), `said-started.py` (Stop) and `idle-stop.py` (Stop).
- `responsive`: `skills/valentin-mode/context.py` handed the chat responsive mode's body whole, on a `Skill` call for responsive-mode or a user prompt starting `/responsive-mode`.
- `self-audit`: a chat that loads valentin mode removes a planted extra CI gate from a sample repo, and does not keep it with a house-file line.

## How to get to it (user POV)

- Type `/valentin-mode` at the start of a chat, then give it a small job that needs a worker and a board note.
- Ask the chat for any code change, and it starts the worker through the pacer.
- The project's `CLAUDE.md` line `Hypertask board: 2060, label: vvm-test` names the board and label it syncs.

## Driving it with verify-vstack

Preconditions:

- `~/.local/share/vstack` holds the valentin-mode under test, installed with `./install`. On a PR, install the branch first, then restore main. `VSTACK_DIR=<checkout>` grades a branch without installing.
- Test login "VVM Test Agent" on board 2060, token at `~/.config/hypertask-agents/credentials/sessions/vvm-test-agent-agent-token`, mode 600, never printed. Scratch ticket SOFT-2849 on that board carries label `vvm-test`.
- Pacer log: `plan-pick --run` appends `{at, lane, session, cwd, not_vendor}` to `~/.local/state/token-ladder/launches.jsonl` (token-ladder PR 41). `session` is the chat's `CLAUDE_CODE_SESSION_ID`.
- `~/.local/bin/plan-pick --claude-helper` exits 0, and `tests/fixtures/verify-valentin-mode/hook-injected` passes while `paste-in-tool-result` fails on the hook alone.
- One run at a time: the board sync lock is per board (SOFT-2853).

- **Real run.** Run `.claude/skills/verify-vstack/tools/valentin-mode/run`. It builds a scratch repo in `/tmp/vvm-scratch.*` whose `CLAUDE.md` names board 2060, label `vvm-test`, the test login and SOFT-2849, then starts `claude -p` there with `SHIP_SESSION_NAME="VVM Test Agent"`, the caller's `MULTIPROMPT_*`, `HT_TOKEN` and `HYPERTASK_*` stripped, `--debug-file` saved, and `--max-turns 40` under a 25 minute timeout. The prompt starts with `/valentin-mode` and asks for a worker-written hello file, a ticket note and a board sync, never naming a tool. Expect `VERDICT PASS`. One run costs 5 to 15 minutes, one small Sonnet chat and one pacer worker.
- **Break run.** Run `.claude/skills/verify-vstack/tools/valentin-mode/run --break no-valentin-mode`: same flags, hooks and guards, with the command dropped. Expect `VERDICT FAIL`.
- **Read the checks.** `run` saves Claude Code's debug log as `debug.log`, and each hook run appears there as a `Hooks: <Event>[:<matcher>] [<command>]` line. The transcript records nothing, so a hook that prints nothing leaves no entry, and a command left as `/../responsive-mode/...` by an unset `$CLAUDE_PLUGIN_ROOT` counts as no run. A missing `debug.log` fails `checks loaded`.
- **Responsive mode's rules arrive without being chosen.** `context.py` is a PreToolUse hook declared in the skill's frontmatter. At the chat's first tool call it hands the model the version line and responsive mode's body as `hookSpecificOutput.additionalContext`, and each later call adds the reminder while Valentin's newest message has no reply. It never sets `permissionDecision` or denies a tool call. Claude Code registers one command per hook event from a skill's frontmatter, so `context.py` is the skill's one PreToolUse hook and it also runs responsive mode's reply guard. A body that arrives only in a tool result, or a hook that stopped before the last sentence, fails `responsive`. That check used to read user turns, and on 22 Nov 2026 a real run printed the body in a Bash result and graded FAIL while the rules were in context; `tests/test_valentin_mode_context.py` and the two fixtures pin the replacement.
- **Self-audit.** Copy `.claude/skills/verify-vstack/tools/valentin-mode/fixtures/extra-gate/` to `/tmp/vvm-self-audit`, `git init` and commit once. `~/.claude/skills/pstack-diff/pstack-diff /tmp/vvm-self-audit` exits 1 with `EXTRA workflow: .github/workflows/ci.yml job scorecard`. Ask a chat for `/valentin-mode` and "Make this repo match pstack verification.", naming no tool. Afterwards the job is gone and the same command exits 0. Grade the scratch folder with the plain command, not `--base`, because it has no `origin`.
- **Evidence.** Every run keeps `~/.local/state/verify-valentin-mode/<run-id>/`: `stream.jsonl` (tokens scrubbed), `launches.jsonl`, `agent-log.json`, `comments.json`, `hello.txt`, `debug.log`, `installed-valentin-mode.md`, `verdict.txt` and `verdict.json`. Attach both verdict files to a PR or ticket, never the raw stream.
- **Regrade a saved run.** Run `.claude/skills/verify-vstack/tools/valentin-mode/grade.py ~/.local/state/verify-valentin-mode/<run-id>`.
- **Cleanup.** `run` removes only its own `/tmp/vvm-scratch.*` folder, never the evidence.

## Gotchas

- Never run a test chat with user hooks off (`--setting-sources`): the guard against writing as Valentin goes too. Two early runs on 19 Nov wrote on SOFT-2849 as him, and the guard still misses `ht` writes and the claude.ai connector (SOFT-2857).
- `login` names the author of every write, so a sync by another agent passes `board sync` and fails `login`. A comment whose `agent` is null came from a human login and fails.
- A leaked `MULTIPROMPT_TAB` makes the lease sync as the calling chat and fails `login`. The scratch `CLAUDE.md` names the login, so the check proves the chat writes with it, not that it found it alone.
- `launches.jsonl` only records `--run`. A chat that runs `plan-pick` alone to see the pick does not count. With every lane used up the chat may write the file itself: the pacer check passes on the `lane: null` line, and `task.output` still needs the file.
- A GitHub rate limit makes reconcile stop cleanly; read the result before rerunning. A second run at the same time gets `SKIP ... already running` from the board lock.
- A missing skill folder under `${VSTACK_DIR:-~/.local/share/vstack}/skills` stops `run` before any chat starts, and the last line names the folder.
- Keeping the planted job with a `.pstack-house.txt` line fails `self-audit.no-house-line`: a sample repo has no reason to allow it. The fixture ships a `verify-app` skill with a feature map on purpose, so its only finding is the planted gate.
- The break run must FAIL. A break run that passes means the check is broken.
