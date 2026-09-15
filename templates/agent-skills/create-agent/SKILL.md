---
name: create-agent
description: Provision a skills-driven agent identity : a worker that reads a skills index before it does anything, optionally wired into a tracker board, or just pointed at a repo. Invoke via /create-agent. Dry-run by default; never creates or revokes a real identity without an explicit go-ahead.
version: 3.0.0
---

# /create-agent : provision an agent identity

This skill is about the method, not about any one tool. An agent is a name, a
mission, a skills index, a model CLI and somewhere to work. A tracker is
optional, and when there is one it sits behind an adapter.

Valentin types `/create-agent` and answers in plain words. He never sees a
flag. This file is the conversation; the scripts are the mechanism.

## Where this comes from

The canonical copy lives in the `vstack` repo under
`templates/agent-skills/create-agent/`. What sits in `~/.claude/skills` and
`~/.local/bin` on any machine is an installed copy, put there by that folder's
`install.sh`. Fix bugs in the repo and re-run `install.sh`, never the other way
round.

## Example dialogue

```
Valentin: /create-agent
Claude: Four things, one message:
  1. Name? (e.g. "FP CRO Bot")
  2. What does it do : ships fixes, verifies only, or a plain worker?
  3. Where does its work come from : a board (which one?), or just a repo?
  4. Does it need a chat page people can message it on? (default: no)
Valentin: FP CRO Bot, plain worker, board 2078, no chat
Claude: Plan:
  1. Mission built, pointed at the skills index
  2. Identity created on board 2078, its token saved to a 0600 file
  3. Poll wiring: a timer runs one tick a minute on this machine
  4. Dry run first, then the real run
  5. Self-test on a throwaway ticket, and I quote its reply
  Go?
Valentin: go
Claude: [runs the script with --yes] ... FP CRO Bot picked up the test ticket
  and replied "Read the skills index, matched cro-audit, ran the fixture."
  Timer active. Conf and token both 0600.
```

## What the session does

1. **Read whatever free text followed `/create-agent`.** If it already answers
   name / kind / where the work comes from / chat page, skip to the plan. Only
   ask for what is missing.
2. **Ask the missing questions in one `AskUserQuestion` call:**
   - **Name** : plain text.
   - **Kind** : dev (ships fixes), QA (verifies, never fixes), plain worker, or
     a CLI identity (a name for logs and commit trails, nothing else).
   - **Which board** : the tracker and the board id, or "just a repo".
   - **Chat page?** : default **no**. Say yes only if a person needs to message
     the agent in a hosted chat window. It is the one thing poll wiring cannot
     give you.
   Never show a flag name to him: map his words yourself.
3. **Show a five-line plan and ask "go?"** before anything real happens. If the
   skills index has no skill matching this agent's domain, write that skill
   first; an agent with nothing to read is not an agent.
4. **Run the script dry first, then with `--yes`.** If the identity already
   exists, add `--resume`: it skips creation and only fills in what is missing.
5. **Finish with evidence.** A self-test ticket, the reply quoted verbatim, and
   the timer's state. An agent nobody has seen do one piece of work is not
   finished, and saying so plainly beats a green checklist.

## The three wiring modes

| Mode | What it needs | What you get | When to pick it |
|---|---|---|---|
| **poll** (default) | the board CLI and a model CLI on this machine, nothing else | a 60-second timer; each tick reads the board and starts one short-lived process per new ticket | almost always, and always for a growth, CRO or support bot |
| **fleet** | a long-lived worker runtime already installed on this machine, which the adapter checks for | webhooks, a chat lane, the runtime's own queue and retries | only where that runtime is already running |
| **none** | nothing | an identity, a conf, a skills index; you trigger it from cron, CI or by hand | repo-only agents, and CLI identities |

**Poll mode runs on any machine that has the board CLI and a model CLI. It
needs no shared fleet infrastructure and no second machine.** If `--wiring
fleet` is asked for where the runtime is absent, the script stops and names
poll mode instead of dead-ending.

A chat page is the one capability poll mode does not have, which is why the
question defaults to no.

## Shape of the code

```
core
  scripts/create-agent.sh     provisioning: identity, conf, wrapper, wiring
  scripts/agent-board-poll    one work tick: read, decide, spawn, log
  scripts/lib/core.sh         slug, conf files, secrets, adapter loading
adapters/
  hypertask/adapter.sh        everything that talks to a Hypertask board
  linear/adapter.sh           stub: same function names, all refuse loudly
  none/adapter.sh             repo-only: reads return nothing, writes refuse
```

