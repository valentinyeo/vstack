# vstack

pstack owns workflow rules.
vstack holds shared skills and checks.
Product repos hold their own facts.

## Rules and the checks that enforce them

Changes land through pull requests.
Every hook runs in `advisor-checks` on GitHub.
A separate model family verifies before merge.
Its verdict is PASS, PASS+NOTES or FAIL.
Nobody pushes to main.

| Rule | Enforced by |
|---|---|
| Worker briefs name pstack and the worker kickoff | `hooks/pstack-source.py` |
| PRs name a real pstack source | `hooks/pstack-source.py` |
| Briefs and PRs walk every book item | `hooks/book-check.py` |
| Advice replies name their pstack source | `hooks/pstack-reply.py` |
| Promised work starts in that turn | `hooks/said-started.py` |
| Advisors respect configured project boundaries | `hooks/out-of-bounds.py` |
| Billing failures go once on the ticket | `hooks/billing-quiet.py` |
| Every hook passes its self-test on GitHub | `advisor-checks` workflow on PRs |
| A separate verifier posts a verdict before merge | Review procedure; branch protection is not configured here |
