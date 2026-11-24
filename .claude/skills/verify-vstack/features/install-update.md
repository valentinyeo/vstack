# Install reaches a chat

`./install` is the only path a vstack change takes to a chat. It links the checkout's skills into every harness, links the hooks a chat calls, retires what the checkout no longer ships, and now records the commit it came from. A change that installs cleanly is a change a fresh chat can load.

## Sub-features

- `install-record` writes `~/.local/state/vstack/install.json` with the checkout root, its commit and the time.
- `skill-links` links every skill folder that has a `SKILL.md`, plus `hypertask-work`, into `.claude/skills`, and each link resolves.
- `bin-links` links `vps-state`, `repo-tidy`, `vstack-feedback` into `.local/bin`, and each link resolves.
- `drive-skill` leaves `valentin-mode/SKILL.md` readable through its link, because that is the skill Drive loads.
- `retire` removes links to skills and hooks the checkout no longer ships, and moves a real folder to the dupe store instead of deleting it.
- `user-hooks` registers `skill-update.py` (UserPromptSubmit) and `pr-cap-guard.py` (PreToolUse, Bash and MCP create) once each in `~/.claude/settings.json` through `run-hook`, via `scripts/register-user-hook.py`, so a chat in any project hears that valentin-mode changed and is refused above the PR cap; a re-run adds no second entry (VSTA-204, VSTA-207).

## How to get to it (user POV)

- Run `./install` from the shared checkout at `~/.local/share/vstack`.
- Start any new chat, in any project, on any harness.
- The chat reads its skills through the links that install just made.

## Driving it with verify-vstack

Preconditions:

- The checkout under test has an executable `install`.
- Launch already ran, so the scratch HOME holds its links, its hooks and its install record.

- **Install runs.** Read `install.txt` in the evidence folder. The recorded exit code is `0` and the last line names the checkout root.
- **The record names this tree.** Read `CHECK install` in `doctor.txt`. It passes when `install.json` names the same commit as the checkout's `HEAD`.
- **The skill tree is whole.** Read `CHECK skill-links` and `CHECK drive-skill`. Both pass only when every link resolves and `valentin-mode/SKILL.md` is readable through its link.
- **A chat loads it.** Run Drive. A `DRIVE PASS` line means one fresh chat started at this install, loaded `/valentin-mode` and ran a Bash command with no hook error.
- **Proof.** Keep `install.txt`, `launch.json`, `doctor.txt` and `verdict.txt`.

## Gotchas

- An install from a git worktree repoints every chat at an unmerged branch. Launch sets `VSTACK_INSTALL_ANYWHERE=1` inside the scratch HOME; never export it in the real one.
- The record is written by the checkout's own `install`. An older tree has no record, and `CHECK install` fails on purpose.
- `skill-dupes-<epoch>` folders under the scratch HOME are expected when a plain folder stood where a link goes.
