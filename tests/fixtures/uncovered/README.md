# Uncovered pass gate fixtures

`pr-1205/` is multiprompt pull request 1205 at head 644279e, the change that broke about 20
chats on restart after the verifier said `PASS+NOTES`.

- `selection.json` is the artifact `pr-verifier-selection` from
  https://github.com/valentinyeo/multiprompt/actions/runs/45077114873, byte for byte.
- `comment.md` is the verdict comment that run posted on the pull request, byte for byte.
- `answer.md` is the same evidence with the verdict written as the judge's own answer line
  (`PASS+NOTES`) instead of the comment's `pstack-verifier: PASS+NOTES @ <sha>` header,
  which is how scripts/verdict.py reads a verifier answer.

`covered/` is the same change planned correctly: a `sessions` journey is selected, and only
the changelog and ticket-title files stay unmapped.
