# Read the skill

## Sub-feature

- `read`: a `Skill` call for `hypertask`, or a `Read` of a path ending `skills/hypertask/SKILL.md`.

## How to get there (user POV)

The prompt starts with `/hypertask`.

## Driving it with run

- Action: `run`. Result: `stream.jsonl`.
- Check: one of the two calls appears.

## Gotchas

- A chat that works from memory of an old skill, without reading, fails here even when its board work is right.
