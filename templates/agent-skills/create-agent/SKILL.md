---
name: create-agent
description: Provision a new skills-driven agent identity for this repo — a wrapper script, a mission that points it at INDEX.md, and (for dev/qa) a systemd unit that triggers it. Use when a project needs another agent identity: a second worker, a QA-only identity, or a plain CLI identity for logs and commits.
---

# create-agent

Provisions one agent identity so it reads `INDEX.md` before doing anything,
instead of carrying every rule in one long prompt. Works for any repo; has
no dependency on a specific issue tracker or chat surface.

## Steps

1. **Gather three answers.** Name, kind (`dev` ships changes, `qa` verifies
   only and never fixes, `cli` is an env-only identity with no chat and no
   worker), and the repo path the worker's commands run in. Provider
   defaults to whatever CLI is installed (`claude`, `cursor-agent`, or
   `codex`) — only ask if it's ambiguous.
2. **Run the script in dry-run first.** `scripts/create-agent.sh --name
   "<Name>" --kind dev|qa|cli --repo <path> [--provider claude|cursor|codex]
   [--skills-repo <path with INDEX.md>]`. Dry-run is the default: it prints
   every command it would run and creates nothing. Read the plan before
   moving on.
3. **Re-run with `--yes`** once the plan looks right. This writes the
   mission, the env file (0600), the state directory, and — for `dev`/`qa`
   — a wrapper script (`<slug> run "<task>"`) plus a generic oneshot
   systemd unit scoped to the repo.
4. **Chat test, done through the script.** For `dev`/`qa` it sends the
   mission plus a one-line hello to the provider CLI non-interactively and
   prints the reply back. Quote that reply in the hand-off — a `cli`
   identity has no chat test; say so instead of skipping the step silently.
5. **Last step: report or hand off.** State the slug, where its files live,
   and (if applicable) the exact reply the chat test returned.

## Check before hand-off

- [ ] The mission names the skills index by its literal absolute path, not `~`
- [ ] Env/conf files for the new identity are 0600
- [ ] `dev`/`qa` identities passed the chat test — the reply is quoted, not assumed
- [ ] `cli` identities are labeled as such (name suffix `" CLI"`) and no chat test is claimed for them
- [ ] Nothing board-specific (issue tracker identity, webhook, ports) was invented — that belongs in a project-specific extension of this script, not here

## Reference

This is the board-agnostic core. A project wired to a specific board or
issue tracker (identity creation, webhook, ports, a chat acceptance test
against that tracker's own UI) extends `scripts/create-agent.sh` with its
own block behind a flag (for example `--board <name>`), gated the same way
the base script gates real writes: dry-run by default, an explicit `--yes`
required, and a hard stop in front of any call that creates a real
identity.
