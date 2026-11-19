VERDICT: PASS+NOTES

**Faults (no service credentials; file per worker-brief):** none that block.

**Required commands** (run from `/home/runner/work/vstack/vstack/change`):
1. `python3 -m unittest discover -s ../lint-source/tests -p test_skill_lint.py -v` → **26 tests OK** (includes `test_real_past_2261_word_mistake_fails` and `test_current_snapshot_has_no_budget_finding`).
2. `python3 ../lint-source/scripts/skill-lint --base 4b50954... --pstack ../pstack-source/pstack/skills --house-rules ../catalog/house-rules.md --catalog ../catalog/skills` → `skill-lint: PASS (0 skills, 0 findings)`, exit 0. Correct: the PR diff (`git diff 4b50954..HEAD`) touches only `skills/hypertask-work/reconcile`, `reconcile.md` and `tests/test_hypertask_work.py` — no `SKILL.md`, so 0 changed skills. `reconcile.md` grew, but it is a supporting doc, not a `SKILL.md`, and the growth gate is file-specific, not whole-skill-tree.

**Break attempts** (throwaway git repo at /tmp/break, absolute paths, real CLI):
- **Growth metadata:** skill grown 12→416 words, no PR-body line → `grew from 12 to 416 words (>20%); add a PR body line ...` and exit 1. With `--pr-body-file` carrying a file-specific `Skill growth:` line, the growth finding clears while the copy finding for a second skill stays — the line waives only growth, as documented.
- **Copied text:** three verbatim house-rules sentences → repeated `link to .../house-rules.md:3/:5/:7 instead of restating`, exit 1.
- **Missing references/prior art:** backticked `docs/no-such-file.md` → `missing reference docs/no-such-file.md`; new skills without a `Prior art:` line → prior-art finding. All caught.
- **Bounds probe:** `--base 4b50954...` in a repo not containing it fails cleanly ("fix the inputs and rerun"), not silently.
- **Historical regression:** fixture `valentin-mode-old.md` → exit 1 with the exact `2261 words exceed budget 800` finding; `valentin-mode-current.md` → PASS, 0 findings. Both match docs/skill-lint.md; the old snapshot's missing `/i-have-adhd` and `~/.local/share/...` references are documented legacy findings, not new.

**Notes (unchanged lint-source behavior, not regressions from this change):**
- The reference check resolves backticked `/pstack:<name>` but not the prose form `/pstack:skill no-such-skill` or `/skill <name>` written outside backticks (verified: such a line yields no finding). docs/skill-lint.md says those calls "must resolve" — minor doc/script gap to file on the worker-repo board.
- Finding lines for the copy detector all report the copied block's source line while repeating the skill line number (e.g. `:5` seven times) — cosmetic.
- Change's own focused tests: `python3 -m unittest tests.test_hypertask_work` → 104 OK (not a full suite). The reconcile change itself (rate-limit clean stop, batched GraphQL) matches the doc and carries no comment/skill growth issues; house-rules and skill-lint script pin to the base commit 4b50954 and are byte-identical across lint-source and catalog.
