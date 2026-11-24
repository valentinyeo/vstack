---
name: pstack-diff
description: >-
  Read-only diff between a checkout and pstack's verification recipe. Run on chat load;
  remove EXTRA lines in a PR until exit 0.
---

# pstack-diff

Prior art: pstack `create-verification-skill/SKILL.md`, `maintain-verification-skill/SKILL.md`, and `poteto-mode/playbooks/shipping.md` step 1 define the recipe. This skill adds a stdlib check those files describe but do not ship.

Each chat that loads this skill runs `skills/pstack-diff/pstack-diff` from the project root once per session (or after verification-touching edits). Exit 0 means the repo matches pstack aside from house deviations. Exit 1 lists `GAP` or `EXTRA` lines — fix them in a PR, not by silencing the tool.

House deviations live in `skills/pstack-diff/house.txt` (one stanza per house change: `id`, optional `gate: <file>:<job>` or `verify-skill:<name>`, `pstack`, verbatim `quote`, one-line `change`, evidence-backed `impossible`, explicit `scope`, `basis`, `approved`, `expiry`); repos may also add a root `.pstack-house.txt` file (stanza or `<file>:<job> <reason>`). Listed gates print `HOUSE` and do not fail the run. The vstack-only Actions exception changes the verifier's machine, not its job. It counts only when an independent agent drives the changed behavior parent against head per shipping step 1.

`scope` lists `board:<id|*>`, `repo:<owner/name|*>`, or `skill:<name|*>`, separated by `; `. Values within a kind are alternatives; specified kinds all constrain the exception. `tests/test_house_list.py` requires both new fields and exercises every house-tagged reconcile stage on configured and runtime boards, including the historical board-13734 leak. A feasible but larger removal must say `Not impossible`, expire in 14 days, and name its follow-up in the audit.

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