# No new PR on a repo over its cap

`scripts/pr-cap.py` owns the repo table, the cap of 10 and the open count, and
`hooks/pr-cap-guard.py` refuses a command that would open a PR above it. Every chat that
installs vstack reads the refusal from its Bash `PreToolUse` hook, and every pacer worker
reads the same refusal from a `gh` shim that `scripts/worker-shims` writes from that module.

## Sub-features

- `forms` refuses `gh pr create` in every `-R` / `--repo` form and from the cwd's origin remote, `gh api ... /pulls` with `-X POST`/`--method POST` (a field flag such as `-f` counts as POST), and an MCP `create_pull_request` tool input.
- `count` reads the open total with one `gh api` search call, keeps it for 5 minutes under `~/.local/state/vstack/pr-cap/`, and fails open with one warning line when GitHub cannot answer.
- `message` names the repo, the count, the cap and the fix: commit small units to master per the repo's CLAUDE.md; close or land open PRs first.
- `shims` writes a `gh` shim beside the heavy-local shims, so an OpenCode or Antigravity worker gets exit 2 and never starts the real `gh`.
- `wiring` registers the hook in `~/.claude/settings.json` from `./install` through `scripts/register-user-hook.py`, once however often install runs, so a Multi Bot chat whose cwd is its own project is refused too, and generates the shim from `./install`.

## How to get to it (user POV)

Nothing to type. A chat whose PR is refused reads the count and the fix line. A pacer worker
that types `gh pr create` reads the same line, because the worker shims folder carries a `gh`
shim. A repo outside the table, a count at the cap or below, and a GitHub outage all pass.

## Driving it with verify-vstack

```sh
timeout 60 python3 -m unittest tests.test_pr_cap -v
```

Every test uses a fake `gh` that answers the count from a file and a scratch HOME. The
journeys require exit 2 with the count, the cap and the fix line for every create form at 11,
exit 0 at 10, at exactly 10, for another repo and on a read failure with one warning line.
They also require the shim's refusal to be byte-identical to the hook's, and that a refused
command never starts the real `gh`.

Expected evidence includes:

```
PASS pr-cap: every create form refused at 11, allowed at 10, read failure warns and passes
```

## Gotchas

- The count is GitHub's search total, so a just-opened or just-closed PR can lag by seconds; the 5 minute cache keeps the same answer between calls.
- A repo outside `scripts/pr-cap.py`'s table is never asked, so adding a repo is a one line change there.
- A missing `gh`, or a state directory that cannot be written, still allows the PR; the warning on stderr names the repo.
- This guard reads commands, so a script that calls `gh` in a way this parser does not name still passes. The repo's own CI is the backstop.
