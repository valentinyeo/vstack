# Park PRs above the agent cap

A board-drain label keeps at most five open PRs. `skills/board-drain/drain-check` names the newest extras and fails. `skills/board-drain/pr-park` previews parking by default and changes PRs and cards only with `--apply`.

## Sub-features

- `agent-cap` counts distinct open PRs matched to the label's tickets through reconcile's ticket keys, aliases, board URLs, branches, and card links. Five passes. Six fails and names the newest extra.
- `park` closes newest extras with the required parking comment, keeps branches, and moves their cards to Todo using the chat's own token.
- `resume` reopens the oldest parked PRs into available slots and moves their Todo cards to Checks.
- `retry` reads saved parking records and current PR states. A second run changes nothing. Interrupted card moves finish without another close or reopen, even while GitHub search is stale.
- `repo-cap` warns above the count and cap from `scripts/pr-cap.py` without failing drain-check.
- `read-failure` warns once and makes no changes when required reads fail.

## How to get to it (user POV)

Run `skills/board-drain/drain-check --board <id> --label <your label>`. Preview with `skills/board-drain/pr-park --board <id> --label <your label>`. The agent applies that plan with `--apply` on its own label.

## Driving it with verify-vstack

Run only the fake-backed journey on a GitHub-hosted runner:

```sh
timeout 300 python3 -m unittest tests.test_pr_park -v
```

The test file creates fake `gh` and `hypertask` executables and a scratch HOME. The real CLI entry points read and update those fake services. Assertions cover command arguments, card columns, token selection, dry-run, ordering, retries, and read failures. No real PR or board is changed.

## Gotchas

- Never run `--apply` against real repos to verify this feature.
- Keep `~/.local/state/board-drain/parked-<board>-<label-slug>.json`. It records which closed PRs this chat parked.
- Protected columns, waiting cards, and cards with another open PR retain their columns.
- `SHIP_SESSION_NAME` names the chat in a headless run. The tool requires that chat's agent token file and verifies the connected agent before any change. A label override such as Vstack for Vstack Maintainer still uses the chat's token.
