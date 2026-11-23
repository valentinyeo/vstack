---
name: cloud-agent
description: >-
  Send a coding brief to a vendor cloud agent (Cursor, Codex, Claude) instead of running it on this server, and get back the agent link and pull request. Use when starting a code worker, when the server is busy, when pstack asks for environment "cloud", or at /cloud-agent.
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
| `cursor` | Code workers, on Composer or Grok only | Included in our Cursor plan |
| `codex` | Code workers | ChatGPT plan allowance |
| `claude` | Claude-native jobs only, after `plan-pick --claude-helper` exits 0 | Claude plan allowance |

Code workers never run on Claude, per the pstack models rule. Never ask Valentin for a Cursor API key or a spend limit: the Cursor CLI login launches cloud agents.

## Run

Push the branch first. A cloud agent clones from GitHub and cannot see local files, so the brief carries everything the worker needs.

```sh
skills/cloud-agent/cloud-agent cursor --repo <checkout> --brief brief.txt
skills/cloud-agent/cloud-agent codex  --repo <checkout> --brief brief.txt --env <codex env>
```

Run it as a tracked background job. It prints one JSON line: `status`, `agent_url`, `pr_url`, `branch`. Exit 75 means a usage limit, so try the next vendor. `--no-wait` returns once the agent has started.

The result is a claim. Check the PR diff and its checks before calling the work done, as pstack's Prove It Works says.

## Traps

- Cursor: `cursor-agent -p "& ..."` runs locally. Only the interactive CLI hands off, after `&` is typed alone. The script does this.
- Codex: each repo needs a cloud environment, created once at https://chatgpt.com/codex. Run `codex cloud list --json` and copy each repo's `environment_label` into the codex-envs map under the cloud-agent config folder (`{"owner/repo": "<label>"}`). The launcher names that path when the map is missing.
- Cursor: the checkout's branch must exist on GitHub. Preflight runs `git push -u origin` when it does not; cursor-agent still sometimes shows a push dialog, which the launcher answers `y` on.
- Claude: the repo needs the Claude GitHub App, or the session cannot push.
