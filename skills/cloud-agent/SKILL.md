---
name: cloud-agent
description: >-
  Send a coding brief to a vendor cloud agent (Codex, Claude) instead of running it on this server, and get back the agent link and pull request. Use when starting a code worker, when the server is busy, when pstack asks for environment "cloud", or at /cloud-agent.
---

# Cloud agent

Prior art: pstack `swarm` spawns workers with `environment: "cloud"`, and `poteto-help` says parallel agents should run as cloud agents, "which each get their own machine". The pstack Claude Code adapter (`docs/harness/claude-code.md`) maps `cloud` to a local worktree, so on this server pstack's cloud work lands on the overloaded box. This skill adds only that gap: a launcher for the vendors' own clouds.

## When

- A code worker, a swarm slice or an arena runner that needs only the GitHub repo goes to the cloud.
- Work that needs this server stays here: the QA phone, a local app, board logins, files that are not pushed.
- Chats Valentin talks to stay on Claude, here.

## Which cloud

| Vendor | Use for | Cost |
|---|---|---|
| `codex` | Code workers | ChatGPT plan allowance |
| `claude` | Claude-native jobs only, after `plan-pick --claude-helper` exits 0 | Claude plan allowance |

Code workers go to `codex`; `claude` stays Claude-native only, per the pstack models rule.
Cursor is off (2026-11-23): the launcher refuses it.

## Run

Push the branch first. A cloud agent clones from GitHub and cannot see local files, so the brief carries everything the worker needs. Include `Owner chat: <your chat name>` in the brief and require that same line in the PR body; the Codex PR writer copies it from the full brief.

```sh
skills/cloud-agent/cloud-agent codex --repo <checkout> --brief brief.txt --env <codex env>
```

Run it as a tracked background job. It prints one JSON line: `status`, `agent_url`, `pr_url`, `branch`. Exit 75 means a usage limit or a refused lane. `--no-wait` returns once the agent has started.

Before preflight or any vendor runs, the launcher calls `~/.local/bin/plan-pick --lane-ok <vendor> --cloud` in the checkout. Exit 3 refuses with the reason, exit 75 and a suggestion to use `plan-pick --run`. A missing `plan-pick` warns and allows the launch. An installed but old or broken picker refuses; install token-ladder's `--lane-ok` support first.

Verify the PR diff and checks per pstack `principle-prove-it-works`.

## Traps

- Codex: each repo needs a cloud environment, created once at https://chatgpt.com/codex. Run `codex cloud list --json` and copy each repo's `environment_label` into the codex-envs map under the cloud-agent config folder (`{"owner/repo": "<label>"}`). The launcher names that path when the map is missing.
- Claude: the repo needs the Claude GitHub App, or the session cannot push.
