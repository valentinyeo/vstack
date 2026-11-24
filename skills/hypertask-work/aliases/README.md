# Old keys of moved cards

One file per board: `<board id>.json`, mapping each key a card carried before it moved
to the key it carries now.

```json
{"SOFT-2368": {"newKey": "MUBO-2"}}
```

Reconcile reads it both ways. Every card that has old keys searches GitHub for them
in the same batch as its own key, and a PR, branch or `Ticket:` line naming an old key
counts exactly like one naming the current key. The move keeps the task's internal id,
so the card is the same card; only its PRs were written under the old name.

A card can carry more than one old key. Board 2060 renamed its project key from
`IGSH-` to `SOFT-` before the move, so `IGSH-2670` and `SOFT-2670` both point at
`MUBO-65` and every pull written under either name is found.

Aliases are learned too. A board run that sees a PR naming a key it does not list
resolves that key once with `hypertask task get <key>` (no `--project`) and keeps the
answer on disk for good: the card it points at when the task is on this board, and a
"not this board's" marker when it is not. Nothing is ever asked twice.

A seed file here exists only to skip that first-run lag for a batch of moves already
made. Keep it keys only: no titles, no statuses, no other ticket content.
