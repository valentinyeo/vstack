# Report-page before a report

## Sub-features

- `report-page/SKILL.md` read before the first HTML file write.

## How to get to it (user POV)

Valentin asks for a report page to scan. The rule is that the chat builds it the report-page way, so it reads that skill first.

## Driving it with run

```sh
.claude/skills/verify-valentin-subskills/run --scenario report
```

PASS when a read of `report-page/SKILL.md` comes before the first HTML file write in the stream.

## Gotchas

- A report written as markdown instead of HTML still counts as the side effect; grade the first file write, not the extension.
- `--break report` removes the report-page line, so the same run must FAIL.
