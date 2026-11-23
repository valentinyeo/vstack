# Cloud worker lane gate

The cloud-agent launcher checks the requested vendor's shared plan before git preflight or a vendor command. A skipped, exhausted or ahead-of-pace lane refuses with exit 75 and the picker's reason. Only a missing picker allows the launch with a warning.

## Sub-features

- Codex and Claude both call `~/.local/bin/plan-pick --lane-ok <vendor> --cloud` (Cursor is refused immediately before any external command).
- Exit 3 becomes `status: limit`, exit 75 and a suggestion to use `plan-pick --run`.
- Other picker failures refuse with `status: failed` and exit 1.
- A missing picker warns once and preserves the existing launch path.

## How to get to it (user POV)

Run `skills/cloud-agent/cloud-agent codex --repo <checkout> --brief <brief-file> --no-wait`.

## Driving it with verify-vstack

Install the token-ladder dependency with `--lane-ok` support before testing a real launch. For refusal proof, use an isolated HOME, not production state or credentials.

1. Put a wrapper at the scratch HOME's `.local/bin/plan-pick` that executes the token-ladder checkout's `bin/plan-pick` with the incoming arguments plus `--pools "$HOME/pools.json"`.
2. Write `{"codex":{"state":"ON","used_pct":20,"pace_ratio":0.5}}` to the scratch `pools.json`.
3. Write `{"codex":<future Unix timestamp>}` to the scratch `.local/state/token-ladder/lane-limits.json`.
4. Write a nonempty brief. Run the command above with the scratch HOME. Expect the skip date and `plan-pick --run` on stderr, `status: limit` in the final JSON line and exit 75. No git preflight or vendor should run.
5. Run `timeout 120 python3 -m unittest discover -s tests -p test_cloud_agent.py -k PlanGateTests` for allowed, refused, missing, old, broken and timed-out picker cases across all active vendors. These use fake pickers and stub vendor launches, never production workers.

## Gotchas

- This change depends on token-ladder's `--lane-ok` API. An older installed picker refuses rather than silently bypassing the check.
- Do not test the allowed path against real vendors just to verify this gate. The focused tests record whether each vendor would be invoked.
- Exit 75 lets callers try another vendor. It does not authorize retrying the same skipped lane.
