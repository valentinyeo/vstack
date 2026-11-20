# Own view and label

## Sub-features

- `view.create`: a `view create` with `--project 2060` and `--label vvm-test`, with no error.
- `view.find`: a `view list --project 2060` whose result names `vvm-test`.

## Driving it with run

- Action: `run`. Result: the Bash calls and results in `stream.jsonl`.
- Check: either call appears, with the exact board and label.

## Gotchas

- A view titled something else, or with no label, fails.
