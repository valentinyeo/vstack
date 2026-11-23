---
name: verify-vstack
description: >-
  Prove that a vstack change keeps every chat working: install the checkout into a scratch HOME, run Doctor over its hook wiring, skill links and install record, then start one fresh headless chat that loads /valentin-mode and runs a Bash command. Fails when a chat is wired to a hook the change stopped shipping. Use on any change to hooks/, install, a skill's frontmatter hooks or settings, and as the proof on such a PR.
skill-word-budget: 800
skill-word-budget-reason: Launch, Doctor, Drive, the evidence table and the base-wiring rule each need their own line; the feature map holds the rest.
---

# Verify vstack

Prior art: pstack `create-verification-skill`, `maintain-verification-skill` and `poteto-mode/playbooks/shipping.md` step 1. They say how to build a check, but none covers a change whose user is every chat on a shared server. This is the skill they ask for, with the install and its hook wiring as the app.

PR #278 deleted three hooks chats were still wired to and killed sessions. This skill exists so that cannot merge again.

Read `features/README.md` for the map: one journey per tool, and each tool's own `run` under `tools/<tool>/`. `.claude/skills/verify-reconcile-formal/` is the one formal check pstack allows beside this skill.

## Launch

```sh
.claude/skills/verify-vstack/run                      # this checkout, base origin/main
.claude/skills/verify-vstack/run --checkout DIR --base REF
.claude/skills/verify-vstack/run --wiring FILE        # stand-in for the live global settings
```

`run` does, in order:

1. Makes a scratch HOME in `/tmp/vstack-verify-home.*` with its own `.claude` and `~/.local/bin`, and evidence in `~/.local/state/verify-vstack/<run-id>/`.
2. Seeds its `~/.claude/settings.json` with a chat's hook wiring, filtered to hooks this repo owns: the live global settings plus `REF:.claude/settings.json`. Hook entries only, no token or permission.
3. Runs the checkout's `install` into that HOME, then Doctor, Drive and grade.

Launch never writes the real `~/.claude`, `~/.local/bin` or `~/.local/share/vstack`. Never run the real install from a worktree.

## Doctor

Read the doctor output: one `CHECK <name> PASS|FAIL <detail>` line per check, then `DOCTOR PASS|FAIL`.
| Check | Passes when |
| --- | --- |
| `settings` | the scratch wiring parses, and the line names its entry count |
| `base-wiring` | every hook the base commit's wiring registers still ships in `hooks/` |
| `wiring` | every registered command names a file that exists in the scratch HOME |
| `hook-links`, `skill-links`, `bin-links` | every link a chat follows resolves |
| `drive-skill` | `valentin-mode/SKILL.md` is readable through its link |
| `install` | the install record names the checkout's commit |
| `frontmatter` | every `$CLAUDE_PLUGIN_ROOT` hook in a linked skill's frontmatter exists |

`base-wiring` catches the incident: `install` repairs the two settings files this repo owns, and every project sets up its own, so a deleted hook keeps a dead registration elsewhere. [hook-wiring.md](features/hook-wiring.md).

## Drive

Drive starts one fresh headless chat in a scratch copy of the checkout at `HEAD`, prompts `/valentin-mode` plus one Bash command, and reads the harness debug log, never the chat's words. It passes when the chat exits 0, the command's file exists, and no hook line reports a non-zero status.

Drive needs Claude credentials and one Sonnet chat's pace. Launch copies no tokens, so it runs only with `ANTHROPIC_API_KEY` set and `~/.local/bin/plan-pick --claude-helper` at exit 0. Otherwise it writes `DRIVE SKIP <reason>` and Doctor alone is the merge gate. A skip is never a pass.

## Evidence

Every run keeps `~/.local/state/verify-vstack/<run-id>/`:

| File | What it proves |
| --- | --- |
| install.txt | the install command, its output and its exit code |
| launch.json | checkout, commit, base commit, seed source, install exit |
| doctor.txt | one line per check |
| stream.jsonl, debug.log, drive.txt | the chat, its hook lines, its version line |
| verdict.txt, verdict.json | one line per check, then the verdict |

Grading reads the harness, never a chat's claim. Attach the verdict file to a PR, not the raw stream.

## Cleanup

`run` removes only its own `/tmp/vstack-verify-home.*` tree, never the evidence. `--keep` keeps the scratch HOME.

## Helpers

`launch.py`, `doctor.py`, `drive.py`, `grade.py` and `run` sit beside this file and are executable. `grade.py <run-dir>` regrades a saved run without a new chat. Each tool's `run`, `grade.py` and helpers sit under `tools/<tool>/`.

## When it runs

CI runs Doctor, never Drive, on a PR that touches `hooks/`, `install`, a `SKILL.md` frontmatter hook block or a settings file: one free GitHub runner, no AI call. The PR owner runs the full `run` here before merging.

## Gotchas

- A fail-open entry (`[ -f "$f" ] || exit 0`) for a missing hook loses the rule silently. That is a wiring failure.
- `hypertask-work` is linked without a `SKILL.md` on purpose.
- A FAIL on `base-wiring` is a finding about the change, not a broken check.
