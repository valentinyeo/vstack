---
name: join-slack
description: "join slack;join the fleet chat;get on slack;slack setup. /join-slack: put this lead session in Slack #fleet with the other leads. Reuses the lead's bot if it exists, points Slack mentions at this tmux session, checks read and reply. Use at lead startup, after a lead moves to a new session, or when Valentin says join Slack."
disable-model-invocation: true
---

# Join Slack #fleet

Every lead lives in #fleet. Valentin starts threads there. Leads reply inside them.

Prior art: pstack poteto-mode was checked for agent sessions and handoff rules. It carries no Slack transport, so the Slack setup steps stay here.

Tools are in `$HOME/.local/bin`. Run `export PATH=$HOME/.local/bin:$PATH` first.
Never print a token.

## 1. Who am I

- Session: `tmux display -p '#S'`.
  Run it in your own shell: it names the window you live in, even `term-*` or `live-*`.
  A subagent gets its parent's session. Trust that over an older row.
- Members list: `$HOME/.config/fleet-slack/members.tsv`.
  Columns: name, aliases, token var, uid var, delivery, target.
- Your row has your lead name (for example `cos`, `mini-boss`, `ci-boss`).

## 2. Row exists

Target is not your session? Repoint it. This keeps the bot token:

```bash
fleet-slack-add <KEY> "<Display Name>" <your tmux session> session-say
```

`KEY` is your row name in capitals (`COS`, `CIBOSS`).
The tool restarts the relay and prints `relay up`.
Delivery `none` means you only post, mentions never reach you. Repoint with the line above.

## 3. No row yet

- Check for a bot token: `grep -c "^SLACK_<KEY>_BOT_TOKEN=" ~/.config/fleet-slack/env`.
- Missing? Look in 1Password: `stack-key --list | grep -i slack`.
  Found: `stack-key <item> | fleet-slack-set-token <KEY>`.
- Still missing: a new Slack app is needed. That is a key.
  No agent can make one: the box has no Slack admin token.
  Every lead bot so far was made by Valentin (2026-10-30/31).
  Do not ask Chief Of Staff or other leads first. Go straight to the Question.
- Post one Question on your own lead ticket. Use the steps below, your name filled in.
  The people-comment check refuses the manifest as text: save it as a .yaml file and `--attach` it.
  Ask him to save the token in 1Password as `slack-<slug>` (example `slack-infra-lead`).

```text
What this is: your own Slack bot for <Display Name>, so it can answer you in #fleet. Free, about 2 minutes.
1. Open https://api.slack.com/apps?new_app=1 and pick "From a manifest", workspace Hypertask.
2. Paste the manifest below. Click Install to Workspace.
3. Copy the Bot User OAuth Token (starts xoxb-). Save it in 1Password as slack-<slug>.
4. In #fleet type: /invite @<Display Name>
Yes: I plug it in and answer in your threads. No: I stay off Slack, tickets only.

display_information:
  name: <Display Name>
features:
  bot_user:
    display_name: <Display Name>
    always_online: true
oauth_config:
  scopes:
    bot: [app_mentions:read, channels:history, channels:read, chat:write, users:read]
```

- After his yes: `stack-key slack-<slug> | fleet-slack-set-token <KEY>`.
- Then run the step 2 line.

## 4. Check

- Check your own row in `~/.config/fleet-slack/members.tsv`: delivery is `session-say`, the target is your current tmux session, and your UID variable is set. Check `systemctl --user is-active fleet-slack-relay`. Do not audit or repoint other leads.
- Reply test, posts nothing:
  `SLACK_SAY_DRY_RUN=1 slack-say <name> --thread <ts> "test"`.
  Take `<ts>` (like `1793700281.094899`) from a Valentin line in `slack-read 10`.

## Rules

- Reply only inside Valentin's threads: `slack-say <name> --thread <ts> "<msg>"`.
- No top-level, status or bot-to-bot posts. slack-say refuses them.
- `--alarm` only for a real alarm, max one per 2 hours.
- Caveman voice, full https links.
- Never take another lead's row or bot.

## Report

One line: `slack: <name> -> <session>, doctor ok, reply dry-run ok`.
