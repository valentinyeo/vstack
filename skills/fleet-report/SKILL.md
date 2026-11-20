---
name: fleet-report
description: >-
  Read-only snapshot of every live chat on this server: valentin-mode version loaded,
  latest version, board-drain loop, and pstack-diff self-check. Message each failing chat;
  it fixes itself.
---

# fleet-report

Prior art: checked local `board-drain`, `vps-state`, and `pstack-diff`; none fits because this is a one-shot read-only fleet table across live sessions, not a per-chat loop, host gate, or repo diff.

Shows whether each live Multibot or Claude chat on this server runs the current valentin-mode and passes its own board loop and pstack-diff checks. Read-only; exit 0 always.

## Run

```bash
python3 ~/.local/share/vstack/skills/fleet-report/fleet-report
python3 skills/fleet-report/fleet-report --json
python3 skills/fleet-report/fleet-report --html /tmp/fleet-report.html
```

Sources: `~/.local/bin/mp-sessions --json` and `~/.local/share/house-rules/fleet/roster-live` for live chats; Claude transcripts under `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`.

Columns: loaded valentin-mode version (last load line in the transcript), latest from `skills/valentin-mode/version.sh`, board-drain `loop-state status`, `pstack-diff` exit and EXTRA count, verdict **OK** / **BEHIND** / **FAILING**.

**Do not fix other chats from here.** Message each failing chat; it fixes itself.