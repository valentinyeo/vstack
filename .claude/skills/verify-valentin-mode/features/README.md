# Valentin mode verification map

The three tools valentin mode names, each proved by one check in `grade.py`, plus the hooks it turns on. Read this, then the file for the check.

## Baseline preconditions

- `~/.local/share/vstack` holds the valentin-mode under test, installed with `./install`.
- No hook pushes valentin mode in. The prompt asks the chat to invoke it.
- Test login "VVM Test Agent" and scratch ticket SOFT-2849 (label `vvm-test`) exist on board 2060.
- `plan-pick --claude-helper` exits 0.
- `run` saves Claude Code's debug log as `debug.log`. Each hook run appears there
  as a `Hooks: <Event>[:<matcher>] [<command>]` line, and `checks loaded` matches
  each command in the skill's frontmatter against one. The transcript records
  nothing, so a hook that prints nothing leaves no entry, and a command left as
  `/../responsive-mode/...` by an unset `$CLAUDE_PLUGIN_ROOT` counts as no run.
  A missing debug.log fails it.

## Driving conventions

- Only `run` starts a chat. One run at a time.
- The prompt names valentin mode, never a tool. A chat that uses the tools learned them from valentin mode.

## Proof and skip reporting

- Each check reads a side effect: the pacer log, the board's author fields, the reconcile results, the file on disk.
- Report a check that could not run (no init line, gate closed) as not run, never as PASS.

## Features

| File | Check | Tool |
| --- | --- | --- |
| [login.md](login.md) | `login` | Board rules: own login, never Valentin's |
| [pacer.md](pacer.md) | `pacer`, `task` | Subscription pacer: workers through `plan-pick --run` |
| [board-sync.md](board-sync.md) | `board sync` | Board sync: reconcile dry run, then `--apply --limit 5` |
| [SKILL.md](../SKILL.md) | `checks loaded` | Hooks: both hooks the frontmatter declares ran |
