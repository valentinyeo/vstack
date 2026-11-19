VERDICT: PASS

## What I verified
PR body states no `## Done when`, so I judged against the title ("read a verdict boxed alone in a fence as the fallback answer") and the `## Why` bug report, and reproduced that bug on the base.

- Base `4b50954`, head `014d895`; diff touches exactly 3 files (`scripts/verdict.py`, `tests/test_verdict.py`, `tests/fixtures/verdict/pr-134-glm-boxed-verdict.md`), all read in full.
- Base reproduces the reported failure: the real glm fixture and a workflow-shaped answer (`"Verdict below."` + fence holding only `PASS`) both read `(None, 'no verdict found…')` on base. Head reads `PASS` for both, exit 0. `boxed(fixture)` returns exactly one hit `(161, 'PASS')`; `occurrences(fixture)` is empty, so the PASS comes from the new fallback, not from a stray token.
- No masking of a real answer: `FAIL` bare outside fences beats a boxed `PASS`; `{"verdict": "FAIL"}` beats a boxed `PASS`; `VERDICT: FAIL` beats a boxed `PASS`; last of two boxed verdicts wins; a fence quoting a verdict beside other lines stays evidence.

## Commands run
- `python3 -m unittest tests.test_verdict -v` — 13 tests, OK
- `python3 scripts/verdict.py --self-test` — 13 tests, OK, exit 0 (the only touched tool with a self-test)
- `python3 -m unittest tests.test_column_verifier tests.test_pstack_sources tests.test_advisor_verdict` (the tests covering the consumers `column-verifier.py`, `pstack-sources.yml`, `verification/advisor.py`) — 15 tests, OK
- `python3 -m unittest discover -s tests` — head 171 tests OK; base worktree 169 tests OK (delta is the 2 new tests; head count differs from the author's 178 only by environment)
- `python3 -m unittest discover -s tests -p test_verdict.py` (CI step shape) — OK; `python3 -m py_compile` on both touched Python files — ok
- CLI probes: fixture, PR-129 fixture, stdin, empty stdin (exit 1 + `no verdict found`), `-` plus no args (exit 2), `--nope` (exit 2), boxed `FAIL` (exit 1), two files (last-wins), malformed JSON, missing file/directory
- Fixture matrix of 24 inputs run through both base and head `find_verdict` to see every behavior change
- Workflow-shaped replay of the `pstack-sources.yml` snippet writing `verdict.value`, then `python3 scripts/verdict.py verdict.value` → `PASS`, exit 0
- `git status --porcelain` after testing: only the pre-existing untracked `picker-base/`; no tracked file edited, worktree removed

## Break attempts (all survived)
Empty/whitespace input, tilde and 4-space-indented fences, CRLF, blank lines inside the fence, unclosed fence (still none — base same), bolded/PASSING/"The verdict:" inside a fence (still evidence), one-line ```` ```PASS``` ````, nested 4-backtick fences, prefixed verdict inside a fence, malformed JSON, two wired files.

## Notes (not blockers)
- Disclosed tradeoff, confirmed: an answer with no verdict outside fences that merely quotes a lone verdict in a fence (e.g. a format template showing `PASS`) now reads that token where base read none. Fail-open in the PASS direction. It is stated in `## Tradeoffs`, the only existing test it changes is updated with a comment, and the fallback is narrow (fence must hold exactly one non-empty line).
- An unclosed fence whose body is a bare verdict still reads none; base behaves the same, so not head-introduced.
- The new `find_verdict` docstring repeats the module docstring and pins a run-specific sha (`8507974`); accurate today, will age. Not misleading.
- Fixture provenance ("the real glm answer") cannot be checked here: no artifact or board credentials. The fixture is consistent with the described run and is the failing input on base.
- Pre-existing, unchanged: a missing path or a directory argument raises a traceback rather than a clean message (`read_source` untouched by this PR).
