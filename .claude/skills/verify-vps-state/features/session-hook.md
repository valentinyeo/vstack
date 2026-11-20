# Session hook

The one line every session sees as it opens, so nobody has to remember to ask.

## Sub-features

- `hook`: `hooks/vps-state-hook` exits 0, prints exactly two lines, `Server: <the brief line>` and the hint `run vps-state before starting chats or workers`, in under three seconds.
- `brief`: `vps-state --brief` prints one line, and it is the same verdict line the human block leads with.
- `speed`: the slowest of the JSON, brief and human runs stays under five seconds, because a session must be able to ask before it starts anything.
- Silent failure: with no script to run, the hook prints nothing and still exits 0. A session must never fail to start over a capacity probe.

## How to get to it (user POV)

- Open a session and read the first line: `Server: HOLD worker, CAREFUL chat: load5 1.9x cores`.
- Run `vps-state` for the block, or `vps-state --brief` for the same one line.

## Driving it with run

- Action: `run` executes the hook with its own HOME and a PATH without vps-state, so the installed link cannot hide a broken repo copy. It saves `hook.out` and `hook.code`.
- Check: two lines, the `Server: ` prefix, exit 0, under three seconds.
- The unit test `SessionHook` also covers the silent missing-script case, and asserts the hook's wall clock from the outside.

## Gotchas

- The hook finds its script through `$VPS_STATE_BIN`, then `~/.local/bin/vps-state`, then the checkout next to it. The installed symlink under `~/.claude/hooks` resolves back here, so a repo copy works before `install` runs.
- Each chat registers the SessionStart hook in its own project's `.claude/settings.json`, with the JSON in `skills/vps-state/SKILL.md`. Nobody registers it centrally. This repo only ships and links the file; without a registration no session sees the line.
- The hook runs `--brief`, which skips the worktree and /tmp scans. Sharing that scan would blow the three second budget on a busy host.
