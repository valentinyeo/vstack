---
name: pstack-diff
description: >-
  Read-only diff between a checkout and pstack's verification recipe. Run on chat load;
  remove EXTRA lines in a PR until exit 0.
---

# pstack-diff

Prior art: pstack `create-verification-skill/SKILL.md`, `maintain-verification-skill/SKILL.md`, and `poteto-mode/playbooks/shipping.md` step 1 define the recipe. This skill adds a stdlib check those files describe but do not ship.

Each chat that loads this skill runs `skills/pstack-diff/pstack-diff` from the project root once per session (or after verification-touching edits). Exit 0 means the repo matches pstack aside from house deviations. Exit 1 lists `GAP` or `EXTRA` lines — fix them in a PR, not by silencing the tool.

House deviation already baked in: the step-1 verifier may be a GitHub Actions job (vstack's shared verifier workflow) instead of a Cursor cloud agent. Everything else should match pstack.

## Run

```bash
python3 skills/pstack-diff/pstack-diff
python3 skills/pstack-diff/pstack-diff --json
```

`--json` prints `{exit, asked, gaps, extras, lines}` for scripts.

## What to do with output

- **ASKED** — expected; no action.
- **GAP** — missing required verification piece (usually no verify skill with a feature map).
- **EXTRA** — duplicate verifier, non-pstack gate, or local rules that restate verdicts; delete or link to pstack instead.

Land one PR that clears every GAP and EXTRA line for this repo. Re-run until exit 0.