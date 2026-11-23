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

`--base REF` fails only on EXTRA lines this branch adds; extras already in the merge base print `BASE`. The `checks` workflow and `hooks/pstack-new-gates.py` run it.

By default the newest installed pstack is the reference. Set `PSTACK_DIFF_PSTACK` or pass `--pstack DIR` to use another install; the flag wins. Tests set it to a fixture, so they never read a home directory.

## What to do with output

- **ASKED** — expected; no action.
- **GAP** — missing required verification piece (usually no verify skill with a feature map).
- **EXTRA** — duplicate verifier, non-pstack gate, or local rules that restate verdicts; delete or link to pstack instead.

`GAP uncovered pass gate` means the verifier plans journeys from a changed-file selection, so it
can PASS while files it could not map went unexercised. Fix: its verdict goes through
`uncovered_gate` (`scripts/uncovered_gate.py` in vstack; `scripts/verdict.py` already runs it),
which turns PASS and PASS+NOTES into FAIL and names the files.

Land one PR that clears every GAP and EXTRA line for this repo. Re-run until exit 0.