Core names no tracker, no vendor and no machine. The runner sources
`adapters/<board>/adapter.sh` and calls its functions. Adding a tracker means
writing one adapter file; nothing in core changes. The contract is the function
list in `scripts/lib/core.sh`, and a missing function fails at load time with
our own message rather than "command not found" three layers down.

## What a poll tick does

1. Read the agent's conf and load its adapter.
2. Take a non-blocking lock; if a tick is already running, exit.
3. List the board's tickets in the watched columns.
4. Keep the ones **assigned to this agent id**, or whose **newest comment
   @mentions it**.
5. Drop anything already handled. The state key is `<task id>:<newest comment
   id>`, so a fresh reply on an old ticket counts as new work and a re-read of
   the same one does not.
6. For each remaining ticket, up to `MAX_CONCURRENT_RUNS`, start **one
   short-lived process**: the prompt tells it to read the skills index first,
   gives it the ticket and the latest comment, and tells it to post its reply
   with the agent's own board CLI and move the ticket per the skills index.
7. Log to `~/.local/state/agent-board-poll/<slug>.log` and exit.

Nothing survives the process except the board, the repo and that log. This is
the one-process-per-ticket design: the board is the state, so there is no
queue, no lock database and no daemon to drift.

**Why a timer plus `Type=oneshot`, not a service with a loop.** systemd refuses
to start a second run of a oneshot unit while one is still active, so the
concurrency guard is free and correct. A `Restart=always` loop would need its
own sleep, its own crash handling and its own guard, and would hold a process
open between ticks for no reason. The timer's schedule is also readable with
`systemctl --user list-timers`, which a loop's internal sleep is not.

## The conf

`<config dir>/<slug>.conf`, 0600. Core keys, no tracker prefixes:

| Key | Meaning |
|---|---|
| `AGENT_ID` | the identity's id on the board |
| `AGENT_NAME` | display name, used in the prompt |
| `BOARD_ADAPTER` | which adapter to load |
| `BOARD_ID` | the board this agent watches |
| `TOKEN_FILE` | absolute path to the 0600 token file |
| `BOARD_CLI` | the wrapper that runs board writes as this agent |
| `WATCH_SECTIONS` | comma-separated columns to watch |
| `SKILLS_INDEX` | absolute path to the index the agent reads first |
| `MODEL_CLI` | command template, default `claude -p --model sonnet` |
| `MAX_CONCURRENT_RUNS` | runs started per tick, default 1 |

Override `MODEL_CLI` to change model or vendor, for example `cursor-agent -p`.
A headless model CLI usually needs its own permission flags; put them in this
value, because the runner passes the template through untouched.

## Tokens

The board prints an agent's bearer token exactly once, when the identity is
created. The script parses it out of the reply with a JSON parser (never a
grep, which happily matches the word "token" in the reply's own advice text),
writes it straight to a 0600 file under `umask 077`, and checks the file is
non-empty and really 0600 before going on.

If the token cannot be parsed, the script **stops** and prints the exact rotate
command to run with the owner's go-ahead, plus the path to save the result to.
It never carries on with a half-made agent, and it never prints the token, not
in a log, not in a prompt, not in a command line. Board writes go through a
one-line wrapper that reads the token file at call time.

## Hard rules

- **Dry run is the default.** Nothing is created, changed or installed without
  `--yes`. Read-only checks still run, so a duplicate name fails before any
  local write.
- **Creating an identity has its own stop** on top of `--yes`: it makes a real
  account someone has to clean up.
- **Existing identities need `--resume`**, which never replaces a value that is
  already there.
- **Never print a token or a secret.** Paths only.
- **Never assign the owner's own user id** to an agent identity.
- **A CLI identity cannot chat.** Do not promise a chat test for one.
- **QA gets its own browser storage state**, never a person's and never a dev's.

## Check before you say done

- the conf and the token file are both 0600, and the token file is not empty
- the skills index exists and has a skill matching this agent's work
- `agent-board-poll --once --dry-run <slug>` lists the tickets you expect
- `agent-board-poll --once <slug>` posted a real reply as the agent, and you
  quote it
- the timer is active, and the log shows a finished tick
- fleet wiring only where the adapter confirmed a runtime; otherwise poll

## Reference

- `install.sh` in this folder : puts the skill and the runner on a machine
- `scripts/create-agent.sh --help`, `agent-board-poll --help` : every flag
- `scripts/lib/core.sh` : the adapter contract, as a function list
