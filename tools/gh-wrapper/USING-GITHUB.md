# Using GitHub

One GitHub account serves every chat. 5000 REST and 5000 GraphQL calls an hour, shared by all.

1. Prefer `gh api` REST over `gh pr view/list/checks`: those four are GraphQL and hit the shared pool.
2. Read a PR once, not every tick. A `pr` read is cached for 60 seconds, a REST GET for 5 minutes.
3. Never poll faster than once a minute. Never watch for more than 30 minutes.
4. Wait for CI with `tools/gh-wrapper/wait-checks <repo> <pr>` in the background: one cached call a minute, exit 0 pass, 1 fail.
5. Merge with `gh api -X PUT repos/O/R/pulls/N/merge -f merge_method=squash`.
6. Check your own use with `gh budget`: your count, the busiest sessions, and live rate-limit headroom.
7. At 300 calls in an hour a warn line names you. At 600 reads are refused with exit 75 until the hour turns.
