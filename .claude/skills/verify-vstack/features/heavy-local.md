# Heavy jobs stay off this host

`hooks/heavy-local-guard.py` refuses heavy local jobs before Bash starts them, and the same
refusal stands in front of every pacer worker's PATH. Each chat registers its own hook using
the setup in `skills/test-timeout/SKILL.md`.

## Sub-features

- `block` refuses Gradle, Zig build/test, Wine and `xvfb-run`, the Windows desktop app, package-manager `test` and `build`, `pytest`, `cargo` and `go` builds and tests, and a full-suite `python3 -m unittest discover`, including under `timeout`.
- `allow` passes only the lines listed in `config/heavy-local-allow.txt`: a syntax check, `--help` or `--version`, and one named test file (`tests.test_<one>`, `discover ... -p <one file with no wildcard>`, or one pytest `.py` file) under `timeout` of 90s or less. Every line carries its reason.
- `shims` writes one shim per blocked command with `scripts/worker-shims`, generated from the same `config/heavy-local.json`, so an OpenCode or Antigravity worker gets the same message and exit 2. A light command execs the real binary; a runner this host lacks says so and exits 127.
- `wiring` drives the registered command through installed symlinks in a temporary HOME.
- `rule` keeps the per-chat setup in test-timeout discoverable.

## How to get to it (user POV)

Register the hook in your project's `.claude/settings.json`, following `skills/test-timeout/SKILL.md#heavy-work-stays-on-github`. A heavy Bash command is refused with the GitHub workflow route. A pacer worker reads the same refusal from the worker shims folder that `./install` regenerates from the same config. No central process killer is needed.

## Driving it with verify-vstack

Run these focused journeys from the checkout under test:

```sh
timeout 60 python3 -m unittest tests.test_heavy_local_guard -v
timeout 60 python3 -m unittest tests.test_worker_shims -v
```

The wiring journey reads this checkout's actual Bash registration, runs `install` into a temporary HOME, and feeds the registered shell command real PreToolUse JSON. It requires exit 2 for heavy commands and exit 0 for light commands. Removing the hook link must still exit 0, with one warning on stderr and in the missing-hook log. It never executes a heavy command or installs into the real HOME.

The shim journey generates the shims into a temporary folder with fake `gradle`, `zig` and `npm` binaries, then requires the shim's refusal to be byte-identical to the hook's for the same command, and a refused command never starts the real binary. It never puts a shim on this host's PATH.

Expected evidence includes:

```
PASS heavy-local: installed hook blocks heavy jobs; light commands and missing links pass
```

## Gotchas

- A missing hook link, or a missing `config/heavy-local.json`, fails open so Bash stays usable. Report it; enforcement is absent until repaired.
- Test payloads only. Never launch a heavy job to prove a block.
- A shim sees only its own words (never a wrapping `timeout`), so the `timeout` <= 90s exception for one named test file reaches a chat and not a worker. A worker pushes and reads CI.
- `timeout` no longer buys a heavy job here.
- Scripts, aliases and generated commands are not expanded. The rule still applies.
