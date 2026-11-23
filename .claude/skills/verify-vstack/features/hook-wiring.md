# Hook wiring resolves

A chat runs a hook by the command string in its settings. When that string names a file that is not there, python exits 2 and Claude Code reads 2 as a block, so the chat stops on every prompt. PR #278 deleted three hooks that chats were still wired to (`plan-pick-only.py`, `claude-helper-gate.py`, `skill-update.py`) and that is the failure this feature exists to catch.

## Sub-features

- `settings` reads the scratch wiring and reports how many entries it holds and where they came from.
- `base-wiring` fails when the base commit's wiring registers a hook the checkout no longer ships.
- `wiring` fails when a registered command names a hook file the scratch HOME does not have.
- `hook-links` fails on a dangling link in `~/.claude/hooks`.
- `frontmatter` fails when a linked skill's own hook command names a file missing from that skill folder.
- `bin-links` and `skill-links` cover the other two link farms a chat follows.

## How to get to it (user POV)

- A chat loads its settings, then calls a hook on each prompt, tool call and stop.
- A hook that fails closed blocks the turn. A hook that fails open (`[ -f "$f" ] || exit 0`) silently stops running, so the rule it enforced disappears without an error.
- `./install` repairs the two settings files this repo owns. Every project sets up its own wiring, so the same registration lives on in each project's `.claude/settings.json`.

## Driving it with verify-vstack

Preconditions:

- Launch seeded the scratch settings from the live global wiring shape and from the base commit's `.claude/settings.json`, filtered to hooks this repo owns.
- The scratch HOME is the only HOME any of these checks read.

- **Base wiring survives.** Read `CHECK base-wiring`. It passes when every hook name wired at `--base` still ships in `hooks/`. On the #278 tree it names `claude-helper-gate.py`, `gh-watch-guard.py`, `plan-pick-only.py`, `skill-update.py`.
- **Every command resolves.** Read `CHECK wiring`. It lists each event and hook file that does not exist in the scratch HOME after install.
- **No dangling link.** Read `CHECK hook-links`. It names each link in `~/.claude/hooks` that points at nothing.
- **Skill hooks resolve.** Read `CHECK frontmatter`. It names each `$CLAUDE_PLUGIN_ROOT/...` target missing from a linked skill folder.
- **Proof.** Keep `doctor.txt` and the seeded `settings.json` that Launch wrote into the scratch HOME; copy it to the evidence folder before cleanup.

## Gotchas

- `install` retires names it knows. It cannot repair a project settings file it never reads, so a hook deleted here keeps its dead registration in every other project.
- A fail-open entry hides the problem from the user and from the chat. Treat a registered hook that silently stopped as a failure, not a non-event.
- The scratch wiring is filtered to hooks this repo owns. A personal hook in the real settings is not seeded, and must not be reported as a wiring failure.
