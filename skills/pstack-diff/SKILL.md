---
name: pstack-diff
description: >-
  Read-only diff between a checkout and pstack's verification recipe. Run on chat load;
  remove EXTRA lines in a PR until exit 0.
---

# pstack-diff

Prior art: pstack `create-verification-skill/SKILL.md`, `maintain-verification-skill/SKILL.md`, and `poteto-mode/playbooks/shipping.md` step 1 define the recipe. This skill adds a stdlib check those files describe but do not ship.

Each chat that loads this skill runs `skills/pstack-diff/pstack-diff` from the project root once per session (or after verification-touching edits). Exit 0 means the repo matches pstack aside from house deviations. Exit 1 lists `GAP` or `EXTRA` lines — fix them in a PR, not by silencing the tool.

House deviations live in `skills/pstack-diff/house.txt`; repos may add a root dot-pstack-house file. Listed gates print `HOUSE` and do not fail the run. The step-1 verifier may be a GitHub Actions job instead of a Cursor cloud agent.

## Run

```bash
python3 skills/pstack-diff/pstack-diff
python3 skills/pstack-diff/pstack-diff --json
python3 skills/pstack-diff/pstack-diff --base origin/main
```

`--json` prints `{exit, asked, gaps, extras, base_extras, lines}` for scripts.

`--base REF` compares the tree against the merge base of REF and HEAD. An EXTRA line that base already has prints as `BASE` and does not fail the run. Only an EXTRA line this branch adds exits 1, so an old extra never blocks an unrelated PR. The `checks` workflow runs it against the PR base, and `hooks/pstack-new-gates.py` runs it on `gh pr create` when the branch touches a workflow or a verify skill.

By default the newest installed pstack is the reference. Set `PSTACK_DIFF_PSTACK` or pass `--pstack DIR` to use another install; the flag wins. Tests set it to a fixture, so they never read a home directory.

## What to do with output

- **ASKED** — expected; no action.
- **GAP** — missing required verification piece (usually no verify skill with a feature map).
- **EXTRA** — duplicate verifier, non-pstack gate, or local rules that restate verdicts; delete or link to pstack instead.

Land one PR that clears every GAP and EXTRA line for this repo. Re-run until exit 0.