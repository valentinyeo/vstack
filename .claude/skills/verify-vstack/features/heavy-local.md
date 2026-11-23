# Heavy jobs stay off this host

`hooks/heavy-local-guard.py` refuses heavy local jobs before Bash starts them. Each chat registers its own hook using the setup in `skills/test-timeout/SKILL.md`.

## Sub-features

- `block` refuses Gradle, Zig build/test and Wine, including timeout wrappers.
- `allow` passes light tests, git, grep and GitHub workflow commands.
- `wiring` drives the registered command through installed symlinks in a temporary HOME.
- `rule` keeps the per-chat setup in test-timeout discoverable.

## How to get to it (user POV)

Register the hook in your project's `.claude/settings.json`, following `skills/test-timeout/SKILL.md#heavy-work-stays-on-github`. A heavy Bash command is refused with the GitHub workflow route. No central process killer is needed.

## Driving it with verify-vstack

Run this focused journey from the checkout under test:

```sh
timeout 600 nice -n 19 env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_heavy_local_guard.py -v
```

The wiring journey reads this checkout's actual Bash registration, copies the two guard files into a temporary checkout, links them into a temporary HOME, and feeds the registered shell command real PreToolUse JSON. It requires exit 2 for heavy commands, exit 0 for light commands, and checks missing-link behavior. It never executes a heavy command or runs `install`.

Expected evidence includes:

```
PASS heavy-local: installed hook blocks heavy jobs; light commands and missing links pass
```

## Gotchas

- A missing hook link fails open so Bash stays usable. Report it; enforcement is absent until repaired.
- Test payloads only. Never launch a heavy job to prove a block.
- `timeout` limits light tests; it does not permit heavy jobs locally.
- Scripts, aliases and generated commands are not expanded. The rule still applies.
