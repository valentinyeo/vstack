# Extra gate fixture

A small repo with one verification gate pstack does not ask for: the `scorecard` job
in `.github/workflows/ci.yml`. pstack-diff must exit 1 before a chat removes it and 0
after. The `verify-app` skill and its feature map are present so the planted gate is
the only finding.
