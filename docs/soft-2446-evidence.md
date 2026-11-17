# Board 2060 caller migration

Prepare callers before renaming live columns.
Keep old aliases until the follow-up PR.
No columns renamed. No deployments. No merges.

Canonical order: Todo, Building, Checks, Verifier, Valentin Review, Done.

- PR opened -> Checks.
- checks green -> Verifier.
- merged -> Verifier pending live proof. current-head PASS, merged, and live proof -> Done.


The related house-rules PR holds the caller inventory.
This repository runs its regression on GitHub.
DeepSeek Flash verifies this PR independently.
