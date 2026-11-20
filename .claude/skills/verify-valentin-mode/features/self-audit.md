# Self-audit removes a planted extra gate

A chat that loads valentin mode audits its own repo against pstack and deletes a verification gate pstack does not ask for.

## Sub-features

- `self-audit.extra`: pstack-diff exits 1 on the sample repo's `scorecard` job.
- `self-audit.remove`: after the chat's change, the job is gone and pstack-diff exits 0.
- `self-audit.no-house-line`: the chat does not keep the job by adding a house-file line.

## How to get to it (user POV)

- Copy the fixture to a scratch folder and ask a fresh chat to `/valentin-mode` to make the repo match pstack verification.

## Driving it with run

Preconditions: vstack is installed, so `~/.claude/skills/pstack-diff/pstack-diff` exists.

- Setup: copy `fixtures/extra-gate/` to `/tmp/vvm-self-audit`, `git init`, then commit once.
- Before: `~/.claude/skills/pstack-diff/pstack-diff /tmp/vvm-self-audit` exits 1 with `EXTRA workflow: .github/workflows/ci.yml job scorecard`.
- Action: start a chat with `/valentin-mode` and the prompt "Make this repo match pstack verification." It names no tool.
- After: the chat removes the `scorecard` job and the same command exits 0. A `BASE` or `EXTRA` line that still names the job fails the check.

## Gotchas

- Without an `origin` remote the `gh pr create` guard has no base. Grade the scratch folder with the plain `pstack-diff` command, not `--base`.
- Keeping the job with a `.pstack-house.txt` line fails `self-audit.no-house-line`: a sample repo has no reason to allow it.
- The fixture has a `verify-app` skill with a feature map on purpose, so its only finding is the planted gate.
