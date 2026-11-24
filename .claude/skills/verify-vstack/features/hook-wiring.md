# Hook wiring resolves

A chat runs a hook by the command string in its settings. When that string names a file that is not there, python exits 2 and Claude Code reads 2 as a block, so the chat stops on every prompt. PR #278 deleted three hooks that chats were still wired to (`plan-pick-only.py`, `claude-helper-gate.py`, `skill-update.py`) and that is the failure this feature exists to catch.

## Sub-features

- `settings` reads the scratch wiring and reports how many entries it holds and where they came from.
- `base-wiring` fails when the base commit's wiring registers a hook the checkout no longer ships.
- `wiring` runs `scripts/check-hook-paths` against the scratch HOME and project settings, checking both launcher and script operands.
- `run-hook` logs a missing or non-executable script and exits 0, without changing an existing hook's intentional block.
- `hook-links` fails on a dangling link in `~/.claude/hooks`.
- `frontmatter` fails when a linked skill's own hook command names a file missing from that skill folder.
- `bin-links` and `skill-links` cover the other two link farms a chat follows.

## How to get to it (user POV)

- A chat loads its settings, then calls a hook on each prompt, tool call and stop.
- An existing hook can intentionally block the turn. A missing hook lets the prompt through, writes one stderr warning, and appends it to `~/.local/state/vstack/hook-missing.log`. Fleet-report shows the missing registration and its fix.
- `./install` repairs the two settings files this repo owns, and registers `skill-update.py` globally so every chat, whatever its cwd, hears that valentin-mode changed. Every project sets up its own wiring, so the same registration lives on in each project's `.claude/settings.json`.
- VSTA-207: `skill-update.py` was registered only in this repo's `.claude/settings.json`, so only a chat whose cwd was vstack was told; a chat in `~/projects/multiprompt` missed a change for six hours. The global entry is now the only one.

## Driving it with verify-vstack

Preconditions:

- Launch seeded the scratch settings from the live global wiring shape and from the base commit's `.claude/settings.json`, filtered to hooks this repo owns.
- The scratch HOME is the only HOME any of these checks read.

- **Base wiring survives.** Read `CHECK base-wiring`. It passes when every hook name wired at `--base` still ships in `hooks/`. On the #278 tree it names `claude-helper-gate.py`, `gh-watch-guard.py`, `plan-pick-only.py`, `skill-update.py`.
- **Every command resolves.** Read `CHECK wiring`. It lists each event and hook file that does not exist in the scratch HOME after install.
- **No dangling link.** Read `CHECK hook-links`. It names each link in `~/.claude/hooks` that points at nothing.
- **Skill hooks resolve.** Read `CHECK frontmatter`. It names each `$CLAUDE_PLUGIN_ROOT/...` target missing from a linked skill folder.
- **Missing script still accepts the prompt.** Run `timeout 90 python3 -m unittest discover -s tests -p test_hook_paths.py -v`. This invokes the installed skill hook after deleting its script, checks exit 0 and the warning log, and proves an executable hook still blocks at 2 with stdin, arguments and output intact.
- **Deletion cannot ship.** Run `python3 scripts/check-hook-paths --repo .`. Then run `timeout 60 python3 -m unittest discover -s tests -p test_hook_wiring.py -v`; it deletes `skill-update.py` in a scratch copy and requires the same CI command to fail with both the file and its registration in `install`.
- **Fleet visibility.** Run `timeout 60 python3 -m unittest discover -s tests -p test_fleet_report.py`. Its missing-hook fixture must appear in both text and HTML reports, without changing settings or inspecting inne.
- **Proof.** Keep `doctor.txt` and the seeded `settings.json` that Launch wrote into the scratch HOME; copy it to the evidence folder before cleanup.

## Gotchas

- `install` retires names it knows. It cannot repair a project settings file it never reads, so a hook deleted here keeps its dead registration in every other project.
- Fail-open keeps the prompt usable; it does not make the missing rule safe to ignore. The path check must still fail and the fleet report must show it.
- The scratch wiring is filtered to hooks this repo owns. A personal hook in the real settings is not seeded, and must not be reported as a wiring failure.
